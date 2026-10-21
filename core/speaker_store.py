"""
说话人声纹库 —— 把「姓名 ↔ 声纹向量」持久化到 SQLite。

解决的问题：声纹分离只能给出 SPK1/SPK2 这样的编号，无法知道真实姓名。
思路：只要用户在任何一次会议里把某人命名过一次（或确认了大模型的推断），
      就把这个人的声纹向量存进本库；以后同一人再出现，即可自动认出真名。

对外接口：
    enroll(name, embedding)      -> 登记 / 增量更新某人的声纹
    identify(embedding)          -> (姓名, 相似度)，未命中返回 ("", score)
    list_profiles()              -> [{"name","samples","created_at","updated_at"}]
    delete_profile(name)         -> 删除某人档案
    rename_profile(old, new)     -> 改名
    count()                      -> 档案数量
"""
import sqlite3
import threading

import numpy as np

import config
from utils.logger import get_logger

logger = get_logger("speaker_store")

_TABLE = "speaker_profile"
_LOCK = threading.RLock()
_CACHE: dict | None = None     # name -> np.ndarray(float32)，进程内缓存，避免反复读库
_CACHE_LOCK = threading.Lock()


# ===================== 底层工具 =====================
def _connect():
    conn = sqlite3.connect(config.DB_FILE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _to_blob(vec) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).copy()


def init_table():
    """建表（幂等）"""
    with _LOCK, _connect() as conn:
        conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            embedding BLOB NOT NULL,
            samples INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_speaker_name ON {_TABLE}(name);")


# ===================== 缓存 =====================
def _load_cache() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    with _CACHE_LOCK:
        if _CACHE is None:
            data = {}
            try:
                init_table()
                with _LOCK, _connect() as conn:
                    for row in conn.execute(f"SELECT name, embedding FROM {_TABLE}"):
                        try:
                            data[row["name"]] = _from_blob(row["embedding"])
                        except Exception:
                            continue
            except Exception as e:
                logger.error(f"读取声纹库失败：{e}")
            _CACHE = data
            logger.info(f"声纹库已加载 {len(data)} 个说话人档案")
        return _CACHE


def refresh_cache():
    global _CACHE
    _CACHE = None
    return _load_cache()


def _normalize(vec) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float32).ravel()
    n = float(np.linalg.norm(v))
    return v if n < 1e-9 else v / n


# ===================== 对外接口 =====================
def enroll(name: str, embedding, alpha: float | None = None) -> bool:
    """
    登记或更新某人的声纹。
    - 新姓名：直接入库，samples=1；
    - 已存在：新老向量做加权平均（增量学习），samples 累加。
    alpha：新样本权重（默认取 config.SPEAKER_UPDATE_ALPHA）。
    """
    name = (name or "").strip()
    if not name:
        return False
    vec = np.asarray(embedding, dtype=np.float32).ravel()
    if vec.size == 0:
        return False

    alpha = config.SPEAKER_UPDATE_ALPHA if alpha is None else float(alpha)
    alpha = min(max(alpha, 0.0), 1.0)

    try:
        init_table()
        with _LOCK, _connect() as conn:
            row = conn.execute(
                f"SELECT embedding, samples FROM {_TABLE} WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                conn.execute(
                    f"INSERT INTO {_TABLE}(name, embedding, samples) VALUES(?,?,1)",
                    (name, _to_blob(vec)),
                )
                final_vec, samples = vec, 1
                action = "新增"
            else:
                old = _from_blob(row["embedding"])
                samples = int(row["samples"] or 1) + 1
                if old.shape == vec.shape:
                    # 按样本数修正权重：样本越多，新样本影响越小
                    w = max(alpha, 1.0 / samples)
                    merged = (1.0 - w) * old + w * vec
                else:
                    merged = vec
                final_vec = merged.astype(np.float32)
                conn.execute(
                    f"UPDATE {_TABLE} SET embedding=?, samples=?, updated_at=CURRENT_TIMESTAMP "
                    f"WHERE name=?",
                    (_to_blob(final_vec), samples, name),
                )
                action = "更新"
        with _CACHE_LOCK:
            # 缓存未加载时无需处理：下次 _load_cache() 会直接从库里读到最新结果
            if _CACHE is not None:
                _CACHE[name] = final_vec
        logger.info(f"声纹{action}：{name}（累计 {samples} 个样本）")
        return True
    except Exception as e:
        logger.error(f"声纹登记失败 {name}: {e}")
        return False


def identify(embedding, threshold: float | None = None) -> tuple[str, float]:
    """
    在声纹库里找最相似的人。
    返回 (姓名, 相似度)；未达阈值时姓名为 ""，但仍返回最高分供界面参考。
    """
    thr = config.SPEAKER_MATCH_THRESHOLD if threshold is None else float(threshold)
    cache = _load_cache()
    if not cache:
        return "", 0.0
    q = _normalize(embedding)
    if q.size == 0:
        return "", 0.0
    best_name, best_score = "", -1.0
    for name, vec in cache.items():
        if vec.shape != q.shape:
            continue
        score = float(np.dot(q, _normalize(vec)))
        if score > best_score:
            best_score, best_name = score, name
    if best_score >= thr:
        return best_name, best_score
    return "", best_score


def list_profiles() -> list[dict]:
    try:
        init_table()
        with _LOCK, _connect() as conn:
            rows = conn.execute(
                f"SELECT name, samples, created_at, updated_at FROM {_TABLE} ORDER BY updated_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"列出声纹档案失败：{e}")
        return []


def delete_profile(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    try:
        with _LOCK, _connect() as conn:
            conn.execute(f"DELETE FROM {_TABLE} WHERE name = ?", (name,))
        with _CACHE_LOCK:
            if _CACHE is not None:
                _CACHE.pop(name, None)
        logger.info(f"已删除声纹档案：{name}")
        return True
    except Exception as e:
        logger.error(f"删除声纹档案失败 {name}: {e}")
        return False


def rename_profile(old_name: str, new_name: str) -> bool:
    old_name, new_name = (old_name or "").strip(), (new_name or "").strip()
    if not old_name or not new_name or old_name == new_name:
        return False
    try:
        with _LOCK, _connect() as conn:
            conn.execute(
                f"UPDATE {_TABLE} SET name=?, updated_at=CURRENT_TIMESTAMP WHERE name=?",
                (new_name, old_name),
            )
        with _CACHE_LOCK:
            if _CACHE is not None and old_name in _CACHE:
                _CACHE[new_name] = _CACHE.pop(old_name)
        logger.info(f"声纹档案改名：{old_name} → {new_name}")
        return True
    except Exception as e:
        logger.error(f"声纹档案改名失败 {old_name}→{new_name}: {e}")
        return False


def count() -> int:
    return len(_load_cache())


def names() -> list[str]:
    return list(_load_cache().keys())
