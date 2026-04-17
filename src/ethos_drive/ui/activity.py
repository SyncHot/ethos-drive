"""Activity — modern transfer progress panel with pause/resume."""

import logging
import os
import time
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QProgressBar, QFrame,
    QScrollArea, QSizePolicy, QLineEdit,
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
    """Clean global progress + history panel."""

    def __init__(self, app: "EthosDriveApp"):
        super().__init__()
        self.drive_app = app
        self._history_widgets: list[_HistoryItemWidget] = []
        # Progress tracking from engine phase signals
        self._total_actions = 0
        self._done_actions = 0
        self._current_file = ""
        self._current_action = ""
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

        # ── Global progress panel ──
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
        title_lbl = QLabel("Sync Progress")
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

        # ── Big progress bar with percentage ──
        self._overall_progress = QProgressBar()
        self._overall_progress.setRange(0, 1000)
        self._overall_progress.setValue(0)
        self._overall_progress.setTextVisible(False)
        self._overall_progress.setFixedHeight(24)
        self._overall_progress.setStyleSheet(f"""
            QProgressBar {{
                background: {theme.BG_INPUT};
                border: none;
                border-radius: 12px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {theme.ACCENT}, stop:1 {theme.SUCCESS});
                border-radius: 12px;
            }}
        """)
        op_layout.addWidget(self._overall_progress)

        # Percentage + current file label
        pct_row = QHBoxLayout()
        pct_row.setSpacing(8)
        self._pct_label = QLabel("0%")
        self._pct_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 18px; font-weight: 700; min-width: 50px;")
        pct_row.addWidget(self._pct_label)

        self._current_file_label = QLabel("")
        self._current_file_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_SIZE_SM};")
        self._current_file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        pct_row.addWidget(self._current_file_label)
        op_layout.addLayout(pct_row)

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

        # ── History section ──
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
        layout.addWidget(history_container, 1)  # stretch to fill

    # ── Progress handling ──────────────────────────────────────

    def _on_progress(self, data: dict):
        phase = data.get("phase", "")
        if phase:
            now = time.monotonic()
            if now - self._last_phase_update < 0.15:
                return
            self._last_phase_update = now

            total_actions = data.get("total", 0)
            done_actions = data.get("done", 0)
            pct = data.get("percent", 0)
            label = data.get("file", "")
            action = data.get("action", "")

            if self._session_start == 0 and phase != "error":
                self._session_start = time.time()

            if phase in ("scanning", "planning"):
                self._overall_status.setText(
                    "Scanning…" if phase == "scanning" else "Planning…")
                self._overall_status.setStyleSheet(
                    f"color: {theme.WARNING}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
                # scanning/planning: show indeterminate-ish progress (0-10%)
                bar_pct = pct * 0.1  # 0-50% of scanning → 0-5% of bar
                self._overall_progress.setValue(int(bar_pct * 10))
                self._pct_label.setText(f"{int(bar_pct)}%")
                self._current_file_label.setText(label)
                self._pause_btn.setVisible(True)
                self._cancel_all_btn.setVisible(True)

            elif phase == "syncing":
                self._total_actions = total_actions
                self._done_actions = done_actions
                self._current_file = label
                self._current_action = action

                # Per-file transfer progress from engine progress callback
                if action in ("upload", "download") and label:
                    speed = data.get("speed", 0)
                    transferred = data.get("transferred", 0)
                    total = data.get("total", 0)
                    if transferred > 0 and total > 0:
                        self._total_bytes_transferred += max(
                            0, transferred - getattr(self, '_last_file_transferred', 0))
                        self._last_file_transferred = transferred
                        self._total_bytes_all = max(self._total_bytes_all, total)
                    arrow = "↑" if action == "upload" else "↓"
                    fname = os.path.basename(label) if ("/" in label or "\\" in label) else label
                    self._current_file_label.setText(f"{arrow} {fname}")
                    return

                # Phase progress (done/total actions)
                self._last_file_transferred = 0
                self._overall_status.setText(f"Syncing ({done_actions}/{total_actions})")
                self._overall_status.setStyleSheet(
                    f"color: {theme.ACCENT}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
                # Map 0-100% of syncing to 10-100% of bar
                bar_pct = 10 + pct * 0.9
                self._overall_progress.setValue(int(bar_pct * 10))
                self._pct_label.setText(f"{int(bar_pct)}%")
                self._files_label.setText(f"{done_actions} / {total_actions} files")
                self._pause_btn.setVisible(True)
                self._cancel_all_btn.setVisible(True)

                if done_actions >= total_actions and total_actions > 0:
                    self._on_sync_complete()

            elif phase == "error":
                self._overall_status.setText(label)
                self._overall_status.setStyleSheet(
                    f"color: {theme.ERROR}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
            return

        # Per-file transfer progress (from TransferManager directly)
        path = data.get("path", "")
        direction = data.get("direction", "")
        speed = data.get("speed_bps", 0)
        transferred = data.get("transferred", 0)
        total = data.get("total", 0)

        if path:
            arrow = "↑" if direction == "upload" else "↓"
            fname = os.path.basename(path) if ("/" in path or "\\" in path) else path
            self._current_file_label.setText(f"{arrow} {fname}")

    def _on_sync_complete(self):
        self._overall_progress.setValue(1000)
        self._pct_label.setText("100%")
        done = self._done_actions
        self._overall_status.setText(f"✓ {done} files synced")
        self._overall_status.setStyleSheet(
            f"color: {theme.SUCCESS}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
        self._current_file_label.setText("")
        self._pause_btn.setVisible(False)
        self._cancel_all_btn.setVisible(False)
        QTimer.singleShot(15000, self._reset_session)

    def _reset_session(self):
        if self._total_actions > 0 and self._done_actions < self._total_actions:
            return  # Still syncing
        self._total_actions = 0
        self._done_actions = 0
        self._total_bytes_transferred = 0
        self._total_bytes_all = 0
        self._session_start = 0.0
        self._last_file_transferred = 0
        self._overall_progress.setValue(0)
        self._pct_label.setText("0%")
        self._overall_status.setText("Idle")
        self._overall_status.setStyleSheet(
            f"color: {theme.SUCCESS}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
        self._current_file_label.setText("")
        self._files_label.setText("0 / 0 files")
        self._size_label.setText("—")
        self._speed_label.setText("—")
        self._eta_label.setText("—")

    def _update_overall_stats(self):
        if self._total_actions == 0:
            return

        # Aggregate speed from active TransferManager transfers
        active_dicts = []
        for engine in self.drive_app.engines.values():
            if hasattr(engine, 'transfer_mgr'):
                active_dicts.extend(engine.transfer_mgr.active_transfers)

        total_speed = sum(d.get("speed_bps", 0) for d in active_dicts)
        if total_speed > 0:
            self._speed_label.setText(theme.format_speed(total_speed))
            remaining = max(0, self._total_bytes_all - self._total_bytes_transferred)
            eta_sec = int(remaining / total_speed) if total_speed > 0 else 0
            self._eta_label.setText(theme.format_eta(eta_sec))
        elif not active_dicts:
            self._speed_label.setText("—")
            self._eta_label.setText("—")

        if self._total_bytes_all > 0:
            self._size_label.setText(
                f"{theme.format_size(self._total_bytes_transferred)} / "
                f"{theme.format_size(self._total_bytes_all)}")

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
            if self._total_actions == 0:
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
            engine._cancelled = True
        self._overall_status.setText("Cancelled")
        self._overall_status.setStyleSheet(
            f"color: {theme.ERROR}; font-size: {theme.FONT_SIZE}; font-weight: 500;")
        self._current_file_label.setText("")
        self._pause_btn.setVisible(False)
        self._cancel_all_btn.setVisible(False)
        QTimer.singleShot(5000, self._reset_session)

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
