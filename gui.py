# gui.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
import re
import shutil
import numpy as np
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTextEdit, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QGroupBox, QComboBox,
    QInputDialog, QTabWidget, QDateEdit, QSplitter, QProgressBar,
    QDialog, QDialogButtonBox, QCheckBox, QCompleter
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QLineF, QTimer
from PyQt6.QtGui import QFont, QPainter, QColor, QPen

from core.recorder import record_audio_gui, stop_gui_record, pause_gui_record, resume_gui_record
from core.transcribe import transcribe, transcribe_with_diarization
from core.meeting_ai import (
    summarize_and_extract, extract_search_tags, extract_standard_tasks,
    summarize_extract_all, infer_speaker_names
)
from core import diarize as diarize_mod
from service.exporter import export_docx, export_pdf, export_pptx, export_xmind
from service.mailer import send_todo_email
from db.db import (
    init_db, save_meeting, list_meetings, batch_insert_tasks,
    list_tasks, update_task_status, get_meeting_by_id,
    delete_meeting as db_delete_meeting,
    delete_task as db_delete_task
)
from utils.text_filter import is_valid_transcript

import config

# ===================== 全局样式：浅色简约风 =====================
GLOBAL_STYLE = """
/* ---------- 基础 ---------- */
QMainWindow { background-color: #f4f6fa; }
QLabel { font-size: 13px; color: #475569; background: transparent; }

/* ---------- 顶部品牌栏 ---------- */
QWidget#brand_bar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #4f46e5);
    border-radius: 12px;
}
QLabel#brand_title { color: #ffffff; font-size: 19px; font-weight: 700; }
QLabel#brand_sub { color: rgba(255,255,255,0.85); font-size: 12px; }

/* ---------- 卡片分组 ---------- */
QGroupBox {
    background: #ffffff;
    border: 1px solid #e6e9f0;
    border-radius: 12px;
    margin-top: 16px;
    padding: 18px 14px 14px 14px;
    font-size: 13px;
    font-weight: 600;
    color: #334155;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: 3px;
    padding: 0 6px;
    color: #334155;
}

/* ---------- 输入控件 ---------- */
QLineEdit, QComboBox, QDateEdit {
    background: #ffffff;
    border: 1px solid #dfe3ea;
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 13px;
    color: #1f2933;
    min-height: 20px;
    selection-background-color: #c7ddff;
    selection-color: #1f2933;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus { border: 1px solid #2563eb; }
QLineEdit:disabled, QComboBox:disabled { background: #f1f3f7; color: #9aa3b2; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #94a3b8;
    margin-right: 10px;
    margin-left: 4px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #dfe3ea;
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: #e8f0fe;
    selection-color: #1f2933;
}

QTextEdit {
    background: #ffffff;
    border: 1px solid #e6e9f0;
    border-radius: 10px;
    padding: 10px;
    font-size: 13px;
    color: #1f2933;
    selection-background-color: #c7ddff;
    selection-color: #1f2933;
}

/* ---------- 按钮（默认：白底描边 = 次要操作） ---------- */
QPushButton {
    background: #ffffff;
    color: #334155;
    border: 1px solid #dfe3ea;
    border-radius: 8px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 500;
}
QPushButton:hover { background: #f3f6fb; border-color: #c9d3e2; }
QPushButton:pressed { background: #e8eef8; }
QPushButton:disabled { background: #f1f3f7; color: #a8b0bd; border-color: #e6e9f0; }

/* 实心主色按钮 */
QPushButton#btn_record, QPushButton#btn_trans, QPushButton#btn_search,
QPushButton#btn_refresh_task, QPushButton#btn_apply_names {
    background: #2563eb; color: #ffffff; border: none;
}
QPushButton#btn_record:hover, QPushButton#btn_trans:hover, QPushButton#btn_search:hover,
QPushButton#btn_refresh_task:hover, QPushButton#btn_apply_names:hover { background: #1d4ed8; }
QPushButton#btn_record { background: #dc2626; }
QPushButton#btn_record:hover { background: #b91c1c; }

QPushButton#btn_stop { background: #475569; color: #ffffff; border: none; }
QPushButton#btn_stop:hover { background: #334155; }
QPushButton#btn_pause { background: #d97706; color: #ffffff; border: none; }
QPushButton#btn_pause:hover { background: #b45309; }
QPushButton#btn_ai, QPushButton#btn_save { background: #7c3aed; color: #ffffff; border: none; }
QPushButton#btn_ai:hover, QPushButton#btn_save:hover { background: #6d28d9; }
QPushButton#btn_clear_search { background: #eef1f7; color: #475569; border: none; }
QPushButton#btn_clear_search:hover { background: #e2e7f0; }

/* 导出类：白底 + 彩色文字（轻量不喧宾夺主） */
QPushButton#btn_docx { color: #1d4ed8; border-color: #c7d7f7; }
QPushButton#btn_docx:hover { background: #eff4ff; }
QPushButton#btn_pdf { color: #b91c1c; border-color: #f5c9c9; }
QPushButton#btn_pdf:hover { background: #fdf0f0; }
QPushButton#btn_pptx { color: #c2410c; border-color: #f7d5c0; }
QPushButton#btn_pptx:hover { background: #fdf4ee; }
QPushButton#btn_xmind { color: #6d28d9; border-color: #ddd0f7; }
QPushButton#btn_xmind:hover { background: #f5f0ff; }
QPushButton#btn_mail { color: #0f766e; border-color: #bfe5e1; }
QPushButton#btn_mail:hover { background: #eefaf8; }
QPushButton#btn_speakers { color: #334155; }

/* 任务状态按钮 */
QPushButton#btn_task_finish { color: #047857; border-color: #b7e4d0; }
QPushButton#btn_task_finish:hover { background: #eefaf3; }
QPushButton#btn_task_progress { color: #1d4ed8; border-color: #c7d7f7; }
QPushButton#btn_task_progress:hover { background: #eff4ff; }
QPushButton#btn_task_delay { color: #b45309; border-color: #f2d9bd; }
QPushButton#btn_task_delay:hover { background: #fdf6ee; }
QPushButton#btn_task_reset { color: #64748b; }
QPushButton#btn_task_reset:hover { background: #f3f6fb; }

/* ---------- 对话框按钮 ---------- */
QDialogButtonBox QPushButton, QMessageBox QPushButton, QInputDialog QPushButton {
    min-width: 76px;
    padding: 7px 16px;
    background: #ffffff;
    color: #334155;
    border: 1px solid #dfe3ea;
    border-radius: 8px;
}
QDialogButtonBox QPushButton:hover, QMessageBox QPushButton:hover,
QInputDialog QPushButton:hover { background: #f3f6fb; }
QPushButton#btn_apply_names { background: #2563eb; color: #ffffff; border: none; }
QPushButton#btn_apply_names:hover { background: #1d4ed8; }

/* ---------- 表格 ---------- */
QTableWidget {
    background: #ffffff;
    border: 1px solid #e6e9f0;
    border-radius: 10px;
    gridline-color: transparent;
    font-size: 13px;
    selection-background-color: #e8f0fe;
    selection-color: #1f2933;
    alternate-background-color: #fafbfd;
}
QTableWidget::item { padding: 8px 8px; border-bottom: 1px solid #f1f3f7; }
QTableWidget::item:alternate { background-color: #fafbfd; }
QTableWidget::item:selected { background-color: #e8f0fe; color: #1f2933; }
QHeaderView::section {
    background: #f7f9fc;
    color: #64748b;
    padding: 10px 8px;
    border: none;
    border-bottom: 1px solid #e6e9f0;
    font-weight: 600;
    font-size: 12px;
}
QHeaderView::section:highlighted { background: #f7f9fc; }
QTableCornerButton::section { background: #f7f9fc; border: none; }

/* ---------- Tab（现代胶囊导航） ---------- */
QTabWidget::pane { border: none; background: transparent; top: 6px; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: #e8ecf3;
    color: #5b6472;
    padding: 9px 20px;
    margin-right: 8px;
    border-radius: 9px;
    font-size: 13px;
    font-weight: 500;
}
QTabBar::tab:hover { background: #dde4ee; }
QTabBar::tab:selected { background: #2563eb; color: #ffffff; font-weight: 600; }

/* ---------- 进度条 / 复选框 ---------- */
QProgressBar {
    background: #eef1f7;
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    font-size: 11px;
    color: #475569;
}
QProgressBar::chunk {
    border-radius: 6px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #6366f1);
}
QCheckBox { font-size: 13px; color: #475569; spacing: 7px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #cbd5e1; border-radius: 4px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: #2563eb; }
QCheckBox::indicator:checked { background: #2563eb; border-color: #2563eb; }

/* ---------- 分割条 / 滚动条 ---------- */
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 10px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #d5dbe5; border-radius: 5px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: #b9c2d0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #d5dbe5; border-radius: 5px; min-width: 32px; }
QScrollBar::handle:horizontal:hover { background: #b9c2d0; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


class WaveformWidget(QWidget):
    """录音实时波形（浅色卡片内嵌）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = np.array([], dtype=np.float32)
        self.setMinimumHeight(64)
        self.setMaximumHeight(84)
        self.setStyleSheet("background-color: #f7f9fc; border: 1px solid #e9edf4; border-radius: 10px;")

    def update_data(self, new_data):
        self.data = np.append(self.data, new_data.flatten())
        if len(self.data) > 48000:
            self.data = self.data[-48000:]
        self.update()

    def clear(self):
        self.data = np.array([], dtype=np.float32)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(247, 249, 252))
        w, h = self.width(), self.height()
        mid_y = h / 2.0
        # 中线
        painter.setPen(QPen(QColor(226, 232, 240), 1))
        painter.drawLine(QLineF(0, mid_y, w, mid_y))

        if len(self.data) < 2:
            painter.setPen(QPen(QColor(148, 163, 184), 1))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "等待音频…")
            return

        points = self.data[::max(1, len(self.data) // 2000)]
        if len(points) < 2:
            return
        max_val = max(float(np.max(np.abs(points))), 1e-6)
        norm = points / max_val
        painter.setPen(QPen(QColor(37, 99, 235), 1.4))
        x_step = w / (len(norm) - 1)
        prev = None
        for i, val in enumerate(norm):
            x = i * x_step
            y = mid_y - val * (h / 2.0 - 6)
            if prev is not None:
                painter.drawLine(QLineF(prev[0], prev[1], x, y))
            prev = (x, y)


class RecordThread(QThread):
    finish_signal = pyqtSignal(str)
    exception_signal = pyqtSignal(str)
    data_signal = pyqtSignal(np.ndarray)
    file_name = ""

    def run(self):
        try:
            def callback(data):
                self.data_signal.emit(data)
            path = record_audio_gui(self.file_name, data_callback=callback)
            self.finish_signal.emit(path)
        except Exception as e:
            self.exception_signal.emit(str(e))


class TranscribeThread(QThread):
    """转写（可选带说话人分离 + 声纹库识别）"""
    finished_signal = pyqtSignal(object)   # dict：plain/labeled/rows/speakers/embeddings/diar_ok
    error_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)

    def __init__(self, audio_path, with_speakers=False):
        super().__init__()
        self.audio_path = audio_path
        self.with_speakers = with_speakers

    def run(self):
        try:
            def _progress_cb(done, total):
                self.progress_signal.emit(done, total)
            if self.with_speakers:
                res = transcribe_with_diarization(self.audio_path, progress_callback=_progress_cb)
            else:
                res = {
                    "plain": transcribe(self.audio_path, progress_callback=_progress_cb),
                    "labeled": "", "rows": [], "speakers": [], "embeddings": {}, "diar_ok": False,
                }
            self.finished_signal.emit(res)
        except Exception as e:
            self.error_signal.emit(str(e))


class NameInferThread(QThread):
    """后台调用大模型，从对话内容推断说话人真实姓名"""
    finished_signal = pyqtSignal(object)   # {speaker_id: 姓名}
    error_signal = pyqtSignal(str)

    def __init__(self, labeled_text, title, meet_type):
        super().__init__()
        self.labeled_text = labeled_text
        self.title = title
        self.meet_type = meet_type

    def run(self):
        try:
            self.finished_signal.emit(
                infer_speaker_names(self.labeled_text, self.title, self.meet_type)
            )
        except Exception as e:
            self.error_signal.emit(str(e))


class AiThread(QThread):
    """后台线程执行大模型分析，避免阻塞界面"""
    finished_signal = pyqtSignal(object)     # dict 结果
    error_signal = pyqtSignal(str)

    def __init__(self, text, title, meet_type):
        super().__init__()
        self.text = text
        self.title = title
        self.meet_type = meet_type

    def run(self):
        try:
            self.finished_signal.emit(summarize_extract_all(self.text, self.title, self.meet_type))
        except Exception as e:
            self.error_signal.emit(str(e))


class SpeakerDialog(QDialog):
    """
    发言人识别对话框：
    把声纹分离得到的 SPK1/SPK2… 映射成真实姓名。
    - 声纹库自动匹配到的姓名直接填入；
    - 大模型从对话线索推断的姓名也填入，但标注「请核对」；
    - 用户可任意修改；确认后替换全文并（可选）把声纹存进声纹库，下次自动识别。
    """

    def __init__(self, speakers, ai_names=None, ai_evidence=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("发言人识别")
        self.setMinimumWidth(720)
        self._speakers = speakers
        self._ai_names = ai_names or {}
        self._ai_evidence = ai_evidence or {}
        self._name_edits = {}
        self._source_items = {}
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        title = QLabel("已分辨出以下发言人")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#1f2933;")
        lay.addWidget(title)

        tip = QLabel(
            "姓名可直接修改。「识别依据」列显示声纹库相似度或 AI 的推断依据；留空则保留 SPK 编号。"
            "确认后同一人的声纹会被记住，下次自动识别。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#64748b; font-size:12px;")
        lay.addWidget(tip)

        table = QTableWidget(len(self._speakers), 4)
        table.setHorizontalHeaderLabels(["发言人", "姓名（可修改）", "识别依据", "发言占比"])
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setAlternatingRowColors(True)
        hh = table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 88)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(2, 210)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(3, 88)
        table.verticalHeader().setDefaultSectionSize(48)

        # 姓名输入框支持从「声纹库已有姓名」自动补全，避免手打错别字造成重复档案
        try:
            from core import speaker_store
            known_names = speaker_store.names()
        except Exception:
            known_names = []
        completer = QCompleter(known_names, self) if known_names else None
        if completer is not None:
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)

        for row, spk in enumerate(self._speakers):
            sid = spk["id"]
            table.setItem(row, 0, QTableWidgetItem(f"SPK{sid + 1}"))

            edit = QLineEdit()
            edit.setPlaceholderText("未识别，可输入或从已有姓名中选择")
            guess = spk.get("guess_name") or self._ai_names.get(sid) or ""
            edit.setText(guess)
            if completer is not None:
                edit.setCompleter(completer)
            edit.textEdited.connect(lambda _t, s=sid: self._mark_manual(s))
            table.setCellWidget(row, 1, edit)

            if spk.get("guess_name"):
                source_text = f"声纹库 {spk.get('guess_score', 0) * 100:.0f}%"
                source_tip = "声纹库中已登记该人的声音，可直接确认"
            elif self._ai_names.get(sid):
                ev = (self._ai_evidence or {}).get(sid, "")
                source_text = f"AI：{ev}" if ev else "AI 推断"
                source_tip = f"AI 依据：{ev}" if ev else "AI 根据对话线索推断，请核对后确认"
            else:
                source_text, source_tip = "—", "未能识别，可手动填写"
            src_item = QTableWidgetItem(source_text)
            src_item.setToolTip(source_tip)
            table.setItem(row, 2, src_item)
            table.setItem(row, 3, QTableWidgetItem(f"{spk.get('ratio', 0) * 100:.0f}%"))

            self._name_edits[sid] = edit
            self._source_items[sid] = src_item

        # 表格高度贴合内容，避免对话框出现大片空白
        table.setFixedHeight(48 + 48 * min(len(self._speakers), 8) + 6)
        lay.addWidget(table)

        self.remember_check = QCheckBox("记住这些人的声音（下次开会自动识别）")
        self.remember_check.setChecked(True)
        lay.addWidget(self.remember_check)

        btns = QDialogButtonBox()
        ok_btn = btns.addButton("应用", QDialogButtonBox.ButtonRole.AcceptRole)
        ok_btn.setObjectName("btn_apply_names")
        cancel_btn = btns.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        lay.addWidget(btns)

    def _mark_manual(self, sid):
        item = self._source_items.get(sid)
        if item is not None:
            item.setText("手动填写")

    def result_map(self) -> dict:
        """{speaker_id: 姓名}，未填写的编号不返回"""
        out = {}
        for sid, edit in self._name_edits.items():
            nm = edit.text().strip()
            if nm:
                out[sid] = nm
        return out

    def remember(self) -> bool:
        return self.remember_check.isChecked()


class SpeakerManagerDialog(QDialog):
    """声纹档案管理：查看已记住的说话人，可删除（删除后不再自动识别）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("发言人档案库")
        self.resize(520, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)

        title = QLabel("已记住的发言人")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#1f2933;")
        lay.addWidget(title)

        self.tip = QLabel("这些人的声纹已入库，下次会议将自动识别其姓名。")
        self.tip.setWordWrap(True)
        self.tip.setStyleSheet("color:#64748b; font-size:12px;")
        lay.addWidget(self.tip)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["姓名", "样本数", "更新时间", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 80)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 90)
        self.table.verticalHeader().setDefaultSectionSize(42)
        lay.addWidget(self.table)

        btns = QDialogButtonBox()
        close_btn = btns.addButton("关闭", QDialogButtonBox.ButtonRole.RejectRole)
        close_btn.clicked.connect(self.reject)
        lay.addWidget(btns)

        self.reload()

    def reload(self):
        from core import speaker_store
        profiles = speaker_store.list_profiles()
        self.table.setRowCount(len(profiles))
        for row, p in enumerate(profiles):
            self.table.setItem(row, 0, QTableWidgetItem(p["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(str(p.get("samples", 1))))
            self.table.setItem(row, 2, QTableWidgetItem(str(p.get("updated_at", ""))))
            btn = QPushButton("删除")
            btn.setStyleSheet(
                "color:#b91c1c; border:1px solid #f5c9c9; border-radius:6px;"
                "padding:4px 10px; font-size:12px; background:#fff;"
            )
            btn.clicked.connect(lambda _c, n=p["name"]: self._delete(n))
            self.table.setCellWidget(row, 3, btn)
        if not profiles:
            self.tip.setText("暂无档案。在「录音与AI纪要」里转写并命名发言人后，声纹会自动记住。")

    def _delete(self, name):
        reply = QMessageBox.question(
            self, "确认删除", f"删除「{name}」的声纹档案？\n删除后该人不再被自动识别（可重新命名再学习）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from core import speaker_store
            speaker_store.delete_profile(name)
            self.reload()


class MeetingGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("会议纪要助手 | 语音转写·发言人识别·AI纪要")
        self.setMinimumSize(1280, 820)
        self.resize(1460, 920)
        self.global_font = QFont("Microsoft YaHei", 10)
        QApplication.setFont(self.global_font)
        # 全局应用样式，保证所有弹窗风格一致
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(GLOBAL_STYLE)

        self.audio_path = ""
        self.trans_text = ""
        self.summary_data = None
        self.diar_result = None
        self.record_thread = None
        self.transcribe_thread = None
        self.name_thread = None
        self.ai_thread = None
        self.selected_task_id = None
        self.is_paused = False
        self._record_seconds = 0
        self._record_timer = QTimer(self)
        self._record_timer.setInterval(1000)
        self._record_timer.timeout.connect(self._tick_record)

        # 启动自检：配置缺失时给出可操作提示（不阻断界面打开）
        QTimer.singleShot(300, self._check_env_on_start)

    def _check_env_on_start(self):
        """
        启动时检查必要配置。缺 key 时弹窗提示并允许直接打开 .env 填写，
        而不是让程序在导入阶段直接崩溃（用户连界面都看不到，无从排查）。
        """
        ok, errs = config.check_config_valid()
        if ok:
            return

        critical = [e for e in errs if "OPENAI" in e or "大模型" in e]
        if not critical:
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("配置未完成")
        box.setText("大模型配置缺失，AI 纪要功能暂不可用。")
        box.setInformativeText(
            "请在 .env 文件中填写以下两项后重启程序：\n\n"
            "  OPENAI_API_KEY=你的密钥\n"
            "  OPENAI_BASE_URL=接口地址\n\n"
            f"配置文件位置：\n{config.BASE_DIR / '.env'}\n\n"
            "其他功能（录音、转写、导出）不受影响。"
        )
        open_btn = box.addButton("打开配置文件", QMessageBox.ButtonRole.ActionRole)
        box.addButton("稍后再说", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self._open_env_file()

    def _open_env_file(self):
        """用系统默认编辑器打开 .env；文件不存在则从模板创建"""
        env_path = config.BASE_DIR / ".env"
        if not env_path.exists():
            example = config.BASE_DIR / ".env.example"
            if example.exists():
                try:
                    shutil.copyfile(example, env_path)
                except Exception as e:
                    QMessageBox.warning(self, "无法创建配置", f"创建 .env 失败：{e}")
                    return
        try:
            os.startfile(str(env_path))  # Windows 下用默认程序打开
        except Exception:
            QMessageBox.information(
                self, "请手动打开",
                f"请用记事本打开以下文件并填写密钥：\n\n{env_path}"
            )

        init_db()
        self.setup_ui()
        self.load_history()
        self.load_all_tasks()

    # ===================== 界面搭建 =====================
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(18, 16, 18, 16)

        # ---- 品牌栏 ----
        brand = QWidget()
        brand.setObjectName("brand_bar")
        brand.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        brand.setFixedHeight(62)
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(22, 9, 22, 9)
        brand_layout.setSpacing(1)
        brand_title = QLabel("会议纪要助手")
        brand_title.setObjectName("brand_title")
        brand_sub = QLabel("录音 → 语音转写 → 发言人识别 → AI 纪要 → 一键导出 Word / PDF / PPT / 思维导图")
        brand_sub.setObjectName("brand_sub")
        brand_layout.addWidget(brand_title)
        brand_layout.addWidget(brand_sub)
        main_layout.addWidget(brand)

        self.tab_widget = QTabWidget()

        # ---------- Tab1 ----------
        tab1_widget = QWidget()
        tab1_layout = QVBoxLayout(tab1_widget)
        tab1_layout.setContentsMargins(0, 0, 0, 0)
        tab1_layout.setSpacing(10)

        top_group = QGroupBox("录音控制与实时波形")
        top_layout = QVBoxLayout(top_group)
        top_layout.setSpacing(8)
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(8)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("请输入会议名称")
        self.title_input.setMinimumWidth(240)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["日常例会", "项目评审", "客户沟通", "需求研讨", "其他"])

        self.record_btn = QPushButton("开始录音")
        self.record_btn.setObjectName("btn_record")
        self.record_btn.clicked.connect(self.start_record)
        self.stop_btn = QPushButton("停止录音")
        self.stop_btn.setObjectName("btn_stop")
        self.stop_btn.clicked.connect(self.end_record)
        self.stop_btn.setEnabled(False)
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setObjectName("btn_pause")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setEnabled(False)

        self.record_time_label = QLabel("")
        self.record_time_label.setStyleSheet("color:#dc2626; font-weight:600;")

        ctrl_layout.addWidget(QLabel("会议名称"))
        ctrl_layout.addWidget(self.title_input, stretch=2)
        ctrl_layout.addWidget(QLabel("类型"))
        ctrl_layout.addWidget(self.type_combo, stretch=1)
        ctrl_layout.addWidget(self.record_btn)
        ctrl_layout.addWidget(self.stop_btn)
        ctrl_layout.addWidget(self.pause_btn)
        ctrl_layout.addWidget(self.record_time_label)
        ctrl_layout.addStretch()
        top_layout.addLayout(ctrl_layout)

        self.waveform = WaveformWidget()
        top_layout.addWidget(self.waveform)
        tab1_layout.addWidget(top_group)

        # ---- 转写 / AI 双栏 ----
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_group = QGroupBox("语音转写原文")
        left_layout = QVBoxLayout(left_group)
        left_layout.setSpacing(8)
        self.trans_text_edit = QTextEdit()
        self.trans_text_edit.setMinimumHeight(160)
        btn_progress_layout = QHBoxLayout()
        btn_progress_layout.setSpacing(10)
        self.trans_btn = QPushButton("一键转写音频")
        self.trans_btn.setObjectName("btn_trans")
        self.trans_btn.clicked.connect(self.run_transcribe)
        self.trans_progress = QProgressBar()
        self.trans_progress.setRange(0, 100)
        self.trans_progress.setValue(0)
        self.trans_progress.setVisible(False)
        self.trans_progress.setFixedWidth(160)
        self.trans_status_label = QLabel("")
        self.trans_status_label.setVisible(False)
        self.trans_status_label.setStyleSheet("color:#64748b; font-size:12px;")
        self.diarize_check = QCheckBox("区分发言人")
        self.diarize_check.setToolTip("开启后做声纹分离，输出带 [时间] 发言人的文稿；说话人越多耗时略增")
        self.diarize_check.setChecked(True)
        self.ai_name_check = QCheckBox("AI 识别人名")
        self.ai_name_check.setToolTip("根据对话中的称呼、自我介绍等线索推断说话人姓名（请核对后确认）")
        self.ai_name_check.setChecked(True)
        self.speaker_count_combo = QComboBox()
        self.speaker_count_combo.addItems(["人数自动", "2 人", "3 人", "4 人", "5 人", "6 人"])
        self.speaker_count_combo.setToolTip("已知参会人数时手动指定，可显著提升说话人分离准确度")
        self.speaker_count_combo.setFixedWidth(98)
        self.speaker_btn = QPushButton("发言人档案")
        self.speaker_btn.setObjectName("btn_speakers")
        self.speaker_btn.setToolTip("查看/管理已记住的发言人声纹档案")
        self.speaker_btn.clicked.connect(self.open_speaker_manager)
        btn_progress_layout.addWidget(self.trans_btn)
        btn_progress_layout.addWidget(self.diarize_check)
        btn_progress_layout.addWidget(self.speaker_count_combo)
        btn_progress_layout.addWidget(self.ai_name_check)
        btn_progress_layout.addWidget(self.speaker_btn)
        btn_progress_layout.addWidget(self.trans_progress)
        btn_progress_layout.addWidget(self.trans_status_label)
        btn_progress_layout.addStretch()
        left_layout.addWidget(self.trans_text_edit)
        left_layout.addLayout(btn_progress_layout)
        splitter.addWidget(left_group)

        right_group = QGroupBox("AI 会议纪要 & 待办")
        right_layout = QVBoxLayout(right_group)
        right_layout.setSpacing(8)
        self.ai_text_edit = QTextEdit()
        self.ai_text_edit.setMinimumHeight(160)
        ai_btn = QPushButton("AI 生成总结")
        ai_btn.setObjectName("btn_ai")
        ai_btn.setMinimumWidth(150)
        ai_btn.clicked.connect(self.run_ai_summary)
        ai_bar = QHBoxLayout()
        ai_bar.addWidget(ai_btn)
        ai_bar.addStretch()
        right_layout.addWidget(self.ai_text_edit)
        right_layout.addLayout(ai_bar)
        splitter.addWidget(right_group)
        splitter.setSizes([520, 520])
        tab1_layout.addWidget(splitter, stretch=1)

        # ---- 功能按钮 ----
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        self.save_btn = QPushButton("保存记录")
        self.save_btn.setObjectName("btn_save")
        self.save_btn.clicked.connect(self.save_meeting_data)
        self.export_docx_btn = QPushButton("导出 Word")
        self.export_docx_btn.setObjectName("btn_docx")
        self.export_docx_btn.clicked.connect(self.export_word)
        self.export_pdf_btn = QPushButton("导出 PDF")
        self.export_pdf_btn.setObjectName("btn_pdf")
        self.export_pdf_btn.clicked.connect(self.export_pdf_file)
        self.export_pptx_btn = QPushButton("导出 PPT")
        self.export_pptx_btn.setObjectName("btn_pptx")
        self.export_pptx_btn.clicked.connect(self.export_pptx_file)
        self.export_xmind_btn = QPushButton("导出思维导图")
        self.export_xmind_btn.setObjectName("btn_xmind")
        self.export_xmind_btn.clicked.connect(self.export_xmind_file)
        self.mail_btn = QPushButton("邮件推送")
        self.mail_btn.setObjectName("btn_mail")
        self.mail_btn.clicked.connect(self.send_mail)
        for b in (self.save_btn, self.export_docx_btn, self.export_pdf_btn,
                  self.export_pptx_btn, self.export_xmind_btn, self.mail_btn):
            btn_layout.addWidget(b)
        btn_layout.addStretch()
        tab1_layout.addLayout(btn_layout)

        # ---- 历史会议表格 ----
        history_group = QGroupBox("全部历史会议")
        history_layout = QVBoxLayout(history_group)
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(["ID", "会议名称", "创建时间", "操作"])
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.history_table.setColumnWidth(0, 60)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.history_table.setColumnWidth(3, 170)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setMinimumHeight(180)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.verticalHeader().setDefaultSectionSize(42)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history_table.horizontalHeader().setHighlightSections(False)
        history_layout.addWidget(self.history_table)
        tab1_layout.addWidget(history_group, stretch=2)

        # ---------- Tab2：会议多维检索 ----------
        tab2_widget = QWidget()
        tab2_layout = QVBoxLayout(tab2_widget)
        tab2_layout.setContentsMargins(0, 0, 0, 0)
        tab2_layout.setSpacing(12)
        search_group = QGroupBox("检索条件")
        search_line_layout = QHBoxLayout(search_group)
        search_line_layout.setSpacing(8)
        self.search_keyword = QLineEdit()
        self.search_keyword.setPlaceholderText("全局关键词：标题 / 转写 / 关键词标签")
        self.search_type = QComboBox()
        self.search_type.addItems(["全部类型", "日常例会", "项目评审", "客户沟通", "需求研讨", "其他"])
        self.search_person = QLineEdit()
        self.search_person.setPlaceholderText("筛选责任人")
        self.search_start_date = QDateEdit()
        self.search_start_date.setDisplayFormat("yyyy-MM-dd")
        self.search_end_date = QDateEdit()
        self.search_end_date.setDisplayFormat("yyyy-MM-dd")
        btn_search = QPushButton("多维检索")
        btn_search.setObjectName("btn_search")
        btn_search.clicked.connect(self.run_multi_search)
        btn_clear_search = QPushButton("清空筛选")
        btn_clear_search.setObjectName("btn_clear_search")
        btn_clear_search.clicked.connect(self.clear_search)
        search_line_layout.addWidget(QLabel("关键词"))
        search_line_layout.addWidget(self.search_keyword, stretch=2)
        search_line_layout.addWidget(QLabel("类型"))
        search_line_layout.addWidget(self.search_type)
        search_line_layout.addWidget(QLabel("责任人"))
        search_line_layout.addWidget(self.search_person)
        search_line_layout.addWidget(QLabel("起始"))
        search_line_layout.addWidget(self.search_start_date)
        search_line_layout.addWidget(QLabel("结束"))
        search_line_layout.addWidget(self.search_end_date)
        search_line_layout.addWidget(btn_search)
        search_line_layout.addWidget(btn_clear_search)
        tab2_layout.addWidget(search_group)

        self.search_table = QTableWidget()
        self.search_table.setColumnCount(7)
        self.search_table.setHorizontalHeaderLabels([
            "会议ID", "标题", "类型", "检索关键词", "关联责任人", "创建时间", "操作"
        ])
        self.search_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.search_table.setColumnWidth(0, 60)
        self.search_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.search_table.setColumnWidth(6, 170)
        for i in range(1, 6):
            self.search_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.search_table.setAlternatingRowColors(True)
        self.search_table.verticalHeader().setVisible(False)
        self.search_table.verticalHeader().setDefaultSectionSize(42)
        self.search_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.search_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.search_table.horizontalHeader().setHighlightSections(False)
        tab2_layout.addWidget(self.search_table)

        # ---------- Tab3：待办任务跟踪 ----------
        tab3_widget = QWidget()
        tab3_layout = QVBoxLayout(tab3_widget)
        tab3_layout.setContentsMargins(0, 0, 0, 0)
        tab3_layout.setSpacing(12)
        task_filter_group = QGroupBox("筛选")
        task_filter_layout = QHBoxLayout(task_filter_group)
        task_filter_layout.setSpacing(8)
        self.task_meet_id_input = QLineEdit()
        self.task_meet_id_input.setPlaceholderText("指定会议ID（留空查全部）")
        self.task_owner_filter = QLineEdit()
        self.task_owner_filter.setPlaceholderText("筛选任务负责人")
        self.task_status_filter = QComboBox()
        self.task_status_filter.addItems(["全部状态", "待处理", "进行中", "已完成", "已延期"])
        refresh_task_btn = QPushButton("刷新任务列表")
        refresh_task_btn.setObjectName("btn_refresh_task")
        refresh_task_btn.clicked.connect(self.load_all_tasks)
        task_filter_layout.addWidget(QLabel("会议ID"))
        task_filter_layout.addWidget(self.task_meet_id_input)
        task_filter_layout.addWidget(QLabel("负责人"))
        task_filter_layout.addWidget(self.task_owner_filter)
        task_filter_layout.addWidget(QLabel("状态"))
        task_filter_layout.addWidget(self.task_status_filter)
        task_filter_layout.addWidget(refresh_task_btn)
        task_filter_layout.addStretch()
        tab3_layout.addWidget(task_filter_group)

        self.task_table = QTableWidget()
        self.task_table.setColumnCount(9)
        self.task_table.setHorizontalHeaderLabels([
            "任务ID", "会议ID", "任务内容", "负责人", "截止日期",
            "优先级", "当前状态", "完成时间", "操作"
        ])
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.task_table.setColumnWidth(0, 60)
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.task_table.setColumnWidth(1, 70)
        self.task_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self.task_table.setColumnWidth(8, 90)
        for i in range(2, 8):
            self.task_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.task_table.setAlternatingRowColors(True)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.verticalHeader().setDefaultSectionSize(42)
        self.task_table.cellClicked.connect(self.on_task_row_click)
        self.task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.task_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.task_table.horizontalHeader().setHighlightSections(False)
        tab3_layout.addWidget(self.task_table)

        task_op_layout = QHBoxLayout()
        task_op_layout.setSpacing(8)
        btn_finish = QPushButton("标记选中任务【已完成】")
        btn_finish.setObjectName("btn_task_finish")
        btn_finish.clicked.connect(self.mark_task_finish)
        btn_progress = QPushButton("设为进行中")
        btn_progress.setObjectName("btn_task_progress")
        btn_progress.clicked.connect(lambda: self.update_task_status("进行中"))
        btn_delay = QPushButton("标记已延期")
        btn_delay.setObjectName("btn_task_delay")
        btn_delay.clicked.connect(lambda: self.update_task_status("已延期"))
        btn_reset = QPushButton("重置为待处理")
        btn_reset.setObjectName("btn_task_reset")
        btn_reset.clicked.connect(lambda: self.update_task_status("待处理"))
        for b in (btn_finish, btn_progress, btn_delay, btn_reset):
            task_op_layout.addWidget(b)
        task_op_layout.addStretch()
        tab3_layout.addLayout(task_op_layout)

        self.tab_widget.addTab(tab1_widget, "录音与AI纪要")
        self.tab_widget.addTab(tab2_widget, "会议多维检索")
        self.tab_widget.addTab(tab3_widget, "待办任务跟踪")
        main_layout.addWidget(self.tab_widget)

    # ===================== 录音 =====================
    def start_record(self):
        title = self.title_input.text().strip()
        title = re.sub(r'[\/:*?"<>|]', "_", title)
        self.title_input.setText(title)
        if not title:
            QMessageBox.warning(self, "提示", "请填写会议名称！")
            return
        if self.record_thread and self.record_thread.isRunning():
            QMessageBox.information(self, "提示", "正在录音中，请先停止！")
            return
        self.trans_text_edit.clear()
        self.ai_text_edit.clear()
        self.waveform.clear()
        self.trans_text = ""
        self.summary_data = None
        self.diar_result = None
        self.audio_path = ""
        self.is_paused = False
        self.pause_btn.setText("暂停")
        self.pause_btn.setEnabled(True)
        self.record_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._record_seconds = 0
        self.record_time_label.setText("● 录音中  00:00")
        self._record_timer.start()
        self.record_thread = RecordThread()
        self.record_thread.file_name = f"{title}.wav"
        self.record_thread.finish_signal.connect(self.record_finish)
        self.record_thread.exception_signal.connect(self.record_error)
        self.record_thread.data_signal.connect(self.waveform.update_data)
        self.record_thread.start()

    def _tick_record(self):
        self._record_seconds += 1
        m, s = divmod(self._record_seconds, 60)
        h, m = divmod(m, 60)
        txt = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        self.record_time_label.setText(f"● 录音中  {txt}")

    def toggle_pause(self):
        if self.is_paused:
            resume_gui_record()
            self.is_paused = False
            self.pause_btn.setText("暂停")
            self._record_timer.start()
        else:
            pause_gui_record()
            self.is_paused = True
            self.pause_btn.setText("继续")
            self._record_timer.stop()

    def end_record(self):
        stop_gui_record()
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.record_btn.setEnabled(True)
        self._record_timer.stop()
        self.record_time_label.setText("")

    def record_finish(self, path):
        self.audio_path = path
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("暂停")
        self._record_timer.stop()
        self.record_time_label.setText("")
        QMessageBox.information(self, "录制完成", f"音频文件已保存至：{path}")

    def record_error(self, err_msg):
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self._record_timer.stop()
        self.record_time_label.setText("")
        QMessageBox.critical(self, "录音失败", f"录音出错：{err_msg}")

    # ===================== 转写 =====================
    def _selected_speaker_count(self):
        """把「人数」下拉转成数字：'人数自动' → None"""
        m = re.search(r"(\d+)", self.speaker_count_combo.currentText())
        return int(m.group(1)) if m else None

    def run_transcribe(self):
        if not self.audio_path or not os.path.exists(self.audio_path):
            QMessageBox.warning(self, "错误", "请先完成录音！")
            return
        if self.transcribe_thread and self.transcribe_thread.isRunning():
            QMessageBox.information(self, "提示", "正在转写中，请稍候…")
            return
        self.trans_text_edit.clear()
        self.trans_text = ""
        self.diar_result = None
        with_speakers = self.diarize_check.isChecked()
        if with_speakers and not diarize_mod.is_available():
            QMessageBox.information(self, "提示", "声纹分离组件/模型不可用，本次只做普通转写。")
            with_speakers = False
        if with_speakers:
            # 已知人数时手动指定，分离准确度明显更好
            diarize_mod.set_num_clusters(self._selected_speaker_count())
        self.trans_progress.setRange(0, 100)
        self.trans_progress.setValue(0)
        self.trans_progress.setVisible(True)
        self.trans_status_label.setText("转写中，请稍候…（首次加载模型较慢）")
        self.trans_status_label.setVisible(True)
        self.trans_btn.setEnabled(False)
        self.transcribe_thread = TranscribeThread(self.audio_path, with_speakers)
        self.transcribe_thread.finished_signal.connect(self.on_transcribe_finished)
        self.transcribe_thread.error_signal.connect(self.on_transcribe_error)
        self.transcribe_thread.progress_signal.connect(self.on_transcribe_progress)
        self.transcribe_thread.start()

    def on_transcribe_progress(self, done, total):
        if total <= 0:
            return
        percent = int(done * 100 / total)
        self.trans_progress.setValue(percent)
        self.trans_status_label.setText(f"转写中… {done}/{total} 片（{percent}%）")

    def on_transcribe_finished(self, res):
        self.trans_progress.setVisible(False)
        self.trans_btn.setEnabled(True)
        self.transcribe_thread = None

        plain = res.get("plain", "")
        valid, cleaned_or_msg = is_valid_transcript(plain)
        if not valid:
            self.trans_status_label.setVisible(False)
            self.trans_text_edit.clear()
            self.trans_text = ""
            QMessageBox.warning(self, "转写结果", f"音频无内容，未识别出任何有效文字。\n提示：{cleaned_or_msg}")
            return

        labeled = res.get("labeled", "")
        self.diar_result = res if res.get("diar_ok") else None
        # 有发言人文稿就用带发言人的，否则退回清洗后的纯文本
        self.trans_text = labeled if labeled else cleaned_or_msg
        self.trans_text_edit.setText(self.trans_text)

        if not labeled or not res.get("speakers"):
            self.trans_status_label.setVisible(False)
            tip = "语音已全部转为文字"
            if res.get("diar_ok"):
                tip += "（未检测到多个说话人）"
            QMessageBox.information(self, "转写完成", tip)
            return

        # 有分离结果：按需启动 AI 人名推断，然后弹「发言人识别」
        if self.ai_name_check.isChecked():
            self.trans_status_label.setText("正在根据对话内容识别人名…")
            self.trans_status_label.setVisible(True)
            self.name_thread = NameInferThread(
                labeled, self.title_input.text(), self.type_combo.currentText()
            )
            self.name_thread.finished_signal.connect(self.on_name_inferred)
            self.name_thread.error_signal.connect(lambda _e: self.on_name_inferred({}))
            self.name_thread.start()
        else:
            self.trans_status_label.setVisible(False)
            self.show_speaker_dialog({})

    def on_name_inferred(self, ai_names):
        self.trans_status_label.setVisible(False)
        self.name_thread = None
        self.show_speaker_dialog(ai_names or {})

    def show_speaker_dialog(self, ai_result):
        res = self.diar_result
        if not res or not res.get("speakers"):
            return
        ai_result = ai_result or {}
        ai_names = ai_result.get("names", {}) or {}
        ai_evidence = ai_result.get("evidence", {}) or {}
        dlg = SpeakerDialog(res["speakers"], ai_names, ai_evidence, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            QMessageBox.information(
                self, "转写完成",
                "已按发言人编号区分（SPK1/SPK2…）。可随时点「发言人档案」查看已记住的人。"
            )
            return

        name_map = dlg.result_map()
        if name_map:
            # 用真实姓名重新格式化全文
            from zhconv import convert
            labeled = diarize_mod.format_labeled(res["rows"], name_map=name_map)
            self.trans_text = convert(labeled, "zh-cn")
            self.trans_text_edit.setText(self.trans_text)

        saved = []
        if dlg.remember() and name_map:
            try:
                from core import speaker_store
                for spk_id, nm in name_map.items():
                    emb = res["embeddings"].get(spk_id)
                    if emb is not None and speaker_store.enroll(nm, emb):
                        saved.append(nm)
            except Exception as e:
                QMessageBox.warning(self, "声纹保存失败", f"未记住发言人声音：{e}")

        msg = "已按姓名标注发言人" if name_map else "未命名，保留发言人编号"
        if saved:
            msg += f"\n已记住 {len(saved)} 人的声音，下次自动识别：{'、'.join(saved)}"
        QMessageBox.information(self, "发言人识别完成", msg)

    def on_transcribe_error(self, err_msg):
        self.trans_progress.setVisible(False)
        self.trans_status_label.setVisible(False)
        self.trans_btn.setEnabled(True)
        self.transcribe_thread = None
        QMessageBox.critical(self, "转写失败", f"错误：{err_msg}")

    def open_speaker_manager(self):
        SpeakerManagerDialog(self).exec()

    # ===================== AI 分析 =====================
    def run_ai_summary(self):
        self.trans_text = self.trans_text_edit.toPlainText()
        if not self.trans_text.strip():
            QMessageBox.warning(self, "错误", "暂无有效转写文本，请先执行转写并确保内容有效！")
            return
        if self.ai_thread and self.ai_thread.isRunning():
            QMessageBox.information(self, "提示", "AI 正在分析中，请稍候…")
            return
        title = self.title_input.text()
        m_type = self.type_combo.currentText()
        # 后台线程执行，摘要 / 待办 / 检索标签并行生成，避免界面卡死
        self.ai_text_edit.setPlainText("AI 分析中，请稍候…")
        self.ai_thread = AiThread(self.trans_text, title, m_type)
        self.ai_thread.finished_signal.connect(self.on_ai_finished)
        self.ai_thread.error_signal.connect(self.on_ai_error)
        self.ai_thread.start()

    def on_ai_finished(self, res):
        self.summary_data = res
        show_text = f"【会议纪要】\n{res['summary']}\n\n【待办事项】\n{res['todos']}"
        self.ai_text_edit.setText(show_text)
        QMessageBox.information(self, "AI分析完成", "已生成会议纪要与原始待办清单")

    def on_ai_error(self, err_msg):
        self.ai_text_edit.clear()
        QMessageBox.critical(self, "AI分析失败", f"调用大模型失败：{err_msg}")

    # ===================== 保存 / 导出 / 邮件 =====================
    def _sync_edited_summary(self):
        """
        保存/导出前，把用户在「AI 会议纪要」编辑框里手动修改过的内容同步回 summary_data。
        否则「人工修改总结」只是界面上的假象——保存/导出的仍是 AI 原始结果。
        """
        if not self.summary_data:
            return
        text = self.ai_text_edit.toPlainText().strip()
        if not text:
            return
        if "【待办事项】" in text:
            head, _, todos = text.partition("【待办事项】")
            self.summary_data["summary"] = head.replace("【会议纪要】", "").strip()
            self.summary_data["todos"] = todos.strip()
        else:
            # 用户删掉了分区标记，则整段视为纪要
            self.summary_data["summary"] = text.replace("【会议纪要】", "").strip()

    def save_meeting_data(self):
        if not self.summary_data:
            QMessageBox.warning(self, "提示", "请先生成AI纪要！")
            return
        self._sync_edited_summary()
        title = self.title_input.text().strip()
        meet_type = self.type_combo.currentText()
        full_transcript = self.trans_text_edit.toPlainText()
        # AI 分析结果优先复用，缺失时再补算
        keyword_tags = self.summary_data.get("keyword_tags")
        todo_person = self.summary_data.get("todo_person")
        if keyword_tags is None or todo_person is None:
            tag_info = extract_search_tags(self.summary_data["summary"], self.summary_data["todos"])
            keyword_tags = tag_info["keyword_tags"]
            todo_person = tag_info["todo_person"]
        task_list = self.summary_data.get("task_list")
        if task_list is None:
            task_list = extract_standard_tasks(full_transcript)
        meet_id = save_meeting(
            title=title, meeting_type=meet_type, audio_path=self.audio_path,
            transcript=full_transcript, summary=self.summary_data["summary"],
            todos=self.summary_data["todos"], todo_person=todo_person, keyword_tags=keyword_tags
        )
        batch_insert_tasks(meet_id, task_list)
        self.load_history()
        self.load_all_tasks()
        QMessageBox.information(
            self, "保存成功",
            f"会议ID：{meet_id} 已存入数据库\nAI自动提取 {len(task_list)} 条标准化待办任务\n切换【待办任务跟踪】面板查看/打勾完成"
        )

    def export_word(self):
        if not self.summary_data:
            QMessageBox.warning(self, "提示", "请先生成AI纪要！")
            return
        self._sync_edited_summary()
        path = export_docx(self.title_input.text(), self.trans_text, self.summary_data["summary"], self.summary_data["todos"])
        QMessageBox.information(self, "导出完成", f"Word文档已生成：{path}")

    def export_pdf_file(self):
        if not self.summary_data:
            QMessageBox.warning(self, "提示", "请先生成AI纪要！")
            return
        self._sync_edited_summary()
        path = export_pdf(self.title_input.text(), self.summary_data["summary"], self.summary_data["todos"])
        QMessageBox.information(self, "导出完成", f"PDF文档已生成：{path}")

    def export_pptx_file(self):
        if not self.summary_data:
            QMessageBox.warning(self, "提示", "请先生成AI纪要！")
            return
        self._sync_edited_summary()
        path = export_pptx(self.title_input.text(), self.summary_data["summary"], self.summary_data["todos"], self.trans_text)
        QMessageBox.information(self, "导出完成", f"PPT已生成：{path}")

    def export_xmind_file(self):
        if not self.summary_data:
            QMessageBox.warning(self, "提示", "请先生成AI纪要！")
            return
        self._sync_edited_summary()
        path = export_xmind(self.title_input.text(), self.summary_data["summary"], self.summary_data["todos"])
        QMessageBox.information(self, "导出完成", f"思维导图已生成：{path}")

    def send_mail(self):
        if not self.summary_data:
            QMessageBox.warning(self, "提示", "请先生成AI纪要！")
            return
        self._sync_edited_summary()
        email, ok = QInputDialog.getText(self, "发送待办邮件", "请输入收件人邮箱：")
        if ok and email.strip():
            send_todo_email(email, self.title_input.text(), self.summary_data["todos"])
            QMessageBox.information(self, "发送成功", "待办事项邮件已发送")

    # ---------- 操作按钮 ----------
    def create_action_buttons(self, detail_data, delete_id, include_detail=True):
        """返回包含操作按钮的QWidget"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        btn_style = (
            "background:#f3f6fb; color:#334155; border:1px solid #dfe3ea; border-radius:6px;"
            "font-size:12px; padding:3px 10px;"
        )

        if include_detail:
            btn_detail = QPushButton("详情")
            btn_detail.setStyleSheet(btn_style)
            btn_detail.clicked.connect(lambda: self.show_detail(detail_data))
            layout.addWidget(btn_detail)

        btn_delete = QPushButton("删除")
        btn_delete.setStyleSheet(
            "background:#fff; color:#b91c1c; border:1px solid #f5c9c9; border-radius:6px;"
            "font-size:12px; padding:3px 10px;"
        )
        btn_delete.clicked.connect(lambda: self.delete_meeting(delete_id))
        layout.addWidget(btn_delete)

        return widget

    def create_delete_button(self, task_id):
        """仅删除按钮（用于任务表）"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        btn_delete = QPushButton("删除")
        btn_delete.setStyleSheet(
            "background:#fff; color:#b91c1c; border:1px solid #f5c9c9; border-radius:6px;"
            "font-size:12px; padding:3px 10px;"
        )
        btn_delete.clicked.connect(lambda: self.delete_task(task_id))
        layout.addWidget(btn_delete)
        return widget

    # ---------- 历史表格 ----------
    def load_history(self):
        data_list, _ = list_meetings(page=1, page_size=9999)
        self.history_table.setRowCount(len(data_list))
        for row, item in enumerate(data_list):
            self.history_table.setItem(row, 0, QTableWidgetItem(str(item["id"])))
            self.history_table.setItem(row, 1, QTableWidgetItem(item["title"]))
            self.history_table.setItem(row, 2, QTableWidgetItem(item["created_at"]))
            widget = self.create_action_buttons(item, item["id"], include_detail=True)
            self.history_table.setCellWidget(row, 3, widget)

    def delete_meeting(self, meet_id):
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除会议ID {meet_id} 及其所有关联任务吗？\n此操作不可撤销！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                db_delete_meeting(meet_id)
                QMessageBox.information(self, "删除成功", f"会议 {meet_id} 已删除")
                self.load_history()
                self.load_all_tasks()
                self.run_multi_search()
            except Exception as e:
                QMessageBox.critical(self, "删除失败", str(e))

    def show_detail(self, data):
        meeting_id = data.get('id')
        if not meeting_id:
            QMessageBox.warning(self, "错误", "无效的会议ID")
            return
        full_data = get_meeting_by_id(meeting_id)
        if not full_data:
            QMessageBox.warning(self, "错误", "未找到会议记录")
            return
        detail = f"""会议ID：{full_data['id']}
会议名称：{full_data['title']}
会议类型：{full_data.get('meeting_type', '')}
录音路径：{full_data.get('audio_path', '')}
创建时间：{full_data.get('created_at', '')}
自动提取检索关键词：{full_data.get('keyword_tags', '')}
关联责任人：{full_data.get('todo_person', '')}

【原始转写文本】
{full_data.get('transcript', '（无）')}

【AI会议纪要】
{full_data.get('summary', '（无）')}

【原始待办文本】
{full_data.get('todos', '（无）')}"""
        dialog = QDialog(self)
        dialog.setWindowTitle("历史会议完整详情")
        dialog.resize(760, 640)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 14)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(detail)
        layout.addWidget(text_edit)
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btn_box.accepted.connect(dialog.accept)
        layout.addWidget(btn_box)
        dialog.exec()

    # ---------- 多维检索 ----------
    def run_multi_search(self):
        keyword = self.search_keyword.text().strip()
        meet_type = self.search_type.currentText()
        meet_type = "" if meet_type == "全部类型" else meet_type
        person = self.search_person.text().strip()
        s_date = self.search_start_date.date().toString("yyyy-MM-dd")
        e_date = self.search_end_date.date().toString("yyyy-MM-dd")
        data_list, total = list_meetings(
            page=1, page_size=9999, keyword=keyword,
            meeting_type=meet_type, person=person,
            start_date=s_date, end_date=e_date
        )
        self.search_table.setRowCount(len(data_list))
        for row, m in enumerate(data_list):
            self.search_table.setItem(row, 0, QTableWidgetItem(str(m["id"])))
            self.search_table.setItem(row, 1, QTableWidgetItem(m["title"]))
            self.search_table.setItem(row, 2, QTableWidgetItem(m["meeting_type"]))
            self.search_table.setItem(row, 3, QTableWidgetItem(m["keyword_tags"]))
            self.search_table.setItem(row, 4, QTableWidgetItem(m["todo_person"]))
            self.search_table.setItem(row, 5, QTableWidgetItem(m["created_at"]))
            widget = self.create_action_buttons(m, m["id"], include_detail=True)
            self.search_table.setCellWidget(row, 6, widget)

    def clear_search(self):
        self.search_keyword.clear()
        self.search_type.setCurrentText("全部类型")
        self.search_person.clear()
        self.search_table.setRowCount(0)

    # ---------- 待办任务 ----------
    def load_all_tasks(self):
        meet_id_str = self.task_meet_id_input.text().strip()
        owner = self.task_owner_filter.text().strip()
        status = self.task_status_filter.currentText()
        status = "" if status == "全部状态" else status
        task_data, _ = list_tasks(page=1, page_size=9999, owner=owner, status=status)
        if meet_id_str.isdigit():
            filter_mid = int(meet_id_str)
            task_data = [t for t in task_data if t["meet_id"] == filter_mid]
        self.task_table.setRowCount(len(task_data))
        for row, t in enumerate(task_data):
            self.task_table.setItem(row, 0, QTableWidgetItem(str(t["task_id"])))
            self.task_table.setItem(row, 1, QTableWidgetItem(str(t["meet_id"])))
            self.task_table.setItem(row, 2, QTableWidgetItem(t["task_content"]))
            self.task_table.setItem(row, 3, QTableWidgetItem(t["owner"]))
            self.task_table.setItem(row, 4, QTableWidgetItem(t["deadline"]))
            self.task_table.setItem(row, 5, QTableWidgetItem(t["priority"]))
            self.task_table.setItem(row, 6, QTableWidgetItem(t["status"]))
            self.task_table.setItem(row, 7, QTableWidgetItem(t["finish_at"] if t["finish_at"] else ""))
            widget = self.create_delete_button(t["task_id"])
            self.task_table.setCellWidget(row, 8, widget)

    def delete_task(self, task_id):
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除任务ID {task_id} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                db_delete_task(task_id)
                QMessageBox.information(self, "删除成功", f"任务 {task_id} 已删除")
                self.load_all_tasks()
            except Exception as e:
                QMessageBox.critical(self, "删除失败", str(e))

    def on_task_row_click(self, row, col):
        task_id_text = self.task_table.item(row, 0).text()
        self.selected_task_id = int(task_id_text)

    def mark_task_finish(self):
        if not self.selected_task_id:
            QMessageBox.warning(self, "操作提示", "请先在任务表格点击选中一行任务！")
            return
        finish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_task_status(self.selected_task_id, status="已完成", finish_at=finish_time)
        QMessageBox.information(self, "操作成功", f"任务{self.selected_task_id}已标记完成，自动记录完成时间")
        self.load_all_tasks()
        self.selected_task_id = None

    def update_task_status(self, target_status):
        if not self.selected_task_id:
            QMessageBox.warning(self, "操作提示", "请先在任务表格点击选中一行任务！")
            return
        finish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if target_status == "已完成" else ""
        update_task_status(self.selected_task_id, status=target_status, finish_at=finish_time)
        QMessageBox.information(self, "状态更新成功", f"任务状态已切换为：{target_status}")
        self.load_all_tasks()
        self.selected_task_id = None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MeetingGUI()
    window.show()
    sys.exit(app.exec())
