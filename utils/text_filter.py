from pathlib import Path
import re
import config
from utils.logger import get_logger

logger = get_logger("text_filter")

# 全局加载外置噪音词库
NOISE_WORD_SET = set()
noise_file_path = Path(config.NOISE_WORD_FILE)

if noise_file_path.exists():
    try:
        with open(noise_file_path, "r", encoding="utf-8") as f:
            for line in f.readlines():
                word = line.strip()
                if word:
                    NOISE_WORD_SET.add(word)
        logger.info(f"成功加载噪音词库，共 {len(NOISE_WORD_SET)} 个过滤词汇")
    except Exception as e:
        logger.error(f"读取噪音词文件失败：{str(e)}")
else:
    logger.warning(f"噪音词库文件不存在：{noise_file_path}，将不执行语气词过滤")

# Whisper幻觉关键词
HALLUCINATION_KWS = [
    "各位领导", "大家好", "今天会议",
    "项目进度", "下一阶段", "汇报如下",
    "感谢聆听", "谢谢各位", "欢迎收听",
    "接下来", "下面我们", "本次大会", "结束语"
]
EMPTY_WORD_PATTERN = re.compile(r"嗯|啊|呃|那个|然后")
REPEAT_PATTERN = re.compile(r"(.{4,}?)\1{3,}")


def clean_transcript(raw_text: str) -> str:
    raw_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    clean_lines = []
    for line in raw_lines:
        clean_line = line
        for noise in NOISE_WORD_SET:
            clean_line = clean_line.replace(noise, "")
        if len(clean_line) >= 2:
            clean_lines.append(clean_line)
    unique_lines = list(dict.fromkeys(clean_lines))
    return "\n".join(unique_lines)


def count_valid_chinese(text: str) -> int:
    return sum(1 for c in text if "\u4e00" <= c <= "\u9fff")


def is_valid_transcript(raw_text: str) -> tuple[bool, str]:
    """
    完整校验转写文本
    返回 (是否有效, 清洗文本/失败提示)
    """
    if not raw_text or raw_text.strip() == "":
        tip = "音频无内容，未识别出任何文字，跳过AI分析"
        logger.warning(tip)
        return False, tip

    text = raw_text.strip()
    clean_text = clean_transcript(text)
    min_valid_limit = config.FILTER_MIN_VALID_CHARS

    if len(text) < min_valid_limit:
        tip = f"文本总长度不足{min_valid_limit}字符，当前仅{len(text)}字符，跳过AI分析"
        logger.warning(tip)
        return False, tip

    pure_text = re.sub(r"[^\w\u4e00-\u9fa5]", "", text)
    if len(pure_text) < 10:
        tip = "去除标点后有效文字不足10个，判定为无效文本"
        logger.warning(tip)
        return False, tip

    hit_kw_num = sum(kw in text for kw in HALLUCINATION_KWS)
    if hit_kw_num >= 2:
        tip = f"检测到{hit_kw_num}条AI幻觉话术，判定为虚假转写文本"
        logger.warning(tip)
        return False, tip

    if REPEAT_PATTERN.search(text):
        tip = "检测到大量连续重复语句，属于模型幻觉，跳过AI分析"
        logger.warning(tip)
        return False, tip

    no_digit_text = re.sub(r"[0-9\s，。！？、]", "", text)
    if len(no_digit_text) < 5:
        tip = "文本仅包含数字/标点，无有效语义文字"
        logger.warning(tip)
        return False, tip

    empty_matches = EMPTY_WORD_PATTERN.findall(text)
    if len(empty_matches) / len(text) > 0.3:
        tip = f"无意义语气词占比超过30%，有效内容过少"
        logger.warning(tip)
        return False, tip

    return True, clean_text


__all__ = ["is_valid_transcript", "clean_transcript", "count_valid_chinese"]