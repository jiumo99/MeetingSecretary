import logging
from logging.handlers import TimedRotatingFileHandler
import config

def get_logger(name: str):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR
    }
    log_level = level_map.get(config.LOG_LEVEL, logging.INFO)
    logger.setLevel(log_level)

    log_format = "%(asctime)s | %(levelname)-6s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, datefmt=date_format)

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件日志 按天切割
    if config.LOG_DAY_SPLIT:
        log_path = config.LOG_ROOT / "app.log"
        file_handler = TimedRotatingFileHandler(
            log_path, when="D", interval=1, backupCount=30, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger

# 密钥脱敏打印工具
def mask_secret(content: str) -> str:
    if content.startswith("sk-") and len(content) > 12:
        return content[:6] + "******" + content[-6:]
    return content