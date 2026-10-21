"""
说话人分离（声纹分离）——基于 sherpa-onnx 的离线管线。

流程：音频 → pyannote 语音分段 → 声纹向量（CamPP-Plus 中文模型）→ 聚类 → (start, end, speaker)

设计原则：
- 依赖/模型缺失时 `is_available()` 返回 False，调用方自动降级为普通转写，绝不阻断主流程；
- 引擎进程内只初始化一次（常驻），与转写模型一致。
"""
import threading
from pathlib import Path

import numpy as np

import config
from utils.logger import get_logger

logger = get_logger("diarize")

_ENGINE = None
_ENGINE_LOCK = threading.Lock()
_AVAILABLE = None  # None=未检测 / True / False
_NUM_CLUSTERS_OVERRIDE = None  # 用户在界面上指定的说话人数（None=自动判断）

SEG_MODEL_NAME = "model.onnx"
EMB_MODEL_NAME = "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"


def _seg_model_path() -> Path:
    return Path(config.DIARIZATION_MODEL_DIR) / "segmentation" / SEG_MODEL_NAME


def _emb_model_path() -> Path:
    return Path(config.DIARIZATION_MODEL_DIR) / "embedding" / EMB_MODEL_NAME


def is_available() -> bool:
    """声纹分离是否可用（已装 sherpa-onnx 且模型齐全）"""
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    try:
        import sherpa_onnx  # noqa: F401
    except Exception as e:
        logger.warning(f"未安装 sherpa-onnx，声纹分离不可用：{e}")
        _AVAILABLE = False
        return False
    if not _seg_model_path().exists() or not _emb_model_path().exists():
        logger.warning(
            f"声纹模型缺失，声纹分离不可用。需要：\n  {_seg_model_path()}\n  {_emb_model_path()}"
        )
        _AVAILABLE = False
        return False
    _AVAILABLE = True
    return True


def _effective_num_clusters():
    """实际使用的说话人数：界面指定优先，否则用配置（-1 表示自动）。"""
    if _NUM_CLUSTERS_OVERRIDE is not None:
        return int(_NUM_CLUSTERS_OVERRIDE)
    return config.SPEAKER_NUM_CLUSTERS


def set_num_clusters(n):
    """
    指定本次会议的说话人数（None 或 <=0 表示自动判断）。
    人数在引擎构造时确定，因此变更后会重建引擎，于下次分离生效。
    """
    global _NUM_CLUSTERS_OVERRIDE, _ENGINE
    n = None if (n is None or int(n) <= 0) else int(n)
    if n == _NUM_CLUSTERS_OVERRIDE:
        return
    with _ENGINE_LOCK:
        _NUM_CLUSTERS_OVERRIDE = n
        _ENGINE = None
    logger.info(f"说话人数已设为：{'自动判断' if n is None else str(n) + ' 人'}（分离引擎已重建）")


def get_num_clusters():
    return _NUM_CLUSTERS_OVERRIDE


def _get_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            import sherpa_onnx
            cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
                segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                    pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                        model=str(_seg_model_path())
                    ),
                ),
                embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(_emb_model_path())
                ),
                clustering=sherpa_onnx.FastClusteringConfig(
                    num_clusters=_effective_num_clusters(),
                    threshold=config.SPEAKER_CLUSTER_THRESHOLD,
                ),
                min_duration_on=config.SPEAKER_MIN_DURATION_ON,
                min_duration_off=config.SPEAKER_MIN_DURATION_OFF,
            )
            _ENGINE = sherpa_onnx.OfflineSpeakerDiarization(cfg)
            logger.info(f"声纹分离引擎就绪（要求采样率 {_ENGINE.sample_rate}Hz）")
        return _ENGINE


# ===================== 声纹向量提取（用于声纹库匹配/登记） =====================
_EXTRACTOR = None
_EXTRACTOR_LOCK = threading.Lock()


def _get_extractor():
    """声纹向量提取器（常驻单例，与分离引擎分别初始化）"""
    global _EXTRACTOR
    if _EXTRACTOR is not None:
        return _EXTRACTOR
    with _EXTRACTOR_LOCK:
        if _EXTRACTOR is None:
            import sherpa_onnx
            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(_emb_model_path()))
            _EXTRACTOR = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
            logger.info(f"声纹提取器就绪（向量维度 {_EXTRACTOR.dim}）")
        return _EXTRACTOR


def embedding_dim() -> int:
    return int(_get_extractor().dim)


def extract_embedding(audio: np.ndarray, fs: int, start: float = None, end: float = None) -> np.ndarray:
    """提取一段音频的声纹向量（float32 一维数组）；start/end 为秒，缺省则整段。"""
    ext = _get_extractor()
    seg = audio
    if start is not None:
        s = max(0, int(start * fs))
        e = len(audio) if end is None else max(s, int(end * fs))
        seg = audio[s:e]
    seg = np.ascontiguousarray(seg, dtype=np.float32)
    if seg.size < int(0.25 * fs):
        raise RuntimeError("音频片段过短，无法提取声纹（需 ≥0.25 秒）")
    stream = ext.create_stream()
    stream.accept_waveform(fs, seg)
    stream.input_finished()
    return np.asarray(ext.compute(stream), dtype=np.float32).ravel()


def speaker_embeddings(audio: np.ndarray, fs: int, diar_segments: list, max_segments: int = 5) -> dict:
    """
    为每个说话人计算「代表声纹向量」：取其时长最长的若干段分别提向量，再做时长加权平均。
    返回 {speaker_id: np.ndarray}
    """
    by_spk: dict = {}
    for s, e, spk in diar_segments:
        dur = e - s
        if dur < 0.5:                       # 太短的片段声纹不稳，跳过
            continue
        by_spk.setdefault(spk, []).append((s, e, dur))

    result: dict = {}
    for spk, segs in by_spk.items():
        segs.sort(key=lambda x: -x[2])
        vecs, weights = [], []
        for s, e, dur in segs[:max_segments]:
            try:
                vecs.append(extract_embedding(audio, fs, s, e))
                weights.append(dur)
            except Exception as e_:
                logger.warning(f"说话人 {spk + 1} 片段声纹提取失败（{s:.1f}-{e:.1f}s）：{e_}")
        if not vecs:
            continue
        w = np.asarray(weights, dtype=np.float32)
        w = w / w.sum() if w.sum() > 0 else np.ones_like(w) / len(w)
        result[spk] = np.average(np.stack(vecs), axis=0, weights=w).astype(np.float32)
    return result


def diarize(audio: np.ndarray, fs: int) -> list:
    """
    对整段音频做说话人分离。
    audio: float32 单声道，取值范围 [-1, 1]
    返回：[(start_sec, end_sec, speaker_id), ...]（按时间排序）
    """
    engine = _get_engine()
    if fs != engine.sample_rate:
        raise RuntimeError(f"声纹分离要求 {engine.sample_rate}Hz，当前 {fs}Hz，请先重采样")
    padded = np.pad(np.ascontiguousarray(audio, dtype=np.float32), (0, engine.sample_rate))
    result = engine.process(padded).sort_by_start_time()
    return [(float(r.start), float(r.end), int(r.speaker)) for r in result]


def align(asr_segments: list, diar_segments: list, default_speaker: int = 0) -> list:
    """
    把 ASR 段落按「最大时间重叠」归属到说话人。
    asr_segments: [(start, end, text)]
    返回: [(start, end, speaker, text)]
    """
    rows = []
    for seg in asr_segments:
        s, e, text = seg[0], seg[1], seg[2]
        best_spk, best_ov = default_speaker, 0.0
        for ds, de, spk in diar_segments:
            ov = min(e, de) - max(s, ds)
            if ov > best_ov:
                best_ov, best_spk = ov, spk
        rows.append((s, e, best_spk, text))
    return rows


def renumber_for_display(rows: list, diar_segments: list) -> tuple[list, list, dict]:
    """
    把说话人编号重排为「文稿中首次出现顺序」的连续编号（0,1,2…），避免出现 SPK3/SPK6 这种跳号。
    只保留真正出现在 ASR 文稿里的说话人（忽略只有声音、未识别出文字的片段）。
    返回 (新 rows, 新 diar_segments, 原编号→新编号 映射)
    """
    mapping: dict = {}
    for _s, _e, spk, _t in rows:
        if spk not in mapping:
            mapping[spk] = len(mapping)
    new_rows = [(s, e, mapping[spk], t) for s, e, spk, t in rows]
    new_diar = [(s, e, mapping[spk]) for s, e, spk in diar_segments if spk in mapping]
    return new_rows, new_diar, mapping


def _fmt_ts(seconds: float) -> str:
    t = int(max(0.0, seconds))
    return f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def speaker_label(spk: int, name_map: dict = None) -> str:
    """把说话人编号转成显示名：优先用 name_map 里的真实姓名，否则回退 SPK1/SPK2…"""
    if name_map:
        nm = name_map.get(spk) or name_map.get(str(spk))
        if nm and str(nm).strip():
            return str(nm).strip()
    return f"SPK{spk + 1}"


def format_labeled(rows: list, merge_same_speaker: bool = True, name_map: dict = None) -> str:
    """格式化为「[hh:mm:ss] 姓名：文本」（未命名则为 SPK编号），同一人连续发言自动合并为一行。"""
    lines = []
    prev_spk = None
    for s, e, spk, text in rows:
        text = (text or "").strip()
        if not text:
            continue
        if merge_same_speaker and spk == prev_spk and lines:
            lines[-1] += text
        else:
            lines.append(f"[{_fmt_ts(s)}] {speaker_label(spk, name_map)}：{text}")
            prev_spk = spk
    return "\n".join(lines)


def speaker_stats(rows: list, diar_segments: list = None) -> list:
    """统计每位说话人的发言时长占比与段落数，用于界面展示。返回按编号排序的列表。"""
    spans: dict = {}
    total = 0.0
    if diar_segments:
        for s, e, spk in diar_segments:
            d = max(0.0, e - s)
            spans[spk] = spans.get(spk, 0.0) + d
            total += d
    else:
        for s, e, spk, _t in rows:
            d = max(0.0, e - s)
            spans[spk] = spans.get(spk, 0.0) + d
            total += d
    seg_count: dict = {}
    for r in rows:
        seg_count[r[2]] = seg_count.get(r[2], 0) + 1
    return [
        {
            "id": spk,
            "label": f"SPK{spk + 1}",
            "seconds": round(spans[spk], 1),
            "ratio": round(spans[spk] / total, 4) if total > 0 else 0.0,
            "segments": seg_count.get(spk, 0),
        }
        for spk in sorted(spans.keys())
    ]


def speaker_count(rows: list) -> int:
    return len({r[2] for r in rows})
