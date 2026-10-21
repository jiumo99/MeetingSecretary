import sys
from pathlib import Path

# 项目根目录加入搜索路径，保证可作为脚本直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import uvicorn

import config
from utils.logger import get_logger
from utils.file_helper import check_disk_free, audio_file_verify
from utils.text_filter import is_valid_transcript
from core.recorder import record_audio
from core.transcribe import transcribe
from core.meeting_ai import summarize_and_extract
from db.db import init_db, save_meeting, list_meetings, get_meeting_by_id
from service.exporter import export_docx, export_pdf, export_pptx, export_xmind
from service.mailer import send_todo_email

app = FastAPI(title="会议纪要工具接口")
# 初始化日志
logger = get_logger("fastapi-server")


# 全局统一异常捕获，所有报错统一返回json，不打印底层堆栈给调用方
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    err_msg = str(exc)
    logger.error(f"接口全局异常：{err_msg}", exc_info=True)
    return JSONResponse(content={"code": -1, "msg": err_msg})


# 初始化数据库
init_db()


# 1. 开始录音接口（日志+磁盘校验）
@app.post("/api/record")
def start_record(title: str, duration: int = None):
    logger.info(f"调用录音接口，会议名称：{title}")
    if not check_disk_free():
        return {"code": -1, "msg": "磁盘剩余空间不足，无法录音", "audio_path": ""}
    path = record_audio(f"{title}.wav", duration)
    logger.info(f"录音完成，文件路径：{path}")
    return {"code": 0, "audio_path": path}


# 2. 音频转写接口（音频校验+磁盘校验+日志）
@app.post("/api/transcribe")
def audio_to_text(audio_path: str):
    logger.info(f"调用转写接口，音频路径：{audio_path}")
    audio_ok, tip = audio_file_verify(audio_path)
    if not audio_ok:
        return {"code": -1, "msg": tip, "text": "", "valid": False}
    if not check_disk_free():
        return {"code": -1, "msg": "磁盘空间不足，无法执行转写", "text": "", "valid": False}
    text = transcribe(audio_path)
    valid, _ = is_valid_transcript(text)
    logger.info(f"转写完成，文本长度：{len(text)}，有效文本：{valid}")
    return {"code": 0, "text": text, "valid": valid}


# 3. AI生成纪要&待办（日志+自动拦截无效文本）
@app.post("/api/ai_summary")
def ai_analysis(text: str, title: str, meeting_type: str):
    logger.info(f"调用AI摘要，会议：{title}，类型：{meeting_type}")
    valid_text_flag, _ = is_valid_transcript(text)
    if not valid_text_flag:
        return {"code": -1, "msg": "文本内容过少/无有效语义，跳过AI分析", "data": None}
    res = summarize_and_extract(text, title, meeting_type)
    logger.info(f"AI纪要生成完成：{title}")
    return {"code": 0, "data": res}


# 4. 保存会议记录到数据库（日志）
@app.post("/api/save_meeting")
def save_record(title: str, audio_path: str, transcript: str, summary: str, todos: str,
                meeting_type: str = "", todo_person: str = "", keyword_tags: str = ""):
    logger.info(f"保存会议记录：{title}")
    meet_id = save_meeting(
        title=title, meeting_type=meeting_type, audio_path=audio_path,
        transcript=transcript, summary=summary, todos=todos,
        todo_person=todo_person, keyword_tags=keyword_tags
    )
    return {"code": 0, "msg": "保存成功", "meet_id": meet_id}


# 5. 导出文档接口（磁盘校验+日志）
@app.post("/api/export")
def export_file(title: str, transcript: str, summary: str, todos: str):
    logger.info(f"导出文档，会议：{title}")
    if not check_disk_free():
        return {"code": -1, "msg": "磁盘空间不足，无法导出文档", "docx": "", "pdf": ""}
    docx = export_docx(title, transcript, summary, todos)
    pdf = export_pdf(title, summary, todos)
    return {"code": 0, "docx": docx, "pdf": pdf}


@app.post("/api/export_pptx")
def export_pptx_api(title: str, summary: str, todos: str, dialogue_text: str = ""):
    logger.info(f"导出PPT，会议：{title}")
    if not check_disk_free():
        return {"code": -1, "msg": "磁盘空间不足"}
    path = export_pptx(title, summary, todos, dialogue_text)
    return {"code": 0, "path": path}


@app.post("/api/export_xmind")
def export_xmind_api(title: str, summary: str, todos: str):
    logger.info(f"导出思维导图，会议：{title}")
    if not check_disk_free():
        return {"code": -1, "msg": "磁盘空间不足"}
    path = export_xmind(title, summary, todos)
    return {"code": 0, "path": path}


# 6. 发送邮件（日志）
@app.post("/api/send_email")
def send_email(to_addr: str, title: str, todos: str):
    logger.info(f"发送待办邮件，收件人：{to_addr}，会议：{title}")
    send_todo_email(to_addr, title, todos)
    return {"code": 0, "msg": "邮件发送完成"}


# 7. 查询历史会议列表（分页+搜索，兼容旧返回格式）
@app.get("/api/meeting_list")
def get_meetings(
    page: int = Query(1, description="页码"),
    page_size: int = Query(15, description="每页条数"),
    keyword: str = Query("", description="标题搜索关键词")
):
    data_list, total = list_meetings(page=page, page_size=page_size, keyword=keyword)
    return {
        "code": 0,
        "list": data_list,
        "total": total,
        "page": page,
        "page_size": page_size
    }


# 8. 根据ID查看单条完整会议详情
@app.get("/api/meeting_detail")
def get_meeting_detail(m_id: int):
    data = get_meeting_by_id(m_id)
    if not data:
        return {"code": -1, "msg": "未找到对应会议记录", "data": None}
    return {"code": 0, "data": data}


if __name__ == "__main__":
    logger.info("FastAPI 会议纪要服务启动，地址 127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
