import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import config
from utils.logger import get_logger

logger = get_logger("file_helper")

def check_disk_free(min_mb: float = 200) -> bool:
    """校验磁盘剩余空间，低于阈值返回False，阻断转写/导出"""
    usage = shutil.disk_usage(".")
    free_mb = usage.free / 1024 / 1024
    if free_mb < min_mb:
        logger.warning(f"磁盘剩余空间不足 {free_mb:.2f}MB，至少需要 {min_mb}MB")
        return False
    return True

def clean_overdue_cache(target_dir: Path):
    """清理超过配置天数的缓存分片、断点文件"""
    expire_day = config.CACHE_EXPIRE_DAYS
    expire_time = datetime.now() - timedelta(days=expire_day)
    delete_num = 0
    if not target_dir.exists():
        return
    for root, _, files in os.walk(target_dir):
        for fname in files:
            fpath = Path(root) / fname
            modify_time = datetime.fromtimestamp(fpath.stat().st_mtime)
            if modify_time < expire_time:
                try:
                    os.remove(fpath)
                    delete_num += 1
                except Exception as e:
                    logger.error(f"删除缓存失败 {fpath}: {str(e)}")
    logger.info(f"缓存清理完成，共删除{delete_num}个过期文件")

def audio_file_verify(audio_path: str) -> tuple[bool, str]:
    """音频前置校验：存在、非空、格式支持"""
    p = Path(audio_path)
    if not p.exists():
        return False, "音频文件不存在"
    if p.stat().st_size < 1024:
        return False, "音频文件为空/损坏"
    suffix = p.suffix.lower()
    support_suffix = [".wav", ".mp3", ".m4a", ".flac"]
    if suffix not in support_suffix:
        return False, f"仅支持音频格式：{support_suffix}"
    return True, "校验通过"