import os
import sys
from pathlib import Path
import dotenv   # 改为导入整个包

# 项目根目录（兼容 PyInstaller 打包）
# - frozen（exe）：代码/静态资源在 sys._MEIPASS 临时目录，但数据目录必须落在 exe 同级，
#   否则用户的数据会被写进临时目录、退出即丢。故拆成 RESOURCE_DIR / BASE_DIR 两个概念。
# - 源码运行：两者都是项目根目录。
if getattr(sys, "frozen", False):
    RESOURCE_DIR = Path(sys._MEIPASS)              # 只读资源：static/ 等
    BASE_DIR = Path(sys.executable).parent.resolve()  # 可写数据：models/ records/ exports/ 等
else:
    RESOURCE_DIR = Path(__file__).parent.resolve()
    BASE_DIR = RESOURCE_DIR

# 加载 .env 配置文件（如果存在）
# 优先读 exe / 项目根目录下的 .env，找不到再退回打包内的默认 .env
dotenv.load_dotenv(BASE_DIR / ".env", override=True)
if not (BASE_DIR / ".env").exists():
    dotenv.load_dotenv(RESOURCE_DIR / ".env", override=True)

# ===================== 设置 Hugging Face 镜像（国内加速） =====================
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "")
if HF_ENDPOINT:
    os.environ["HF_ENDPOINT"] = HF_ENDPOINT

# 新版 huggingface_hub 默认走 Xet 协议，国内镜像（hf-mirror）不支持会导致下载 401，默认禁用
if os.getenv("HF_HUB_DISABLE_XET", "1").lower() in ("1", "true", "yes"):
    os.environ["HF_HUB_DISABLE_XET"] = "1"

def get_abs_path(relative_path: str) -> Path:
    """把相对路径解析为可写数据目录下的绝对路径（exe 模式下即 exe 同级）"""
    p = Path(relative_path)
    if p.is_absolute():
        return p
    return BASE_DIR / relative_path


def get_resource_path(relative_path: str) -> Path:
    """把相对路径解析为只读资源目录下的绝对路径（打包内的 static/ 等）"""
    p = Path(relative_path)
    if p.is_absolute():
        return p
    return RESOURCE_DIR / relative_path

# ===================== LLM大模型接口配置 =====================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-turbo").strip()
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", 30))
LLM_MAX_RETRY = int(os.getenv("LLM_MAX_RETRY", 3))
LLM_RATE_LIMIT = int(os.getenv("LLM_RATE_LIMIT", 10))
# 是否在主流程生成英文双语文稿（关闭可加快整体处理速度）
TRANSLATE_ENABLED = os.getenv("TRANSLATE_ENABLED", "true").lower() == "true"

# ===================== 邮件推送配置 =====================
MY_EMAIL = os.getenv("MY_EMAIL", "")
MY_EMAIL_PASS = os.getenv("MY_EMAIL_PASS", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))

# ===================== 语音转写Whisper配置（faster-whisper） =====================
# 注意：.env 里手写常带首尾空格，这里必须 strip，否则会拼出错误的模型路径/仓库名
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small").strip()
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "zh").strip()
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
# 计算精度：cpu 推荐 int8；cuda 可用 float16 / int8_float16
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
# 解码 beam 宽度：越小越快、越大越准（1=贪心最快）
WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", 5))
# 是否开启 VAD 语音活动检测（跳过静音段，显著加速）
WHISPER_VAD = os.getenv("WHISPER_VAD", "true").lower() == "true"
# 静音判定阈值（毫秒），超过则视为静音段跳过
WHISPER_VAD_MIN_SILENCE_MS = int(os.getenv("WHISPER_VAD_MIN_SILENCE_MS", 500))
# 长音频分片长度（秒）：分片后可按片缓存、断点续跑、上报进度
AUDIO_CHUNK_SECONDS = int(os.getenv("AUDIO_CHUNK_SECONDS", 300))
CACHE_EXPIRE_DAYS = int(os.getenv("CACHE_EXPIRE_DAYS", 7))
# 是否复用转写缓存（同一段音频命中缓存直接返回，跳过推理）
TRANSCRIBE_CACHE_ENABLED = os.getenv("TRANSCRIBE_CACHE_ENABLED", "true").lower() == "true"

# ===================== 说话人分离（声纹分离）配置 =====================
# 总开关：关闭后只做普通转写（不区分发言人）
SPEAKER_DIARIZATION_ENABLED = os.getenv("SPEAKER_DIARIZATION_ENABLED", "true").lower() == "true"
# 声纹聚类阈值：越大越倾向把不同人并成同一人（人数偏少），越小越容易拆成多人
# 实测（真实 4 人音频）：0.6~0.75 → 4 人正确；0.8 及以上会过度合并成 3 人
SPEAKER_CLUSTER_THRESHOLD = float(os.getenv("SPEAKER_CLUSTER_THRESHOLD", "0.7"))
# 已知说话人数时填正整数；-1 表示自动判断
SPEAKER_NUM_CLUSTERS = int(os.getenv("SPEAKER_NUM_CLUSTERS", "-1"))
# 语音片段边界（秒），一般无需修改
SPEAKER_MIN_DURATION_ON = float(os.getenv("SPEAKER_MIN_DURATION_ON", "0.3"))
SPEAKER_MIN_DURATION_OFF = float(os.getenv("SPEAKER_MIN_DURATION_OFF", "0.5"))
# 声纹模型目录（分段模型 + 声纹向量模型）
DIARIZATION_MODEL_DIR = get_abs_path(os.getenv("DIARIZATION_MODEL_DIR", "models/speaker-diarization"))

# ===================== 说话人姓名识别（声纹库 + 大模型推断） =====================
# 声纹库总开关：开启后，已在库里登记过的人可被自动认出真实姓名
SPEAKER_STORE_ENABLED = os.getenv("SPEAKER_STORE_ENABLED", "true").lower() == "true"
# 声纹匹配阈值（余弦相似度，越大越严格）：达到阈值才认定为同一人
SPEAKER_MATCH_THRESHOLD = float(os.getenv("SPEAKER_MATCH_THRESHOLD", "0.55"))
# 声纹增量学习融合系数：0.35 表示新样本以 35% 权重并入旧档案
SPEAKER_UPDATE_ALPHA = float(os.getenv("SPEAKER_UPDATE_ALPHA", "0.35"))
# 是否允许大模型从对话内容里推断说话人姓名（零操作，但可能猜错，需人工确认）
SPEAKER_AI_NAME_ENABLED = os.getenv("SPEAKER_AI_NAME_ENABLED", "true").lower() == "true"

# ===================== 目录路径配置 =====================
RECORDS_DIR = os.getenv("RECORD_ROOT", "records")
RECORD_ROOT = get_abs_path(RECORDS_DIR)
CHUNK_CACHE_DIR = RECORD_ROOT / os.getenv("CHUNK_CACHE_DIR", "chunks_cache")
TRANS_CACHE_DIR = RECORD_ROOT / os.getenv("TRANS_CACHE_DIR", "trans_cache")

EXPORTS_DIR = os.getenv("EXPORT_ROOT", "exports")
EXPORT_ROOT = get_abs_path(EXPORTS_DIR)

# 本地模型目录：faster-whisper 模型直接下载到项目内，真实文件、可随项目迁移
MODELS_ROOT = get_abs_path(os.getenv("MODELS_ROOT", "models"))

DB_FILE_PATH = get_abs_path(os.getenv("DB_FILE_PATH", "meetings.db"))
DB_BACKUP_ROOT = get_abs_path(os.getenv("DB_BACKUP_ROOT", "backups"))
# 数据库备份策略：两次备份最小间隔（分钟），间隔内重复写操作不再备份
DB_BACKUP_MIN_INTERVAL_MIN = int(os.getenv("DB_BACKUP_MIN_INTERVAL_MIN", "30"))
# 备份文件最多保留份数，超出后自动删除最旧的
DB_BACKUP_KEEP = int(os.getenv("DB_BACKUP_KEEP", "20"))
LOG_ROOT = get_abs_path(os.getenv("LOG_ROOT", "logs"))
# static/ 是随程序分发的只读资源，打包后位于 sys._MEIPASS 内
STATIC_DIR = get_resource_path(os.getenv("STATIC_ROOT", "static"))

# ===================== 文本过滤配置 =====================
FILTER_MIN_VALID_CHARS = int(os.getenv("FILTER_MIN_VALID_CHARS", 80))
NOISE_WORD_FILE = STATIC_DIR / os.getenv("NOISE_WORD_FILE", "noise_words.txt")

# ===================== AI提示词模板 =====================
PROMPT_TEMPLATE_FILE = STATIC_DIR / os.getenv("PROMPT_TEMPLATE_PATH", "meeting_prompt.txt")

# ===================== 日志配置 =====================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_SPLIT_BY_DAY = os.getenv("LOG_SPLIT_BY_DAY", "true").lower() == "true"
LOG_DAY_SPLIT = LOG_SPLIT_BY_DAY

# ===================== 自动创建全部缺失目录 =====================
def init_all_project_dirs():
    dir_list = [
        RECORD_ROOT, CHUNK_CACHE_DIR, TRANS_CACHE_DIR,
        EXPORT_ROOT, DB_BACKUP_ROOT, LOG_ROOT, STATIC_DIR
    ]
    for folder in dir_list:
        folder.mkdir(exist_ok=True, parents=True)

init_all_project_dirs()

# ===================== 配置校验函数 =====================
def check_config_valid() -> tuple[bool, list[str]]:
    error_msg = []
    if not OPENAI_API_KEY:
        error_msg.append("缺失配置：OPENAI_API_KEY，请在.env文件填写大模型密钥")
    if not OPENAI_BASE_URL:
        error_msg.append("缺失配置：OPENAI_BASE_URL，请填写兼容接口地址")
    if not MY_EMAIL or not MY_EMAIL_PASS:
        error_msg.append("邮箱配置不完整，邮件发送功能将无法使用")
    return len(error_msg) == 0, error_msg