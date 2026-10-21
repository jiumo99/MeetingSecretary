import sounddevice as sd
import scipy.io.wavfile as wav
import numpy as np
import time
import os
import threading
from config import RECORDS_DIR

RECORD_LOCK = threading.Lock()
is_recording = False
is_paused = False
stream = None
record_data = []

def safe_clear_recorder():
    global is_recording, is_paused, stream, record_data
    with RECORD_LOCK:
        is_recording = False
        is_paused = False
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            stream = None
        record_data.clear()

def record_audio_gui(filename: str, data_callback=None) -> str:
    global is_recording, is_paused, stream, record_data
    safe_clear_recorder()
    os.makedirs(RECORDS_DIR, exist_ok=True)
    save_path = os.path.join(RECORDS_DIR, filename)
    fs = 16000
    record_data.clear()

    is_recording = True
    is_paused = False
    has_data = False

    # ---- 自动增益控制参数 ----
    TARGET_RMS = 0.2          # 目标 RMS（归一化后）
    NOISE_FLOOR = 0.005       # 噪声门限
    MAX_GAIN = 3.0            # 最大增益倍数

    # 用于平滑增益的 RMS 跟踪（简单指数平均）
    smooth_rms = 0.01

    def callback(indata, frames, time_info, status):
        nonlocal has_data, smooth_rms
        if status:
            print(f"录音警告: {status}")
        with RECORD_LOCK:
            if is_recording and not is_paused:
                audio = indata.copy()
                # 计算 RMS
                rms = np.sqrt(np.mean(audio ** 2))
                # 平滑
                smooth_rms = 0.9 * smooth_rms + 0.1 * rms
                # 噪声门：如果平滑 RMS 低于噪声门限，视为静音，直接衰减
                if smooth_rms < NOISE_FLOOR:
                    audio = audio * 0.1
                else:
                    # 计算增益：目标 RMS / 当前 RMS，但限制最大增益
                    gain = TARGET_RMS / (smooth_rms + 1e-6)
                    gain = np.clip(gain, 0.5, MAX_GAIN)
                    audio = audio * gain
                    # 防止削波（但 float32 很少削波，保留）
                    np.clip(audio, -1.0, 1.0, out=audio)

                record_data.append(audio)
                has_data = True
                if data_callback is not None:
                    data_callback(audio)

    try:
        stream = sd.InputStream(
            samplerate=fs,
            channels=1,
            dtype="float32",
            callback=callback
        )
        stream.start()
        time.sleep(0.2)
    except Exception as e:
        safe_clear_recorder()
        raise RuntimeError(f"麦克风初始化失败: {str(e)}")

    while True:
        time.sleep(0.1)
        with RECORD_LOCK:
            if not is_recording:
                break

    try:
        stream.stop()
        stream.close()
    except:
        pass
    stream = None
    is_recording = False
    is_paused = False

    if not has_data or len(record_data) == 0:
        raise RuntimeError("未采集到任何音频数据，请检查麦克风")

    audio_np = np.concatenate(record_data, axis=0)
    # 最终归一化（保险）
    max_amp = np.max(np.abs(audio_np))
    if max_amp > 0:
        audio_np = audio_np / max_amp * 0.95
    audio_int16 = (audio_np * 32767).astype(np.int16)
    wav.write(save_path, fs, audio_int16)

    if not os.path.exists(save_path) or os.path.getsize(save_path) < 1024:
        raise RuntimeError("音频文件保存失败，生成文件为空")
    return save_path

# ---- 其他函数（stop, pause, resume, record_audio）保持不变 ----
def stop_gui_record():
    global is_recording
    with RECORD_LOCK:
        is_recording = False

def pause_gui_record():
    global is_paused
    with RECORD_LOCK:
        if is_recording:
            is_paused = True

def resume_gui_record():
    global is_paused
    with RECORD_LOCK:
        if is_recording and is_paused:
            is_paused = False

def record_audio(filename=None, duration=None):
    safe_clear_recorder()
    os.makedirs(RECORDS_DIR, exist_ok=True)
    if not filename:
        filename = f"meeting_{int(time.time())}.wav"
    path = os.path.join(RECORDS_DIR, filename)
    fs = 16000
    recording = []

    def callback(indata, frames, time_info, status):
        recording.append(indata.copy())

    try:
        with sd.InputStream(samplerate=fs, channels=1, callback=callback):
            if duration:
                sd.sleep(int(duration * 1000))
            else:
                input("按回车结束录音\n")
    except Exception as e:
        raise RuntimeError(f"录音失败: {e}")

    data = np.concatenate(recording, axis=0)
    max_amp = np.max(np.abs(data))
    if max_amp > 0:
        data = data / max_amp * 0.95
    wav.write(path, fs, (data * 32767).astype(np.int16))
    return path