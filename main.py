import sys
import atexit

# 项目根目录加入Python搜索路径
from pathlib import Path
BASE = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE))

# 全局配置与工具层优先导入
import config
from utils.logger import get_logger, mask_secret
from utils.file_helper import check_disk_free, audio_file_verify, clean_overdue_cache
from utils.text_filter import is_valid_transcript
from utils.translator import translate_to_english

# 分层业务导入
from core.recorder import record_audio
from core.transcribe import transcribe, transcribe_with_speakers   # 普通转写 + 带声纹分离的转写
from core.meeting_ai import summarize_and_extract, extract_search_tags, extract_standard_tasks, summarize_extract_all
from db.db import init_db, save_meeting, batch_insert_tasks
from service.exporter import export_docx, export_pdf
from service.mailer import send_todo_email

# 初始化日志
logger = get_logger("main-console")

# -------------------------- 1. 启动配置自检 --------------------------
cfg_ok, err_list = config.check_config_valid()
if not cfg_ok:
    logger.critical("程序配置校验失败，即将退出")
    for err in err_list:
        logger.error(f"- {err}")
    sys.exit(1)

logger.info("========================================")
logger.info("控制台会议纪要工具启动，配置校验通过")
logger.info(f"LLM密钥加载完成：{mask_secret(config.OPENAI_API_KEY)}")
logger.info(f"音频缓存目录：{config.RECORD_ROOT.resolve()}")
logger.info(f"文档导出目录：{config.EXPORT_ROOT.resolve()}")
logger.info("========================================")

# 初始化数据库（自动升级表结构、创建任务表）
init_db()
logger.info("数据库初始化完成：会议多维检索表+标准化待办任务表就绪")

# -------------------------- 2. 退出钩子：自动清理过期缓存 --------------------------
@atexit.register
def exit_clean_cache():
    logger.info("程序退出，执行过期缓存清理")
    clean_overdue_cache(config.CHUNK_CACHE_DIR)
    clean_overdue_cache(config.TRANS_CACHE_DIR)
    logger.info("缓存清理完成")

# -------------------------- 3. 统一异常捕获包装函数 --------------------------
def safe_exec(task_func, error_desc: str):
    """通用执行包装：校验磁盘+捕获异常，返回(是否成功, 结果/错误提示)"""
    try:
        if not check_disk_free():
            raise RuntimeError("磁盘剩余空间不足，无法执行操作")
        return True, task_func()
    except Exception as e:
        err_msg = f"{error_desc}：{str(e)}"
        logger.error(err_msg, exc_info=True)
        return False, err_msg

# -------------------------- 主业务流程 --------------------------
if __name__ == "__main__":
    # 输入交互
    meeting_type = input("会议类型（默认：周会）：").strip() or "周会"
    title = input("会议名称（默认同类型名称）：").strip() or meeting_type
    audio_filename = f"{title}.wav"

    # 1. 录音
    logger.info(f"开始录制音频，文件名：{audio_filename}")
    ok_record, audio_path = safe_exec(lambda: record_audio(filename=audio_filename), "录音失败")
    if not ok_record:
        print(f"❌ {audio_path}")
        sys.exit(1)
    logger.info(f"录音完成，文件路径：{audio_path}")

    # 2. 音频前置校验
    audio_ok, audio_tip = audio_file_verify(audio_path)
    if not audio_ok:
        logger.warning(f"音频校验不通过：{audio_tip}")
        print(f"❌ {audio_tip}")
        sys.exit(1)

    # 3. 转写（按 .env 的 SPEAKER_DIARIZATION_ENABLED 决定是否做声纹分离）
    print("🔤 转文字中…")
    logger.info(f"开始转写，声纹分离开关：{config.SPEAKER_DIARIZATION_ENABLED}")
    ok_trans, trans_res = safe_exec(lambda: transcribe_with_speakers(audio_path), "音频转写失败")
    if not ok_trans:
        print(f"❌ {trans_res}")
        sys.exit(1)
    labeled_text, raw_text = trans_res
    # dialog_text 用于导出时的“完整对话”字段：有发言人文稿则优先使用
    dialog_text = labeled_text if labeled_text else raw_text
    print("✅ 转写完成，前100字：", dialog_text[:100])
    logger.info(f"转写完成，总文本长度：{len(dialog_text)}，含发言人区分：{bool(labeled_text)}")

    if config.TRANSLATE_ENABLED:
        print("🌐 正在生成英文双语文稿…")
        ok_trans_en, en_dialog = safe_exec(lambda: translate_to_english(dialog_text), "双语翻译失败")
        if not ok_trans_en or not en_dialog:
            en_dialog = ""
            logger.warning("英文翻译跳过/失败，导出文档将不含英文部分")
        else:
            logger.info("英文翻译完成")
    else:
        en_dialog = ""
        logger.info("已关闭英文翻译（TRANSLATE_ENABLED=false）")

    # 4. 文本有效性校验，获取清洗后纯净文本
    valid_text, clean_text = is_valid_transcript(raw_text)
    if not valid_text:
        logger.warning(f"文本校验失败：{clean_text}")
        print(f"⚠️ {clean_text}，跳过AI分析")
        sys.exit(0)
    logger.info("文本校验通过，无意义语气词已清洗")

    # 5. AI生成纪要（摘要、待办、检索标签、责任人一次到位，内部并行调用）
    print("🤖 AI分析中…")
    logger.info(f"调用大模型生成纪要，会议标题：{title}，类型：{meeting_type}")
    # 有发言人文稿时用带 SPK 的文稿，AI 更容易把待办归到正确的人
    analyze_text = dialog_text if labeled_text else clean_text
    ok_ai, res = safe_exec(lambda: summarize_extract_all(analyze_text, title, meeting_type), "AI纪要生成失败")
    if not ok_ai:
        print(f"❌ {res}")
        sys.exit(1)
    keyword_tags = res["keyword_tags"]
    todo_person = res["todo_person"]
    task_list = res["task_list"]
    logger.info(f"AI分析完成：关键词={keyword_tags}，责任人={todo_person}，标准化待办{len(task_list)}条")

    # 控制台打印结果
    print("\n===== 会议纪要 =====")
    print(res["summary"])
    print("\n===== 待办 =====")
    print(res["todos"])

    # 6. 存入数据库
    ok_save, meet_id = safe_exec(
        lambda: save_meeting(
            title=title,
            meeting_type=meeting_type,
            audio_path=audio_path,
            transcript=raw_text,
            summary=res["summary"],
            todos=res["todos"],
            todo_person=todo_person,
            keyword_tags=keyword_tags
        ),
        "保存会议记录到数据库失败"
    )
    if ok_save:
        logger.info(f"会议记录已入库：{title}，会议唯一ID={meet_id}")
        batch_insert_tasks(meet_id, task_list)
        logger.info(f"会议{meet_id}待办任务全部写入任务跟踪表")
    else:
        print(f"❌ 数据库保存失败：{meet_id}")

    # 7. 导出Word、PDF
    print("\n📄 正在导出文档…")
    ok_docx, docx_path = safe_exec(
        lambda: export_docx(title, raw_text, res["summary"], res["todos"], dialogue_text=dialog_text, en_dialogue=en_dialog),
        "Word文档导出失败")
    ok_pdf, pdf_path = safe_exec(
        lambda: export_pdf(title, res["summary"], res["todos"], dialogue_text=dialog_text, en_dialogue=en_dialog),
        "PDF文档导出失败")
    print("已导出文件：")
    if ok_docx:
        print(f"- Word：{docx_path}")
        logger.info(f"Word导出成功：{docx_path}")
    else:
        print(f"- Word导出失败：{docx_path}")
    if ok_pdf:
        print(f"- PDF：{pdf_path}")
        logger.info(f"PDF导出成功：{pdf_path}")
    else:
        print(f"- PDF导出失败：{pdf_path}")

    # 8. 发送邮件
    send_choice = input("\n发送待办邮件？(y/n):").strip().lower()
    if send_choice == "y":
        mail_addr = input("收件人邮箱：").strip()
        ok_mail, _ = safe_exec(lambda: send_todo_email(mail_addr, title, res["todos"]), "邮件发送失败")
        if ok_mail:
            print("✅ 邮件发送完成")
            logger.info(f"待办邮件发送成功，收件人：{mask_secret(mail_addr)}")
        else:
            print(f"❌ 邮件发送失败：{_}")

    logger.info("控制台流程全部执行完毕，程序正常结束")