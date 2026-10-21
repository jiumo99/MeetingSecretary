# core/meeting_ai.py
from concurrent.futures import ThreadPoolExecutor

import json
import re
import threading

import config
from openai import OpenAI

from config import (
    OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL,
    LLM_TIMEOUT, LLM_MAX_RETRY
)

# ===================== LLM 客户端（懒加载） =====================
# 为什么不在模块顶层直接创建：打包成 exe 后，导入本模块时可能还没读到用户填写的 .env，
# 顶层创建会因 api_key 为空而直接抛异常，导致整个界面都起不来（用户连配置的机会都没有）。
# 因此改为「首次调用时才创建」，并做进程内单例缓存。
_CLIENT = None
_CLIENT_LOCK = threading.Lock()


class LLMConfigError(RuntimeError):
    """大模型配置缺失，属于用户可修复的错误，界面应友好提示而非崩溃"""


def get_client() -> OpenAI:
    """获取 LLM 客户端（懒加载 + 单例）。缺少密钥时抛出可读错误。"""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            return _CLIENT
        # 这里重新读一次，确保读到的是「已经加载过 .env 之后」的值
        api_key = config.OPENAI_API_KEY or OPENAI_API_KEY
        base_url = config.OPENAI_BASE_URL or OPENAI_BASE_URL
        if not api_key or not api_key.strip():
            raise LLMConfigError(
                "未配置大模型 API Key。\n\n"
                "请打开程序目录下的 .env 文件，填写：\n"
                "  OPENAI_API_KEY=你的密钥\n"
                "  OPENAI_BASE_URL=接口地址\n\n"
                "填写后重新启动程序即可。"
            )
        _CLIENT = OpenAI(
            api_key=api_key.strip(),
            base_url=base_url.strip() if base_url else None,
            timeout=LLM_TIMEOUT,
            max_retries=LLM_MAX_RETRY,
        )
        return _CLIENT

PROMPT = """
你是一个专业会议秘书。会议类型：{meeting_type}；会议名称：{meeting_title}
根据下面会议文字稿（可能没有标点，请自行按语义断句并添加标点）：
1. 生成结构化会议纪要（主题/讨论点/结论），要求段落清晰，标点正确。
2. 提取待办事项，格式每行：任务 | 责任人 | 截止日期(未知写待定)
3. 如果这是周会，请重点总结本周工作、问题和下周计划。

--- 文字稿 ---
{text}
--- 输出 ---
【会议纪要】
……
【待办事项】
……
"""


def summarize_and_extract(text: str, meeting_title: str = "周会", meeting_type: str = "周会") -> dict:
    resp = get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": PROMPT.format(text=text, meeting_title=meeting_title, meeting_type=meeting_type)}],
        temperature=0.2   # 降低随机性
    )
    content = resp.choices[0].message.content
    parts = content.split("【待办事项】")
    summary = parts[0].replace("【会议纪要】", "").strip()
    todos = parts[1].strip() if len(parts) > 1 else ""
    return {"summary": summary, "todos": todos}


def extract_search_tags(summary: str, todos: str) -> dict:
    extract_prompt = f"""
仅输出标准JSON，无多余文字、无解释：
1. keyword_tags：3~8个核心关键词，英文逗号分隔
2. todo_person：所有责任人，去重，英文逗号分隔
示例{{"keyword_tags":"党建,表彰,理论学习","todo_person":"党委,宣传部门"}}
会议纪要：{summary}
待办文本：{todos}
"""
    try:
        resp = get_client().chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": extract_prompt}],
            temperature=0.1
        )
        content = resp.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "")
        return json.loads(content)
    except Exception as e:
        print(f"关键词提取失败：{str(e)}")
        return {"keyword_tags": "", "todo_person": ""}


def extract_standard_tasks(full_transcript: str) -> list[dict]:
    task_prompt = """
你是会议任务提取专家，严格遵守规则：
1. 只提取需要落地执行、分配到人/部门的工作；纯理论学习、讲话、宣传不算；
2. 每条任务固定4个键：task_content, owner, deadline, priority；
3. 输出格式：仅纯JSON数组，禁止额外文字。
会议原文：
""" + full_transcript
    try:
        resp = get_client().chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": task_prompt}],
            temperature=0.1
        )
        content = resp.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").replace("\n", "").replace(" ", "")
        raw_list = json.loads(content)
        if not isinstance(raw_list, list):
            return []
        final = []
        for item in raw_list:
            final.append({
                "task_content": item.get("task_content", "").strip() or "无明确工作内容",
                "owner": item.get("owner", "").strip() or "全体成员",
                "deadline": item.get("deadline", "").strip() or "无",
                "priority": item.get("priority", "").strip() if item.get("priority") in ["高", "中", "低"] else "中"
            })
        return final
    except Exception as e:
        print(f"标准化任务提取失败：{str(e)}")
        return []


def summarize_extract_all(text: str, meeting_title: str = "周会", meeting_type: str = "周会") -> dict:
    """
    一次到位完成全部 LLM 分析，并做并行提速：
      第一轮并行：会议纪要摘要  ‖  标准化待办任务（二者互不依赖）
      第二轮：基于摘要提取检索标签/责任人
    返回 dict：summary / todos / keyword_tags / todo_person / task_list
    """
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_summary = executor.submit(summarize_and_extract, text, meeting_title, meeting_type)
        future_tasks = executor.submit(extract_standard_tasks, text)
        result = future_summary.result()
        task_list = future_tasks.result()

    tag_info = extract_search_tags(result["summary"], result["todos"])
    result["keyword_tags"] = tag_info.get("keyword_tags", "")
    result["todo_person"] = tag_info.get("todo_person", "")
    result["task_list"] = task_list
    return result


# ===================== 说话人姓名推断（对话内容线索） =====================
NAME_PROMPT = """
你是会议速记员。下面是一份多人对话文稿，每段以「[时间] SPKx：」开头。
注意：SPKx 只是系统自动分配的说话人编号（**不是真实姓名**）。本文稿中共有 {speaker_list} 这几位说话人。

请根据文稿中出现的线索（例：他人称呼"王工/李老师/张三你觉得呢"、自我介绍"我是产品部李四"、
被点名"这件事小明负责"、上下文明确指代等），推断每位说话人最可能的真实姓名或习惯称呼。

输出格式：一个 JSON 对象，键为编号数字（如 "1"），值为对象 {{"name": 姓名, "evidence": 一句话依据}}。
严格遵守：
1. **必须使用上面列出的编号**作为键；
2. evidence 必须写出具体依据（可引用原文片段）。只有当线索明确指向「说话人本人」时才给出 name，例如：
   该说话人自我介绍（"我是产品部李四"）；他人紧接着直接称呼该说话人并由其回应
   （甲："张三你说说看" → 紧接着发言的那位很可能是张三）；
3. 若说话人只是在安排或提及别人（如"这件事交给王五"），王五是第三方，**不能**把王五当作该说话人的姓名；
4. 任何一位没有把握，就不要在结果里出现该编号，绝不编造；若全部无法判断则输出 {{}}；
5. 禁止输出任何解释、注释或 markdown 代码块。

会议名称：{title}
会议类型：{meeting_type}

--- 文稿 ---
{text}
--- 输出示例（仅示意格式） ---
{{"1": {{"name": "张三", "evidence": "有人称呼'张三你来说'后由其回应"}}}}
--- 输出 JSON ---
"""


def infer_speaker_names(labeled_text: str, meeting_title: str = "", meeting_type: str = "") -> dict:
    """
    让大模型从对话内容推断说话人真实姓名。
    返回 {"names": {speaker_id: 姓名}, "evidence": {speaker_id: 推断依据}}；
    无法判断的编号不会出现在结果里（依据便于用户在界面上核对）。
    """
    if not labeled_text or not labeled_text.strip():
        return {}
    valid_nos = sorted({int(m) for m in re.findall(r"SPK(\d+)", labeled_text)})
    if not valid_nos:
        return {}
    valid_ids = {n - 1 for n in valid_nos}       # 界面从 SPK1 起 → 内部 speaker_id 从 0 起
    speaker_list = "、".join(f"SPK{n}" for n in valid_nos)

    prompt = NAME_PROMPT.format(
        text=labeled_text, title=meeting_title or "未命名会议",
        meeting_type=meeting_type or "未知", speaker_list=speaker_list,
    )
    empty = {"names": {}, "evidence": {}}
    try:
        resp = get_client().chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        content = (resp.choices[0].message.content or "").strip()
        content = content.replace("```json", "").replace("```", "").strip()
        # 容错：只截取第一个 JSON 对象
        left, right = content.find("{"), content.rfind("}")
        if left == -1 or right == -1:
            return empty
        raw = json.loads(content[left:right + 1])
        if not isinstance(raw, dict):
            return empty

        names: dict = {}
        evidence: dict = {}
        for k, v in raw.items():
            try:
                spk_no = int(str(k).strip().lstrip("SPKspk"))
            except Exception:
                continue
            spk_id = spk_no - 1              # 界面用 SPK1 起，内部 speaker_id 从 0 起
            if spk_id not in valid_ids:      # 只接受文稿里真实出现的编号
                continue
            # 兼容两种返回：{"1": "张三"} 与 {"1": {"name": "张三", "evidence": "..."}}
            if isinstance(v, dict):
                name = str(v.get("name", "")).strip()
                ev = str(v.get("evidence", "")).strip()
            else:
                name, ev = str(v).strip(), ""
            if not (1 <= len(name) <= 12):   # 过滤掉明显不是名字的回答
                continue
            names[spk_id] = name
            evidence[spk_id] = ev
        if raw and not names:
            print(f"说话人姓名推断结果与文稿编号不匹配，已忽略：{raw}")
        return {"names": names, "evidence": evidence}
    except Exception as e:
        print(f"说话人姓名推断失败：{str(e)}")
        return empty
