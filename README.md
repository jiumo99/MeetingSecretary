# 会议纪要助手 MeetingSecretary

录制会议 → 语音转写 → AI 生成纪要与待办 → 导出 Word / PDF / PPT / XMind → 邮件推送。

**本地运行，数据不出本机**。语音识别与说话人分离全部离线完成，只有生成纪要时才调用大模型接口。

---

## 功能概览

| 模块 | 说明 |
| --- | --- |
| 录音 | 一键录制会议音频，支持暂停 / 继续 |
| 语音转写 | 基于 faster-whisper，CPU 上即可运行，中文识别效果好 |
| 说话人分离 | 自动区分「谁在说话」（sherpa-onnx 声纹聚类，全离线） |
| 说话人姓名 | 可手动为发言人命名，声音会存入声纹库，下次自动认出 |
| AI 纪要 | 大模型自动提炼会议摘要、关键结论、待办任务与负责人 |
| 待办管理 | 任务清单落库、状态流转、完成时间记录 |
| 多格式导出 | Word / PDF / PPT / XMind 思维导图 |
| 邮件推送 | 把待办任务直接发到指定邮箱 |
| 历史记录 | 会议与任务持久化存储，可搜索、可回溯 |

---

## 快速开始

### 方式一：下载可执行程序（推荐，无需装 Python）

1. 到本仓库的 **Releases** 页面下载 `MeetingSecretary.zip`
2. 解压到任意目录（**不要放在中文路径下**，避免个别库的兼容问题）
3. 双击 `MeetingSecretary.exe`
4. 首次运行会自动下载语音识别模型（约 1.5GB，视网速需要几分钟），界面会显示进度
5. 第一次使用需在程序目录下的 `.env` 文件里填写大模型 API Key

> 模型下载到 `exe` 同级的 `models/` 目录，下载一次后永久复用，再次打开秒启动。

### 方式二：从源码运行

```bash
git clone <本仓库地址>
cd MeetingSecretary

# 复制配置模板并填写密钥
copy .env.example .env

# 双击运行（Windows，自动创建虚拟环境 + 安装依赖）
启动.bat
```

也可以手动执行：

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python gui.py
```

---

## 配置说明

所有配置集中在项目根目录的 `.env` 文件中（从 `.env.example` 复制而来）。
**`.env` 已被 `.gitignore` 排除，不会也不应提交到仓库。**

最少必填一项：

```ini
OPENAI_API_KEY=sk-你的密钥
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-turbo
```

邮箱推送为选填，QQ 邮箱的 `MY_EMAIL_PASS` 需要填**授权码**而非登录密码。

### 模型大小怎么选

| 规格 | 体积 | 说明 |
| --- | --- | --- |
| `tiny` | 75MB | 最快，准确度一般，适合快速试用 |
| `base` | 145MB | 速度与准确度折中 |
| `small` | 480MB | 轻量场景够用 |
| `medium` | 1.5GB | **默认值**，中文会议场景效果与速度平衡最好 |
| `large-v3` | 3GB | 最准，但 CPU 上明显变慢 |

改 `.env` 里的 `WHISPER_MODEL_SIZE` 即可切换，程序会自动下载对应模型。

---

## 打包成可执行程序

```bash
build.bat
```

产物位于 **`dist/MeetingSecretary/`**，整个目录打包成压缩包即可分发。

> ⚠️ **务必使用 `dist/` 目录下的 exe，不要运行 `build/` 目录下的！**
> `build/` 是 PyInstaller 的**中间产物（施工脚手架）**，里面的 exe 缺少运行库，
> 直接双击会报 `Failed to load Python DLL ... 找不到指定的模块`。
> 只有 `dist/` 才是完整可独立运行的程序。

打包时**不会**把模型打进程序（否则体积会超过 1.5GB），程序首次运行会自动下载到本地。

---

## 项目结构

```
MeetingSecretary/
├── gui.py                    # 图形界面入口（主要使用）
├── main.py                   # 命令行流程入口
├── config.py                 # 配置加载与路径解析
├── core/
│   ├── recorder.py           # 录音
│   ├── transcribe.py         # 语音转写（faster-whisper）
│   ├── diarize.py            # 说话人分离（sherpa-onnx）
│   ├── speaker_store.py      # 声纹库（SQLite）
│   ├── meeting_ai.py         # 大模型：纪要生成、姓名推断
│   └── model_downloader.py   # 模型自动下载
├── db/db.py                  # 数据库操作
├── service/
│   ├── exporter.py           # Word / PDF / PPT / XMind 导出
│   ├── mailer.py             # 邮件发送
│   └── api.py                # 可选 FastAPI 接口
├── utils/                    # 日志、翻译、文本过滤等工具
├── static/                   # 提示词模板、停用词表
├── models/                   # 模型目录（不入库，运行时自动下载）
└── 启动.bat / build.bat      # 一键启动 / 一键打包
```

运行时产生的目录（均已加入 `.gitignore`）：

| 目录 | 内容 |
| --- | --- |
| `records/` | 录音文件与转写缓存 |
| `exports/` | 导出的文档 |
| `backups/` | 数据库自动备份（保留最近 20 份） |
| `logs/` | 运行日志 |
| `meetings.db` | 会议与任务数据库 |

---

## 技术栈

- **语音识别**：[faster-whisper](https://github.com/SYSTRAN/faster-whisper)（CTranslate2 后端，CPU 上比原版快数倍）
- **说话人分离**：[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)（pyannote 分段 + CamPP-Plus 中文声纹聚类，纯离线）
- **大模型**：任意 OpenAI 兼容接口（默认阿里云百炼 qwen）
- **界面**：PyQt6
- **存储**：SQLite
- **导出**：python-docx / reportlab / python-pptx / xmind

---

## 常见问题

**Q：首次启动卡在「正在下载模型」很久？**
A：模型约 1.5GB，取决于网速。已默认使用国内镜像 `hf-mirror.com` 加速。也可以先把 `WHISPER_MODEL_SIZE` 改成 `tiny` 试用。

**Q：不想装 Python，能直接用吗？**
A：可以，下载 Releases 里的压缩包，双击 exe 即可。

**Q：说话人分离没生效？**
A：若声纹模型下载失败，程序会自动降级为普通转写（不区分发言人），不影响主流程。可检查 `models/speaker-diarization/` 是否完整。

**Q：导出的文件在哪？**
A：默认在项目目录的 `exports/` 下。

**Q：模型可以手动放置吗？**
A：可以。把模型放到 `models/faster-whisper-<规格>/` 和 `models/speaker-diarization/` 下即可，程序会自动识别并跳过下载。

---

## 许可证

仅供学习与内部使用。
