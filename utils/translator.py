from utils.logger import get_logger
from openai import OpenAI
from config import (
    OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL,
    LLM_TIMEOUT, LLM_MAX_RETRY, TRANSLATE_ENABLED
)

logger = get_logger("translator")

# 和 meeting_ai 相同的客户端配置：带超时与自动重试
client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    timeout=LLM_TIMEOUT,
    max_retries=LLM_MAX_RETRY,
)


def translate_to_english(content: str) -> str:
    """把中文会议文稿翻成英文。关闭开关或失败时返回空串（不污染导出文档）。"""
    if not TRANSLATE_ENABLED:
        logger.info("TRANSLATE_ENABLED=false，跳过英文翻译")
        return ""
    if not content or not content.strip():
        return ""
    prompt = f"""
将下方带时间戳、SPK发言人编号的会议对话完整翻译成英文，严格保留每行时间戳与SPK标识，仅输出英文译文，不要任何中文、解释、多余文字。
原文内容：
{content}
"""
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"翻译AI调用失败：{str(e)}")
        return ""
