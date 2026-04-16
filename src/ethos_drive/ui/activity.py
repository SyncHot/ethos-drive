"""Activity — modern transfer progress panel with pause/resume."""

import logging
import os
import time
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QProgressBar, QFrame,
    QScrollArea, QSplitter, QSizePolicy, QLineEdit,
)
from PySide6.QtCore import Qt, QTimer

if TYPE_CHECKING:
    from ethos_drive.app import EthosDriveApp

from ethos_drive.ui import theme

log = logging.getLogger(__name__)

ACTION_ICONS = {
    "upload": "↑",
    "download": "↓",
    "delete_local": "✕",
    "delete_remote": "✕",
    "conflict": "⚠",
}


class _TransferItemWidget(QFrame):
    """Modern single-file transfer card."""

    def __init__(self, path: str, direction: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.direction = direction
        self.setStyleSheet(f"""
            _TransferItemWidget {{
                background: {theme.BG_SURFACE};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_SM};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)

        arrow = "↑" if direction == "upload" else "↓"
        arrow_color = theme.SUCCESS if direction == "upload" else theme.INFO
        self._icon_label = QLabel(arrow)
        self._icon_label.setStyleSheet(
            f"color: {arrow_color}; font-size: 16px; font-weight: bold;")
        self._icon_label.setFixedWidth(20)
        top.addWidget(self._icon_label)

        filename = os.path.basename(path) if "/" in path or "\\" in path else path
        self._name_label = QLabel(filename)
        self._name_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
        self._name_label.setToolTip(path)
        self._name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(self._name_label)

        self._speed_label = QLabel("—")
        self._speed_label.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: {theme.FONT_SIZE_SM}; min-width: 80px;")
        self._speed_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self._speed_label)

        self._eta_label = QLabel("—")
        self._eta_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_SIZE_SM}; min-width: 60px;")
        self._eta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self._eta_label)

        self._size_label = QLabel("")
        self._size_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_SIZE_SM}; min-width: 100px;")
        self._size_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self._size_label)

        layout.addLayout(top)

        # Thin progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        chunk_color = theme.SUCCESS if direction == "upload" else theme.ACCENT
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background: {theme.BG_INPUT};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: {chunk_color};
                border-radius: 2px;
            }}
        """)
        layout.addWidget(self._progress)

    def update_progress(self, percent: float, speed_bps: int, eta_sec: int,
                        transferred: int = 0, total: int = 0):
        self._progress.setValue(int(percent * 10))
        self._speed_label.setText(theme.format_speed(speed_bps))
        self._eta_label.setText(theme.format_eta(eta_sec))
        if total > 0:
            self._size_label.setText(
                f"{theme.format_size(transferred)} / {theme.format_size(total)}")

    def mark_complete(self, success: bool):
        if success:
            self._progress.setValue(1000)
            self._speed_label.setText("✓")
            self._speed_label.setStyleSheet(
                f"color: {theme.SUCCESS}; font-size: {theme.FONT_SIZE_SM};")
            self._eta_label.setText("")
        else:
            self._speed_label.setText("✗")
            self._speed_label.setStyleSheet(
                f"color: {theme.ERROR}; font-size: {theme.FONT_SIZE_SM};")
            self._progress.setStyleSheet(f"""
                QProgressBar {{
                    background: {theme.BG_INPUT}; border: none; border-radius: 2px;
                }}
                QProgressBar::chunk {{
                    background: {theme.ERROR}; border-radius: 2px;
                }}
            """)


class _HistoryItemWidget(QFrame):
    """Compact card for a single sync history entry."""

    def __init__(self, entry: dict, task_name: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            _HistoryItemWidget {{
                background: {theme.BG_SURFACE};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_SM};
            }}
            _HistoryItemWidget:hover {{
                border-color: {theme.TEXT_SECONDARY};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        action = entry.get("action", "")
        icon = ACTION_ICONS.get(action, "•")
        is_upload = action == "upload"
        is_error = not entry.get("success", 1)
        icon_color = theme.ERROR if is_error else (
            theme.SUCCESS if is_upload else theme.INFO if action == "download" else theme.WARNING)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"color: {icon_color}; font-size: 16px; font-weight: bold;")
        icon_lbl.setFixedWidth(20)
        layout.addWidget(icon_lbl)

        # File info column
        info = QVBoxLayout()
        info.setSpacing(2)

        path = entry.get("path", "")
        filename = os.path.basename(path) if "/" in path or "\\" in path else path
        name_lbl = QLabel(filename)
        name_lbl.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
        name_lbl.setToolTip(path)
        info.addWidget(name_lbl)

        # Subtext: folder + size + task
        parts = []
        folder = os.path.dirname(path)
        if folder:
            parts.append(folder)
        size = entry.get("bytes_transferred", 0)
        if size:
            parts.append(theme.format_size(size))
        parts.append(task_name)
        sub_text = "  ·  ".join(parts)
        sub_lbl = QLabel(sub_text)
        sub_lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_SIZE_SM};")
        info.addWidget(sub_lbl)

        layout.addLayout(info, 1)

        # Time ago
        ts = entry.get("timestamp", 0)
        ago = theme.time_ago(ts) if ts else ""
        time_lbl = QLabel(ago)
        time_lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_SIZE_SM};")
        time_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        time_lbl.setFixedWidth(60)
        layout.addWidget(time_lbl)

        # Status
        if is_error:
            err_lbl = QLabel("Failed")
            err_lbl.setStyleSheet(f"color: {theme.ERROR}; font-size: {theme.FONT_SIZE_SM};")
            err_lbl.setFixedWidth(50)
            layout.addWidget(err_lbl)


class ActivityWidget(QWidget):
    """Modern transfer & history panel with real-time progress."""

    def __init__(self, app: "EthosDriveApp"):
        super().__init__()
        self.drive_app = app
        self._transfer_widgets: dict[str, _TransferItemWidget] = {}
        self._history_widgets: list[_HistoryItemWidget] = []
        self._completed_count = 0
        self._total_queued = 0
        self._total_bytes_transferred = 0
        self._total_bytes_all = 0
        self._session_start = 0.0
        self._last_phase_update = 0.0
        self._history_offset = 0
        self._history_search = ""
        self._setup_ui()

        app.sync_progress.connect(self._on_progress)
        app.status_changed.connect(self._on_status_changed)

        self._stats_timer = QTimer()
        self._stats_timer.timeout.connect(self._update_overall_stats)
        self._stats_timer.start(1000)

        self._history_timer = QTimer()
        self._history_timer.timeout.connect(self._refresh_log)
        self._history_timer.start(5000)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── Overall progress panel ──
        overall_panel = QFrame()
        overall_panel.setStyleSheet(f"""
            QFrame {{
                background: {theme.BG_SURFACE};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS};
            }}
        """)
        op_layout = QVBoxLayout(overall_panel)
        op_layout.setContentsMargins(20, 16, 20, 16)
        op_layout.setSpacing(10)

        # Title row
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title_lbl = QLabel("Transfers")
        title_lbl.setStyleSheet(
            f"font-weight: 600; font-size: {theme.FONT_SIZE_LG}; color: {theme.TEXT_PRIMARY};")
        title_row.addWidget(title_lbl)

        self._overall_status = QLabel("Idle")
        self._overall_status.setStyleSheet(
            f"color: {theme.SUCCESS}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
        title_row.addWidget(self._overall_status)
        title_row.addStretch()

        self._pause_btn = QPushButton("⏸  Pause")
        self._pause_btn.setProperty("class", "flat")
        self._pause_btn.clicked.connect(self._toggle_pause)
        self._pause_btn.setFixedWidth(110)
        self._pause_btn.setVisible(False)
        title_row.addWidget(self._pause_btn)

        self._cancel_all_btn = QPushButton("Cancel All")
        self._cancel_all_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {theme.ERROR};
                border: 1px solid {theme.ERROR}; padding: 5px 14px;
                border-radius: {theme.RADIUS_SM}; font-size: {theme.FONT_SIZE_SM};
            }}
            QPushButton:hover {{ background: {theme.ERROR}; color: white; }}
        """)
        self._cancel_all_btn.clicked.connect(self._cancel_all)
        self._cancel_all_btn.setVisible(False)
        title_row.addWidget(self._cancel_all_btn)

        op_layout.addLayout(title_row)

        # Overall progress bar (thin)
        self._overall_progress = QProgressBar()
        self._overall_progress.setRange(0, 1000)
        self._overall_progress.setValue(0)
        self._overall_progress.setTextVisible(False)
        self._overall_progress.setFixedHeight(4)
        op_layout.addWidget(self._overall_progress)

        # Stats row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(24)

        for name, default_text in [
            ("_files_label", "0 / 0 files"),
            ("_size_label", "—"),
            ("_speed_label", "—"),
            ("_eta_label", "—"),
        ]:
            lbl = QLabel(default_text)
            lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_SIZE_SM};")
            setattr(self, name, lbl)
            stats_row.addWidget(lbl)

        stats_row.addStretch()
        op_layout.addLayout(stats_row)
        layout.addWidget(overall_panel)

        # ── Splitter: active transfers / history ──
        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {theme.BORDER}; height: 1px; }}")

        # Active transfers
        transfers_container = QWidget()
        tc_layout = QVBoxLayout(transfers_container)
        tc_layout.setContentsMargins(0, 0, 0, 0)
        tc_layout.setSpacing(6)

        tf_header = QLabel("Active")
        tf_header.setStyleSheet(
            f"font-weight: 600; font-size: {theme.FONT_SIZE}; color: {theme.TEXT_SECONDARY};")
        tc_layout.addWidget(tf_header)

        self._transfers_scroll = QScrollArea()
        self._transfers_scroll.setWidgetResizable(True)
        self._transfers_scroll.setFrameShape(QFrame.NoFrame)

        self._transfers_list = QWidget()
        self._transfers_layout = QVBoxLayout(self._transfers_list)
        self._transfers_layout.setContentsMargins(0, 0, 0, 0)
        self._transfers_layout.setSpacing(4)
        self._transfers_layout.addStretch()

        self._no_transfers_label = QLabel("No active transfers")
        self._no_transfers_label.setStyleSheet(
            f"color: {theme.TEXT_DISABLED}; font-size: {theme.FONT_SIZE}; padding: 24px;")
        self._no_transfers_label.setAlignment(Qt.AlignCenter)
        self._transfers_layout.insertWidget(0, self._no_transfers_label)

        self._transfers_scroll.setWidget(self._transfers_list)
        tc_layout.addWidget(self._transfers_scroll)
        splitter.addWidget(transfers_container)

        # History section
        history_container = QWidget()
        hc_layout = QVBoxLayout(history_container)
        hc_layout.setContentsMargins(0, 8, 0, 0)
        hc_layout.setSpacing(6)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)
        hl = QLabel("History")
        hl.setStyleSheet(
            f"font-weight: 600; font-size: {theme.FONT_SIZE}; color: {theme.TEXT_SECONDARY};")
        filter_row.addWidget(hl)
        filter_row.addStretch()

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search files…")
        self._search_input.setFixedWidth(180)
        self._search_input.textChanged.connect(self._on_search_changed)
        filter_row.addWidget(self._search_input)

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
        self._task_filter.setFixedWidth(130)
        filter_row.addWidget(self._task_filter)

        hc_layout.addLayout(filter_row)

        # History scroll area with card-based items
        self._history_scroll = QScrollArea()
        self._history_scroll.setWidgetResizable(True)
        self._history_scroll.setFrameShape(QFrame.NoFrame)

        self._history_list = QWidget()
        self._history_layout = QVBoxLayout(self._history_list)
        self._history_layout.setContentsMargins(0, 0, 0, 0)
        self._history_layout.setSpacing(4)

        self._no_history_label = QLabel("No sync history yet")
        self._no_history_label.setStyleSheet(
            f"color: {theme.TEXT_DISABLED}; font-size: {theme.FONT_SIZE}; padding: 24px;")
        self._no_history_label.setAlignment(Qt.AlignCenter)
        self._history_layout.addWidget(self._no_history_label)
        self._history_layout.addStretch()

        # "Load more" button
        self._load_more_btn = QPushButton("Load more…")
        self._load_more_btn.setProperty("class", "flat")
        self._load_more_btn.clicked.connect(self._load_more_history)
        self._load_more_btn.setVisible(False)
        self._history_layout.addWidget(self._load_more_btn, alignment=Qt.AlignCenter)

        self._history_scroll.setWidget(self._history_list)
        hc_layout.addWidget(self._history_scroll)
        splitter.addWidget(history_container)

        splitter.setSizes([250, 350])
        layout.addWidget(splitter)

    # ── Progress handling ──────────────────────────────────────

    def _on_progress(self, data: dict):
        phase = data.get("phase", "")
        if phase:
            now = time.monotonic()
            if now - self._last_phase_update < 0.25:
                return
            self._last_phase_update = now

            total_actions = data.get("total", 0)
            done_actions = data.get("done", 0)
            pct = data.get("percent", 0)
            label = data.get("file", "")

            if phase in ("scanning", "planning"):
                self._overall_status.setText(label)
                self._overall_status.setStyleSheet(
                    f"color: {theme.WARNING}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
                self._overall_progress.setValue(int(pct * 10))
            elif phase == "syncing":
                # Per-file transfer progress from engine
                action = data.get("action", "")
                speed = data.get("speed", 0)
                eta = data.get("eta", 0)
                transferred = data.get("transferred", 0)
                total = data.get("total", 0)
                file_path = data.get("file", "")

                if action in ("upload", "download") and file_path:
                    if file_path not in self._transfer_widgets:
                        self._add_transfer_widget(file_path, action)
                    widget = self._transfer_widgets.get(file_path)
                    if widget:
                        widget.update_progress(pct, speed, eta, transferred, total)

                    self._total_bytes_transferred = sum(
                        d.get("transferred", 0) for d in self._get_active_dicts())
                    self._total_bytes_all = sum(
                        d.get("total", 0) for d in self._get_active_dicts())

                    if pct >= 100:
                        self._completed_count += 1
                        if widget:
                            widget.mark_complete(True)
                        QTimer.singleShot(3000,
                                          lambda p=file_path: self._remove_transfer_widget(p))
                    return

                self._overall_status.setText(f"Syncing ({done_actions}/{total_actions})")
                self._overall_status.setStyleSheet(
                    f"color: {theme.ACCENT}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
                self._overall_progress.setValue(int(pct * 10))
                self._files_label.setText(f"{done_actions} / {total_actions} files")
            return

        # Per-file transfer progress (from TransferManager directly)
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

        self._total_bytes_transferred = sum(
            d.get("transferred", 0) for d in self._get_active_dicts())
        self._total_bytes_all = sum(
            d.get("total", 0) for d in self._get_active_dicts())

        if percent >= 100:
            self._completed_count += 1
            widget.mark_complete(True)
            QTimer.singleShot(3000, lambda p=path: self._remove_transfer_widget(p))

    def _get_active_dicts(self) -> list[dict]:
        result = []
        for engine in self.drive_app.engines.values():
            if hasattr(engine, 'transfer_mgr'):
                result.extend(engine.transfer_mgr.active_transfers)
        return result

    def _add_transfer_widget(self, path: str, direction: str):
        if self._no_transfers_label.isVisible():
            self._no_transfers_label.setVisible(False)
        if self._session_start == 0:
            self._session_start = time.time()

        widget = _TransferItemWidget(path, direction)
        self._transfer_widgets[path] = widget
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
            if self._completed_count > 0:
                self._overall_progress.setValue(1000)
                self._overall_status.setText(
                    f"✓ {self._completed_count} files transferred")
                self._overall_status.setStyleSheet(
                    f"color: {theme.SUCCESS}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
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
        self._overall_status.setText("Idle")
        self._overall_status.setStyleSheet(
            f"color: {theme.SUCCESS}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
        self._files_label.setText("0 / 0 files")
        self._size_label.setText("—")
        self._speed_label.setText("—")
        self._eta_label.setText("—")

    def _update_overall_stats(self):
        active = len(self._transfer_widgets)
        if active == 0 and self._completed_count == 0:
            return

        total_files = self._total_queued
        done_files = self._completed_count
        self._files_label.setText(
            f"{done_files} / {total_files} files"
            + (f"  ({active} active)" if active else ""))

        if self._total_bytes_all > 0:
            self._size_label.setText(
                f"{theme.format_size(self._total_bytes_transferred)} / "
                f"{theme.format_size(self._total_bytes_all)}")

        if total_files > 0:
            active_dicts = self._get_active_dicts()
            active_pct_sum = sum(d.get("percent", 0) for d in active_dicts) / 100.0
            effective_done = done_files + active_pct_sum
            overall_pct = (effective_done / total_files) * 100
            self._overall_progress.setValue(int(overall_pct * 10))

        active_dicts = self._get_active_dicts()
        total_speed = sum(d.get("speed_bps", 0) for d in active_dicts)
        if total_speed > 0:
            self._speed_label.setText(theme.format_speed(total_speed))
            remaining = max(0, self._total_bytes_all - self._total_bytes_transferred)
            eta_sec = int(remaining / total_speed) if total_speed > 0 else 0
            self._eta_label.setText(theme.format_eta(eta_sec))
        elif active == 0:
            self._speed_label.setText("—")
            self._eta_label.setText("—")

    def _update_buttons_visibility(self):
        has_active = len(self._transfer_widgets) > 0
        self._pause_btn.setVisible(has_active)
        self._cancel_all_btn.setVisible(has_active)
        if has_active:
            self._overall_status.setText("Transferring")
            self._overall_status.setStyleSheet(
                f"color: {theme.ACCENT}; font-size: {theme.FONT_SIZE}; font-weight: 500;")

    def _toggle_pause(self):
        if self.drive_app.status == "paused":
            self.drive_app.resume()
        else:
            self.drive_app.pause()

    def _on_status_changed(self, status: str):
        base = status.split(":")[0] if ":" in status else status
        if base == "paused":
            self._pause_btn.setText("▶  Resume")
            self._overall_status.setText("Paused")
            self._overall_status.setStyleSheet(
                f"color: {theme.WARNING}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
        elif base == "syncing":
            self._pause_btn.setText("⏸  Pause")
            self._overall_status.setText("Syncing")
            self._overall_status.setStyleSheet(
                f"color: {theme.ACCENT}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
        elif base == "idle":
            self._pause_btn.setText("⏸  Pause")
            if not self._transfer_widgets:
                self._overall_status.setText("Idle")
                self._overall_status.setStyleSheet(
                    f"color: {theme.SUCCESS}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
        elif base == "offline":
            self._overall_status.setText("Offline")
            self._overall_status.setStyleSheet(
                f"color: {theme.TEXT_DISABLED}; font-size: {theme.FONT_SIZE}; font-weight: 500;")

    def _cancel_all(self):
        for engine in self.drive_app.engines.values():
            if hasattr(engine, 'transfer_mgr'):
                engine.transfer_mgr.cancel_all()
        for path in list(self._transfer_widgets.keys()):
            w = self._transfer_widgets.get(path)
            if w:
                w.mark_complete(False)
        QTimer.singleShot(2000, self._clear_all_transfers)

    def _clear_all_transfers(self):
        for path in list(self._transfer_widgets.keys()):
            self._remove_transfer_widget(path)

    # ── History ────────────────────────────────────────────────

    def _on_search_changed(self, text: str):
        self._history_search = text.strip().lower()
        self._refresh_log()

    def _refresh_log(self):
        """Refresh the history with modern card-based items."""
        # Clear existing
        for w in self._history_widgets:
            self._history_layout.removeWidget(w)
            w.deleteLater()
        self._history_widgets.clear()
        self._history_offset = 0

        self._load_history_batch()

    def _load_history_batch(self, batch_size: int = 100):
        """Load a batch of history entries."""
        task_filter = self._task_filter.currentData()
        action_filter = self._action_filter.currentText()
        search = self._history_search

        # Build task name lookup
        task_names = {t.id: t.name for t in self.drive_app.config.sync_tasks}

        entries = self.drive_app.state_db.get_recent_log(
            task_id=task_filter, limit=batch_size + 1,
            offset=self._history_offset)

        has_more = len(entries) > batch_size
        entries = entries[:batch_size]

        count = 0
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
            if search and search not in entry.get("path", "").lower():
                continue

            task_name = task_names.get(entry.get("task_id", ""), "?")
            widget = _HistoryItemWidget(entry, task_name)
            self._history_widgets.append(widget)

            # Insert before stretch + load-more button
            idx = self._history_layout.count() - 2
            if idx < 0:
                idx = 0
            self._history_layout.insertWidget(idx, widget)
            count += 1

        self._history_offset += batch_size
        self._no_history_label.setVisible(count == 0 and self._history_offset <= batch_size)
        self._load_more_btn.setVisible(has_more)

    def _load_more_history(self):
        self._load_history_batch()
