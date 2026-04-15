"""Activity — professional transfer progress panel with pause/resume."""

import logging
import os
import time
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QComboBox, QPushButton, QHeaderView,
    QProgressBar, QFrame, QScrollArea, QSplitter, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont

if TYPE_CHECKING:
    from ethos_drive.app import EthosDriveApp

log = logging.getLogger(__name__)

ACTION_ICONS = {
    "upload": "↑",
    "download": "↓",
    "delete_local": "🗑 Local",
    "delete_remote": "🗑 Remote",
    "conflict": "⚠",
}

_STYLE_HEADER = "font-weight: bold; font-size: 14px; color: #ccc;"
_STYLE_SUBTEXT = "color: #888; font-size: 12px;"
_STYLE_PANEL_BG = "QFrame { background: #1a1a2e; border-radius: 8px; }"
_STYLE_PROGRESS = """
QProgressBar {
    background: #2a2a3e; border: none; border-radius: 4px;
    height: 18px; text-align: center; color: #fff; font-size: 11px;
}
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
    stop:0 #2196F3, stop:1 #42A5F5); border-radius: 4px; }
"""
_STYLE_PROGRESS_UPLOAD = """
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
    stop:0 #4CAF50, stop:1 #66BB6A); border-radius: 4px; }
"""
_STYLE_BTN_PAUSE = (
    "QPushButton { background: #FF9800; color: white; border: none; padding: 8px 20px; "
    "border-radius: 4px; font-weight: bold; font-size: 13px; } "
    "QPushButton:hover { background: #F57C00; }"
)
_STYLE_BTN_RESUME = (
    "QPushButton { background: #4CAF50; color: white; border: none; padding: 8px 20px; "
    "border-radius: 4px; font-weight: bold; font-size: 13px; } "
    "QPushButton:hover { background: #388E3C; }"
)
_STYLE_BTN_CANCEL = (
    "QPushButton { background: transparent; color: #F44336; border: 1px solid #F44336; "
    "padding: 4px 12px; border-radius: 3px; font-size: 11px; } "
    "QPushButton:hover { background: #F44336; color: white; }"
)


def _format_size(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / (1024 * 1024 * 1024):.2f} GB"


def _format_speed(bps: int) -> str:
    if bps < 1024:
        return f"{bps} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.1f} MB/s"


def _format_eta(seconds: int) -> str:
    if seconds <= 0:
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m}m"


class _TransferItemWidget(QFrame):
    """Widget for a single active transfer — shows file name, progress bar, speed, ETA."""

    def __init__(self, path: str, direction: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.direction = direction
        self.setStyleSheet("QFrame { background: #222240; border-radius: 6px; margin: 2px 0; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Top row: icon + filename + speed + ETA
        top = QHBoxLayout()
        top.setSpacing(8)

        arrow = "↑" if direction == "upload" else "↓"
        arrow_color = "#4CAF50" if direction == "upload" else "#2196F3"
        self._icon_label = QLabel(arrow)
        self._icon_label.setStyleSheet(f"color: {arrow_color}; font-size: 16px; font-weight: bold;")
        self._icon_label.setFixedWidth(20)
        top.addWidget(self._icon_label)

        filename = os.path.basename(path) if "/" in path or "\\" in path else path
        self._name_label = QLabel(filename)
        self._name_label.setStyleSheet("color: #eee; font-size: 12px;")
        self._name_label.setToolTip(path)
        self._name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(self._name_label)

        self._speed_label = QLabel("—")
        self._speed_label.setStyleSheet("color: #90CAF9; font-size: 11px; min-width: 80px;")
        self._speed_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self._speed_label)

        self._eta_label = QLabel("—")
        self._eta_label.setStyleSheet("color: #888; font-size: 11px; min-width: 60px;")
        self._eta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self._eta_label)

        self._size_label = QLabel("")
        self._size_label.setStyleSheet("color: #888; font-size: 11px; min-width: 100px;")
        self._size_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self._size_label)

        layout.addLayout(top)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setValue(0)
        self._progress.setFormat("%p%")
        self._progress.setFixedHeight(18)
        base_style = _STYLE_PROGRESS
        if direction == "upload":
            base_style += _STYLE_PROGRESS_UPLOAD
        self._progress.setStyleSheet(base_style)
        layout.addWidget(self._progress)

    def update_progress(self, percent: float, speed_bps: int, eta_sec: int,
                        transferred: int = 0, total: int = 0):
        self._progress.setValue(int(percent * 10))
        self._progress.setFormat(f"{percent:.1f}%")
        self._speed_label.setText(_format_speed(speed_bps))
        self._eta_label.setText(_format_eta(eta_sec))
        if total > 0:
            self._size_label.setText(f"{_format_size(transferred)} / {_format_size(total)}")

    def mark_complete(self, success: bool):
        if success:
            self._progress.setValue(1000)
            self._progress.setFormat("✓ Done")
            self._speed_label.setText("")
            self._eta_label.setText("")
        else:
            self._progress.setFormat("✗ Failed")
            self._progress.setStyleSheet(
                _STYLE_PROGRESS + "QProgressBar::chunk { background: #F44336; border-radius: 4px; }")


class ActivityWidget(QWidget):
    """Professional transfer progress panel with pause/resume and detailed stats."""

    def __init__(self, app: "EthosDriveApp"):
        super().__init__()
        self.drive_app = app
        self._transfer_widgets: dict[str, _TransferItemWidget] = {}
        self._completed_count = 0
        self._total_queued = 0
        self._total_bytes_transferred = 0
        self._total_bytes_all = 0
        self._session_start = 0.0
        self._setup_ui()

        app.sync_progress.connect(self._on_progress)
        app.status_changed.connect(self._on_status_changed)

        # UI refresh timer for overall stats
        self._stats_timer = QTimer()
        self._stats_timer.timeout.connect(self._update_overall_stats)
        self._stats_timer.start(1000)

        # History refresh timer
        self._history_timer = QTimer()
        self._history_timer.timeout.connect(self._refresh_log)
        self._history_timer.start(5000)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── Overall progress panel ──
        overall_panel = QFrame()
        overall_panel.setStyleSheet(_STYLE_PANEL_BG)
        op_layout = QVBoxLayout(overall_panel)
        op_layout.setContentsMargins(16, 12, 16, 12)
        op_layout.setSpacing(6)

        # Title row with buttons
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_lbl = QLabel("Transfers")
        title_lbl.setStyleSheet("font-weight: bold; font-size: 16px; color: #fff;")
        title_row.addWidget(title_lbl)

        self._overall_status = QLabel("Idle")
        self._overall_status.setStyleSheet("color: #4CAF50; font-size: 13px; font-weight: bold;")
        title_row.addWidget(self._overall_status)
        title_row.addStretch()

        self._pause_btn = QPushButton("⏸  Pause")
        self._pause_btn.setStyleSheet(_STYLE_BTN_PAUSE)
        self._pause_btn.clicked.connect(self._toggle_pause)
        self._pause_btn.setFixedWidth(120)
        self._pause_btn.setVisible(False)
        title_row.addWidget(self._pause_btn)

        self._cancel_all_btn = QPushButton("Cancel All")
        self._cancel_all_btn.setStyleSheet(_STYLE_BTN_CANCEL)
        self._cancel_all_btn.clicked.connect(self._cancel_all)
        self._cancel_all_btn.setVisible(False)
        title_row.addWidget(self._cancel_all_btn)

        op_layout.addLayout(title_row)

        # Overall progress bar
        self._overall_progress = QProgressBar()
        self._overall_progress.setRange(0, 1000)
        self._overall_progress.setValue(0)
        self._overall_progress.setFormat("No active transfers")
        self._overall_progress.setFixedHeight(22)
        self._overall_progress.setStyleSheet(_STYLE_PROGRESS)
        op_layout.addWidget(self._overall_progress)

        # Stats row: files, size, speed, ETA
        stats_row = QHBoxLayout()
        stats_row.setSpacing(20)

        self._files_label = QLabel("Files: 0 / 0")
        self._files_label.setStyleSheet(_STYLE_SUBTEXT)
        stats_row.addWidget(self._files_label)

        self._size_label = QLabel("Size: 0 B / 0 B")
        self._size_label.setStyleSheet(_STYLE_SUBTEXT)
        stats_row.addWidget(self._size_label)

        self._speed_label = QLabel("Speed: —")
        self._speed_label.setStyleSheet("color: #90CAF9; font-size: 12px;")
        stats_row.addWidget(self._speed_label)

        self._eta_label = QLabel("ETA: —")
        self._eta_label.setStyleSheet("color: #FFB74D; font-size: 12px;")
        stats_row.addWidget(self._eta_label)

        stats_row.addStretch()
        op_layout.addLayout(stats_row)
        layout.addWidget(overall_panel)

        # ── Splitter: active transfers (top) / history (bottom) ──
        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet("QSplitter::handle { background: #333; height: 3px; }")

        # Active transfers scroll area
        transfers_container = QWidget()
        tc_layout = QVBoxLayout(transfers_container)
        tc_layout.setContentsMargins(0, 0, 0, 0)
        tc_layout.setSpacing(4)

        tf_header = QLabel("Active Transfers")
        tf_header.setStyleSheet(_STYLE_HEADER)
        tc_layout.addWidget(tf_header)

        self._transfers_scroll = QScrollArea()
        self._transfers_scroll.setWidgetResizable(True)
        self._transfers_scroll.setFrameShape(QFrame.NoFrame)
        self._transfers_scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self._transfers_list = QWidget()
        self._transfers_layout = QVBoxLayout(self._transfers_list)
        self._transfers_layout.setContentsMargins(0, 0, 0, 0)
        self._transfers_layout.setSpacing(2)
        self._transfers_layout.addStretch()

        self._no_transfers_label = QLabel("No active transfers")
        self._no_transfers_label.setStyleSheet("color: #666; font-size: 13px; padding: 20px;")
        self._no_transfers_label.setAlignment(Qt.AlignCenter)
        self._transfers_layout.insertWidget(0, self._no_transfers_label)

        self._transfers_scroll.setWidget(self._transfers_list)
        tc_layout.addWidget(self._transfers_scroll)
        splitter.addWidget(transfers_container)

        # History section
        history_container = QWidget()
        hc_layout = QVBoxLayout(history_container)
        hc_layout.setContentsMargins(0, 4, 0, 0)
        hc_layout.setSpacing(4)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        hl = QLabel("Sync History")
        hl.setStyleSheet(_STYLE_HEADER)
        filter_row.addWidget(hl)
        filter_row.addStretch()

        filter_row.addWidget(QLabel("Show:"))
        self._action_filter = QComboBox()
        self._action_filter.addItems(["All", "Uploads", "Downloads", "Deletes", "Errors"])
        self._action_filter.currentTextChanged.connect(self._refresh_log)
        self._action_filter.setFixedWidth(100)
        filter_row.addWidget(self._action_filter)

        self._task_filter = QComboBox()
        self._task_filter.addItem("All Tasks")
        for task in self.drive_app.config.sync_tasks:
            self._task_filter.addItem(task.name, task.id)
        self._task_filter.currentTextChanged.connect(self._refresh_log)
        self._task_filter.setFixedWidth(120)
        filter_row.addWidget(self._task_filter)

        hc_layout.addLayout(filter_row)

        self._history_table = QTableWidget(0, 5)
        self._history_table.setHorizontalHeaderLabels(["Time", "Action", "File", "Task", "Status"])
        header = self._history_table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._history_table.verticalHeader().hide()
        self._history_table.setAlternatingRowColors(True)
        self._history_table.setStyleSheet(
            "QTableWidget { background: #1e1e30; alternate-background-color: #24243a; "
            "gridline-color: #333; } "
            "QHeaderView::section { background: #1a1a2e; color: #aaa; border: none; "
            "padding: 6px; font-weight: bold; }")
        hc_layout.addWidget(self._history_table)
        splitter.addWidget(history_container)

        splitter.setSizes([300, 300])
        layout.addWidget(splitter)

    def _on_progress(self, data: dict):
        """Update per-file transfer widget and overall stats."""
        path = data.get("path", "")
        direction = data.get("direction", "")
        percent = data.get("percent", 0)
        speed = data.get("speed_bps", 0)
        eta = data.get("eta_seconds", 0)
        transferred = data.get("transferred", 0)
        total = data.get("total", 0)

        if path not in self._transfer_widgets:
            self._add_transfer_widget(path, direction)

        widget = self._transfer_widgets[path]
        widget.update_progress(percent, speed, eta, transferred, total)

        # Track totals
        self._total_bytes_transferred = sum(
            d.get("transferred", 0) for d in self._get_active_dicts())
        self._total_bytes_all = sum(
            d.get("total", 0) for d in self._get_active_dicts())

        if percent >= 100:
            self._completed_count += 1
            widget.mark_complete(True)
            QTimer.singleShot(3000, lambda p=path: self._remove_transfer_widget(p))

    def _get_active_dicts(self) -> list[dict]:
        """Get active transfer dicts from transfer manager if available."""
        for engine in self.drive_app.engines.values():
            if hasattr(engine, 'transfer_manager'):
                return engine.transfer_manager.active_transfers
        return []

    def _add_transfer_widget(self, path: str, direction: str):
        if self._no_transfers_label.isVisible():
            self._no_transfers_label.setVisible(False)

        if self._session_start == 0:
            self._session_start = time.time()

        widget = _TransferItemWidget(path, direction)
        self._transfer_widgets[path] = widget
        # Insert before the stretch
        idx = self._transfers_layout.count() - 1
        self._transfers_layout.insertWidget(idx, widget)

        self._total_queued += 1
        self._update_buttons_visibility()

    def _remove_transfer_widget(self, path: str):
        widget = self._transfer_widgets.pop(path, None)
        if widget:
            self._transfers_layout.removeWidget(widget)
            widget.deleteLater()

        if not self._transfer_widgets:
            self._no_transfers_label.setVisible(True)
            self._update_buttons_visibility()
            # Reset session when all done
            if self._completed_count > 0:
                self._overall_progress.setValue(1000)
                self._overall_progress.setFormat(
                    f"✓ {self._completed_count} files transferred")
                self._overall_status.setText("Complete")
                self._overall_status.setStyleSheet(
                    "color: #4CAF50; font-size: 13px; font-weight: bold;")
                QTimer.singleShot(10000, self._reset_session)

    def _reset_session(self):
        if self._transfer_widgets:
            return
        self._completed_count = 0
        self._total_queued = 0
        self._total_bytes_transferred = 0
        self._total_bytes_all = 0
        self._session_start = 0.0
        self._overall_progress.setValue(0)
        self._overall_progress.setFormat("No active transfers")
        self._overall_status.setText("Idle")
        self._overall_status.setStyleSheet(
            "color: #4CAF50; font-size: 13px; font-weight: bold;")
        self._files_label.setText("Files: 0 / 0")
        self._size_label.setText("Size: 0 B / 0 B")
        self._speed_label.setText("Speed: —")
        self._eta_label.setText("ETA: —")

    def _update_overall_stats(self):
        """Periodic update of overall progress bar and stats."""
        active = len(self._transfer_widgets)
        if active == 0 and self._completed_count == 0:
            return

        total_files = self._total_queued
        done_files = self._completed_count

        # File count
        self._files_label.setText(
            f"Files: {done_files} / {total_files}"
            + (f"  ({active} active)" if active else ""))

        # Size
        if self._total_bytes_all > 0:
            self._size_label.setText(
                f"Size: {_format_size(self._total_bytes_transferred)} / "
                f"{_format_size(self._total_bytes_all)}")

        # Overall progress
        if total_files > 0:
            active_dicts = self._get_active_dicts()
            active_percent_sum = sum(d.get("percent", 0) for d in active_dicts) / 100.0
            effective_done = done_files + active_percent_sum
            overall_pct = (effective_done / total_files) * 100
            self._overall_progress.setValue(int(overall_pct * 10))
            self._overall_progress.setFormat(f"{overall_pct:.1f}%")

        # Aggregate speed
        active_dicts = self._get_active_dicts()
        total_speed = sum(d.get("speed_bps", 0) for d in active_dicts)
        if total_speed > 0:
            self._speed_label.setText(f"Speed: {_format_speed(total_speed)}")

            remaining = max(0, self._total_bytes_all - self._total_bytes_transferred)
            eta_sec = int(remaining / total_speed) if total_speed > 0 else 0
            self._eta_label.setText(f"ETA: {_format_eta(eta_sec)}")
        elif active == 0:
            self._speed_label.setText("Speed: —")
            self._eta_label.setText("ETA: —")

    def _update_buttons_visibility(self):
        has_active = len(self._transfer_widgets) > 0
        self._pause_btn.setVisible(has_active)
        self._cancel_all_btn.setVisible(has_active)
        if has_active:
            self._overall_status.setText("Transferring")
            self._overall_status.setStyleSheet(
                "color: #2196F3; font-size: 13px; font-weight: bold;")

    def _toggle_pause(self):
        if self.drive_app.status == "paused":
            self.drive_app.resume()
        else:
            self.drive_app.pause()

    def _on_status_changed(self, status: str):
        if status == "paused":
            self._pause_btn.setText("▶  Resume")
            self._pause_btn.setStyleSheet(_STYLE_BTN_RESUME)
            self._overall_status.setText("Paused")
            self._overall_status.setStyleSheet(
                "color: #FF9800; font-size: 13px; font-weight: bold;")
        elif status == "syncing":
            self._pause_btn.setText("⏸  Pause")
            self._pause_btn.setStyleSheet(_STYLE_BTN_PAUSE)
            self._overall_status.setText("Syncing")
            self._overall_status.setStyleSheet(
                "color: #2196F3; font-size: 13px; font-weight: bold;")
        elif status == "idle":
            self._pause_btn.setText("⏸  Pause")
            self._pause_btn.setStyleSheet(_STYLE_BTN_PAUSE)
            if not self._transfer_widgets:
                self._overall_status.setText("Idle")
                self._overall_status.setStyleSheet(
                    "color: #4CAF50; font-size: 13px; font-weight: bold;")

    def _cancel_all(self):
        for engine in self.drive_app.engines.values():
            if hasattr(engine, 'transfer_manager'):
                engine.transfer_manager.cancel_all()
        for path in list(self._transfer_widgets.keys()):
            w = self._transfer_widgets.get(path)
            if w:
                w.mark_complete(False)
        QTimer.singleShot(2000, self._clear_all_transfers)

    def _clear_all_transfers(self):
        for path in list(self._transfer_widgets.keys()):
            self._remove_transfer_widget(path)

    def _refresh_log(self):
        """Refresh the history table from the database."""
        self._history_table.setRowCount(0)

        for task in self.drive_app.config.sync_tasks:
            task_filter = self._task_filter.currentData()
            if task_filter and task_filter != task.id:
                continue

            entries = self.drive_app.state_db.get_recent_log(task.id, limit=200)

            action_filter = self._action_filter.currentText()
            for entry in entries:
                action = entry.get("action", "")
                if action_filter == "Uploads" and action != "upload":
                    continue
                if action_filter == "Downloads" and action != "download":
                    continue
                if action_filter == "Deletes" and "delete" not in action:
                    continue
                if action_filter == "Errors" and entry.get("success", 1):
                    continue

                row = self._history_table.rowCount()
                self._history_table.insertRow(row)

                ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry["timestamp"]))
                self._history_table.setItem(row, 0, QTableWidgetItem(ts))

                icon = ACTION_ICONS.get(action, "•")
                self._history_table.setItem(row, 1, QTableWidgetItem(f"{icon} {action}"))
                self._history_table.setItem(row, 2, QTableWidgetItem(entry.get("path", "")))
                self._history_table.setItem(row, 3, QTableWidgetItem(task.name))

                status = "✓" if entry.get("success") else "✗ " + entry.get("detail", "")
                item = QTableWidgetItem(status)
                if not entry.get("success"):
                    item.setForeground(QColor("#F44336"))
                self._history_table.setItem(row, 4, item)
