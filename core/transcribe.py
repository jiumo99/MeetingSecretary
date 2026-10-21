import hashlib
import json
import os
import threading

import numpy as np
import scipy.io.wavfile as wav
from zhconv import convert

import config
from utils.logger import get_logger

logger = get_logger("transcribe")

# ===================== 模型常驻单例 =====================
# faster-whisper 模型加载开销大（尤其 medium），进程内只加载一次、反复复用，
# 避免每次点“转写”都重新冷启动模型。
_MODEL_CACHE: dict = {}
_MODEL_LOCK = threading.Lock()

_INITIAL_PROMPT = "以下是中文会议录音，内容涉及工作汇报、项目讨论、任务分配。"
# 缓存格式版本：变更缓存结构时需递增，避免读到旧格式
_CACHE_VERSION = "v2"


def _cuda_available() -> bool:
    """
    探测运行环境是否真有可用的 CUDA 设备。

    优先用 ctranslate2（faster-whisper 的实际推理后端，必然已安装），
    避免为了探测而把一个 500MB+ 的 torch 拖进打包产物。
    torch 仅在 ctranslate2 探测不可用时作为兜底。
    """
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        pass
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _resolve_device_and_type() -> tuple[str, str]:
    """确定实际使用的设备与计算精度，做安全降级"""
    device = config.WHISPER_DEVICE
    compute_type = config.WHISPER_COMPUTE_TYPE
    if device == "cuda":
        if not _cuda_available():
            logger.warning("CUDA 不可用，降级使用 CPU")
            device = "cpu"
    # CPU 不支持 float16，自动纠正
    if device == "cpu" and compute_type in ("float16", "fp16"):
        logger.warning(f"CPU 不支持 {compute_type}，已自动改为 int8")
        compute_type = "int8"
    return device, compute_type


def _resolve_model_path() -> str:
    """
    把模型名解析成本地目录：
    - 传的是已存在目录 → 直接用；
    - 项目 models/ 下已有完整模型 → 直接用（离线可用）；
    - 否则从 HuggingFace 镜像下载到 models/ 下（真实文件，避免 Windows 符号链接缓存问题）。
    """
    size_or_path = config.WHISPER_MODEL_SIZE
    if os.path.isdir(size_or_path):
        return size_or_path
    local_dir = config.MODELS_ROOT / f"faster-whisper-{size_or_path}"
    model_bin = local_dir / "model.bin"
    if model_bin.exists() and model_bin.stat().st_size > 0:
        return str(local_dir)
    # 本地缺失 → 直接从 HuggingFace 镜像下载（真实文件，避免 Windows 符号链接缓存问题）
    from huggingface_hub import snapshot_download
    repo_id = size_or_path if "/" in size_or_path else f"Systran/faster-whisper-{size_or_path}"
    logger.info(f"本地未找到模型，正在下载：{repo_id} → {local_dir}（首次较慢）")
    snapshot_download(repo_id=repo_id, local_dir=str(local_dir))
    logger.info("模型下载完成")
    return str(local_dir)


def get_model():
    """加载并缓存 faster-whisper 模型（线程安全，进程内仅加载一次）"""
    key = (config.WHISPER_MODEL_SIZE, config.WHISPER_DEVICE, config.WHISPER_COMPUTE_TYPE)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached
    with _MODEL_LOCK:
        cached = _MODEL_CACHE.get(key)
        if cached is not None:
            return cached
        from faster_whisper import WhisperModel
        device, compute_type = _resolve_device_and_type()
        model_path = _resolve_model_path()
        logger.info(
            f"加载 faster-whisper 模型：{model_path} "
            f"device={device} compute_type={compute_type}（首次加载较慢，之后常驻内存）"
        )
        model = WhisperModel(model_path, device=device, compute_type=compute_type)
        _MODEL_CACHE[key] = model
        logger.info("模型加载完成，已常驻内存")
        return model


def _read_audio(audio_path: str) -> tuple[int, np.ndarray]:
    """读取音频为 float32 单声道数组 [-1, 1]，并做基础校验"""
    fs, data = wav.read(audio_path)
    if data is None or len(data) == 0:
        raise RuntimeError("音频文件为空，无法转写")
    data = np.asarray(data)
    if data.ndim > 1:                                   # 多声道 → 单声道
        data = data.mean(axis=1)
    if data.dtype == np.int16:
        audio = data.astype(np.float32) / 32768.0
    elif data.dtype == np.uint8:                        # 8-bit PCM 为无符号，中点 128
        audio = (data.astype(np.float32) - 128.0) / 128.0
    elif data.dtype == np.int8:
        audio = data.astype(np.float32) / 128.0
    elif data.dtype == np.int32:
        audio = data.astype(np.float32) / 2147483648.0
    elif np.issubdtype(data.dtype, np.floating):
        audio = data.astype(np.float32)
        peak = float(np.max(np.abs(audio))) or 1.0
        if peak > 1.0:
            audio = audio / peak
    else:
        audio = data.astype(np.float32) / 32768.0
    return fs, audio


def _chunk_key(chunk: np.ndarray) -> str:
    """按 音频内容 + 关键参数 生成缓存键，参数变化则缓存自动失效"""
    h = hashlib.md5()
    h.update(chunk.tobytes())
    h.update(
        f"{config.WHISPER_MODEL_SIZE}|{config.WHISPER_LANGUAGE}|"
        f"{config.WHISPER_BEAM_SIZE}|{config.WHISPER_VAD}|{_CACHE_VERSION}".encode()
    )
    return h.hexdigest()[:20]


def _transcribe_chunk(model, chunk: np.ndarray, offset: float) -> list:
    """转写单个分片，返回 [(start, end, text), ...]（时间戳已加上分片偏移）"""
    kwargs = dict(
        language=config.WHISPER_LANGUAGE,
        task="transcribe",
        beam_size=config.WHISPER_BEAM_SIZE,
        temperature=0.0,                    # 确定性解码
        compression_ratio_threshold=2.0,    # 降低重复片段
        log_prob_threshold=-0.5,            # 只保留较高置信度
        no_speech_threshold=0.8,            # 更积极跳过非语音
        condition_on_previous_text=False,   # 分片独立，避免跨片重复循环
        initial_prompt=_INITIAL_PROMPT,     # 场景提示，提升中文准确率
        vad_filter=config.WHISPER_VAD,      # VAD 跳过静音段，显著加速
    )
    if config.WHISPER_VAD:
        kwargs["vad_parameters"] = dict(min_silence_duration_ms=config.WHISPER_VAD_MIN_SILENCE_MS)
    segments, _info = model.transcribe(chunk, **kwargs)
    return [(offset + float(s.start), offset + float(s.end), s.text) for s in segments]


def transcribe_segments(audio_path: str, progress_callback=None) -> tuple[list, int]:
    """
    转写并返回带时间戳的分段：([(start, end, text), ...], 缓存命中片数)
    - 模型常驻单例，避免重复冷启动；
    - 按 AUDIO_CHUNK_SECONDS 分片，每片结果（含时间戳）写入 TRANS_CACHE_DIR，命中即跳过推理；
    - progress_callback(done, total) 可用于驱动界面进度条。
    """
    fs, audio = _read_audio(audio_path)
    duration = len(audio) / fs
    if duration < 0.5:
        raise RuntimeError(f"音频时长仅 {duration:.2f} 秒，太短无法识别")
    max_amp = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if max_amp < 0.005:
        raise RuntimeError("音频信号幅度极低，请检查麦克风是否正常工作")
    if fs != 16000:
        logger.warning(f"采样率 {fs}，建议统一为 16kHz，可能影响准确率")

    model = get_model()

    chunk_samples = max(1, int(config.AUDIO_CHUNK_SECONDS * fs))
    total_chunks = int(np.ceil(len(audio) / chunk_samples))
    logger.info(f"转写开始：时长 {duration:.1f}s，分 {total_chunks} 片（每片 {config.AUDIO_CHUNK_SECONDS}s）")

    if progress_callback:
        try:
            progress_callback(0, total_chunks)
        except Exception:
            pass

    segments = []
    cache_hits = 0
    for idx in range(total_chunks):
        start = idx * chunk_samples
        chunk = audio[start:start + chunk_samples]
        if chunk.size == 0:
            continue

        key = _chunk_key(chunk)
        cache_file = config.TRANS_CACHE_DIR / f"{key}.json"
        if config.TRANSCRIBE_CACHE_ENABLED and cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                cache_hits += 1
                logger.info(f"第{idx + 1}/{total_chunks}片命中转写缓存")
            except Exception as e:
                logger.warning(f"缓存读取失败，改为重新转写：{e}")
                data = _transcribe_chunk(model, chunk, idx * chunk_samples / fs)
        else:
            data = _transcribe_chunk(model, chunk, idx * chunk_samples / fs)
            if config.TRANSCRIBE_CACHE_ENABLED:
                try:
                    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                except Exception as e:
                    logger.warning(f"写入转写缓存失败：{e}")
            logger.info(f"第{idx + 1}/{total_chunks}片转写完成，段数：{len(data)}")

        segments.extend((float(a), float(b), str(t)) for a, b, t in data)
        if progress_callback:
            try:
                progress_callback(idx + 1, total_chunks)
            except Exception:
                pass

    return segments, cache_hits


def transcribe(audio_path: str, progress_callback=None) -> str:
    """普通转写：返回纯文本（简体）。"""
    segments, cache_hits = transcribe_segments(audio_path, progress_callback)
    raw_text = "".join(t for _, _, t in segments).strip()
    if not raw_text:
        raise RuntimeError("Whisper 未识别出任何文字，请确认录音内容清晰或尝试不同模型")
    simplified = convert(raw_text, "zh-cn")
    logger.info(f"转写成功，文本长度：{len(simplified)}，缓存命中：{cache_hits} 片")
    return simplified


def transcribe_with_diarization(audio_path: str, progress_callback=None) -> dict:
    """
    转写 + 说话人分离 + 声纹库识别，一次性返回界面所需的全部信息。
    返回 dict：
      plain       纯文本（简体）
      labeled     带说话人编号的文稿（简体），形如「[00:00:03] SPK1：……」
      rows        原始对齐结果 [(start, end, speaker_id, text)]，供重新命名后重新格式化
      speakers    每位说话人的统计与识别建议（编号/时长占比/声纹库命中姓名与相似度）
      embeddings  {speaker_id: 声纹向量}
      cache_hits  命中转写缓存的片数
      diar_ok     是否成功完成说话人分离
    """
    segments, cache_hits = transcribe_segments(audio_path, progress_callback)
    plain_text = convert("".join(t for _, _, t in segments).strip(), "zh-cn")
    if not plain_text:
        raise RuntimeError("Whisper 未识别出任何文字，请确认录音内容清晰或尝试不同模型")

    result = {
        "plain": plain_text, "labeled": "", "rows": [],
        "speakers": [], "embeddings": {}, "cache_hits": cache_hits, "diar_ok": False,
    }

    if not config.SPEAKER_DIARIZATION_ENABLED:
        logger.info("SPEAKER_DIARIZATION_ENABLED=false，跳过声纹分离")
        return result

    from core import diarize as diarize_mod
    if not diarize_mod.is_available():
        logger.warning("声纹分离不可用，降级为普通转写")
        return result

    try:
        fs, audio = _read_audio(audio_path)
        diar_segments = diarize_mod.diarize(audio, fs)
        rows = diarize_mod.align(segments, diar_segments)
        # 重排为连续编号（避免 SPK3/SPK6 跳号），并丢弃没有文字的说话人
        rows, diar_segments, _mapping = diarize_mod.renumber_for_display(rows, diar_segments)
        result["rows"] = rows
        result["labeled"] = convert(diarize_mod.format_labeled(rows), "zh-cn")
        result["diar_ok"] = True

        stats = diarize_mod.speaker_stats(rows, diar_segments)
        embeddings = diarize_mod.speaker_embeddings(audio, fs, diar_segments)
        result["embeddings"] = embeddings

        store = None
        if config.SPEAKER_STORE_ENABLED:
            try:
                from core import speaker_store
                store = speaker_store
            except Exception as e:
                logger.warning(f"声纹库不可用，跳过自动识人：{e}")

        hit = 0
        for item in stats:
            spk = item["id"]
            item["guess_name"], item["guess_score"], item["guess_source"] = "", 0.0, ""
            emb = embeddings.get(spk)
            if store is not None and emb is not None:
                try:
                    nm, score = store.identify(emb)
                    item["guess_score"] = round(float(score), 4)
                    if nm:
                        item["guess_name"], item["guess_source"] = nm, "声纹库"
                        hit += 1
                except Exception as e:
                    logger.warning(f"声纹库识别失败（说话人{spk + 1}）：{e}")
        result["speakers"] = stats
        logger.info(
            f"声纹分离完成：{len(diar_segments)} 个语音片段，{len(stats)} 位说话人，"
            f"声纹库命中 {hit} 人，缓存命中 {cache_hits} 片"
        )
    except Exception as e:
        logger.error(f"声纹分离运行异常，降级为普通转写：{e}", exc_info=True)
        result["labeled"] = ""
        result["rows"] = []
        result["speakers"] = []
        result["embeddings"] = {}
        result["diar_ok"] = False
    return result


def transcribe_with_speakers(audio_path: str, progress_callback=None) -> tuple[str, str]:
    """
    兼容旧接口：返回 (labeled_text, plain_text)：
      labeled_text —— 「[hh:mm:ss] SPK1：……」带时间戳与发言人编号的文稿；
      plain_text   —— 普通纯文本（声纹不可用时用它兜底）。
    """
    res = transcribe_with_diarization(audio_path, progress_callback)
    return res["labeled"], res["plain"]


def to_simplified(text: str) -> str:
    return convert(text, "zh-cn")
