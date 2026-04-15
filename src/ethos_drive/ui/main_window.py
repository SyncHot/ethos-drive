"""Main settings and dashboard window."""

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QCheckBox,
    QSpinBox, QComboBox, QGroupBox, QFormLayout, QMessageBox,
    QFileDialog, QStackedWidget, QFrame, QSplitter,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QIcon, QColor

if TYPE_CHECKING:
    from ethos_drive.app import EthosDriveApp

from ethos_drive.config import SyncTask
from ethos_drive.ui.task_editor import TaskEditorDialog
from ethos_drive.ui.activity import ActivityWidget
from ethos_drive.ui.conflicts import ConflictsWidget
from ethos_drive.ui.icons import get_app_icon

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main EthOS Drive window — dashboard, sync tasks, settings."""

    def __init__(self, app: "EthosDriveApp"):
        super().__init__()
        self.drive_app = app
        self._setup_ui()
        self._refresh_tasks()

        # Connect signals
        app.status_changed.connect(self._update_status)
        app.sync_progress.connect(self._on_sync_progress)

    def _setup_ui(self):
        self.setWindowTitle("EthOS Drive")
        self.setWindowIcon(get_app_icon())
        self.setMinimumSize(700, 500)
        self.resize(850, 600)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Status bar at top
        self._status_bar = self._create_status_bar()
        layout.addWidget(self._status_bar)

        # Tab widget
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # Tab 1: Sync Tasks
        self._tasks_tab = self._create_tasks_tab()
        self._tabs.addTab(self._tasks_tab, "Sync Tasks")

        # Tab 2: Transfers & Activity
        self._activity_widget = ActivityWidget(self.drive_app)
        self._tabs.addTab(self._activity_widget, "Transfers")

        # Tab 3: Conflicts
        self._conflicts_widget = ConflictsWidget(self.drive_app)
        self._tabs.addTab(self._conflicts_widget, "Conflicts")

        # Tab 4: Settings
        self._settings_tab = self._create_settings_tab()
        self._tabs.addTab(self._settings_tab, "Settings")

    def _create_status_bar(self) -> QFrame:
        """Create the top status bar."""
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: #1a1a2e; padding: 8px 16px; }")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 8, 16, 8)

        self._status_icon = QLabel("●")
        self._status_icon.setStyleSheet("color: #9E9E9E; font-size: 18px;")
        layout.addWidget(self._status_icon)

        self._status_text = QLabel("Not connected")
        self._status_text.setStyleSheet("color: #ccc; font-size: 13px;")
        layout.addWidget(self._status_text)

        layout.addStretch()

        self._pause_btn = QPushButton("⏸ Pause")
        self._pause_btn.setStyleSheet(
            "QPushButton { background: #FF9800; color: white; border: none; padding: 6px 16px; "
            "border-radius: 4px; font-weight: bold; } QPushButton:hover { background: #F57C00; }")
        self._pause_btn.clicked.connect(self._toggle_pause)
        self._pause_btn.setVisible(False)
        layout.addWidget(self._pause_btn)

        self._sync_now_btn = QPushButton("Sync Now")
        self._sync_now_btn.setStyleSheet(
            "QPushButton { background: #2196F3; color: white; border: none; padding: 6px 16px; "
            "border-radius: 4px; } QPushButton:hover { background: #1976D2; }")
        self._sync_now_btn.clicked.connect(self.drive_app.sync_all)
        layout.addWidget(self._sync_now_btn)

        return frame

    def _create_tasks_tab(self) -> QWidget:
        """Create the sync tasks management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Toolbar
        toolbar = QHBoxLayout()
        add_btn = QPushButton("+ Add Sync Task")
        add_btn.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white; border: none; padding: 8px 16px; "
            "border-radius: 4px; font-weight: bold; } QPushButton:hover { background: #388E3C; }")
        add_btn.clicked.connect(self._add_task)
        toolbar.addWidget(add_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Task list
        self._task_list = QListWidget()
        self._task_list.setSpacing(4)
        self._task_list.itemDoubleClicked.connect(self._edit_task)
        layout.addWidget(self._task_list)

        # Task actions
        actions = QHBoxLayout()
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(lambda: self._edit_task(self._task_list.currentItem()))
        actions.addWidget(edit_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setStyleSheet("color: #F44336;")
        remove_btn.clicked.connect(self._remove_task)
        actions.addWidget(remove_btn)

        actions.addStretch()

        sync_btn = QPushButton("Sync Selected")
        sync_btn.clicked.connect(self._sync_selected)
        actions.addWidget(sync_btn)

        layout.addLayout(actions)
        return widget

    def _create_settings_tab(self) -> QWidget:
        """Create the general settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Connection settings
        conn_group = QGroupBox("Connection")
        conn_form = QFormLayout(conn_group)

        self._server_label = QLabel(self.drive_app.config.server_url or "Not connected")
        conn_form.addRow("Server:", self._server_label)

        self._user_label = QLabel(self.drive_app.config.username or "—")
        conn_form.addRow("Username:", self._user_label)

        reconnect_btn = QPushButton("Change Server...")
        reconnect_btn.clicked.connect(self._reconnect)
        disconnect_btn = QPushButton("Disconnect")
        disconnect_btn.clicked.connect(self._disconnect)
        btn_row = QHBoxLayout()
        btn_row.addWidget(reconnect_btn)
        btn_row.addWidget(disconnect_btn)
        conn_form.addRow("", btn_row)
        layout.addWidget(conn_group)

        # General settings
        gen_group = QGroupBox("General")
        gen_form = QFormLayout(gen_group)

        self._auto_start_cb = QCheckBox("Launch EthOS Drive when Windows starts")
        self._auto_start_cb.setChecked(self.drive_app.config.auto_start)
        self._auto_start_cb.toggled.connect(self._on_auto_start_changed)
        gen_form.addRow(self._auto_start_cb)

        self._start_min_cb = QCheckBox("Start minimized to tray")
        self._start_min_cb.setChecked(self.drive_app.config.start_minimized)
        self._start_min_cb.toggled.connect(self._save_settings)
        gen_form.addRow(self._start_min_cb)

        self._notify_cb = QCheckBox("Show sync notifications")
        self._notify_cb.setChecked(self.drive_app.config.show_notifications)
        self._notify_cb.toggled.connect(self._save_settings)
        gen_form.addRow(self._notify_cb)

        layout.addWidget(gen_group)

        # Explorer integration
        drive_group = QGroupBox("Explorer Integration")
        drive_form = QFormLayout(drive_group)

        self._mount_drive_cb = QCheckBox("Show EthOS Drive in Explorer sidebar")
        self._mount_drive_cb.setChecked(self.drive_app.config.mount_as_drive)
        self._mount_drive_cb.toggled.connect(self._on_mount_drive_changed)
        drive_form.addRow(self._mount_drive_cb)

        if self.drive_app._mounted_drive:
            mounted_label = QLabel("✓ Visible in Explorer navigation pane")
            mounted_label.setStyleSheet("color: #4CAF50;")
            drive_form.addRow(mounted_label)

        layout.addWidget(drive_group)

        # Transfer settings
        transfer_group = QGroupBox("Transfers")
        transfer_form = QFormLayout(transfer_group)

        self._max_transfers = QSpinBox()
        self._max_transfers.setRange(1, 10)
        self._max_transfers.setValue(self.drive_app.config.max_concurrent_transfers)
        self._max_transfers.valueChanged.connect(self._save_settings)
        transfer_form.addRow("Max concurrent transfers:", self._max_transfers)

        layout.addWidget(transfer_group)

        # Log level
        log_group = QGroupBox("Logging")
        log_form = QFormLayout(log_group)
        self._log_level = QComboBox()
        self._log_level.addItems(["INFO", "DEBUG", "WARNING", "ERROR"])
        self._log_level.setCurrentText(self.drive_app.config.log_level)
        self._log_level.currentTextChanged.connect(self._save_settings)
        log_form.addRow("Log level:", self._log_level)
        layout.addWidget(log_group)

        # Updates
        update_group = QGroupBox("Updates")
        update_form = QFormLayout(update_group)

        self._auto_update_cb = QCheckBox("Automatically check for updates")
        self._auto_update_cb.setChecked(self.drive_app.config.auto_update)
        self._auto_update_cb.toggled.connect(self._save_settings)
        update_form.addRow(self._auto_update_cb)

        update_row = QHBoxLayout()
        self._check_update_btn = QPushButton("Check Now")
        self._check_update_btn.setStyleSheet(
            "QPushButton { background: #2196F3; color: white; border: none; padding: 6px 16px; "
            "border-radius: 4px; } QPushButton:hover { background: #1976D2; }")
        self._check_update_btn.clicked.connect(self._check_for_updates)
        update_row.addWidget(self._check_update_btn)

        from ethos_drive import __version__
        self._version_label = QLabel(f"Current version: v{__version__}")
        self._version_label.setStyleSheet("color: #888;")
        update_row.addWidget(self._version_label)
        update_row.addStretch()
        update_form.addRow(update_row)

        self._update_status_label = QLabel("")
        update_form.addRow(self._update_status_label)

        layout.addWidget(update_group)

        # Wire update signals
        self.drive_app.update_available.connect(self._on_update_available)

        layout.addStretch()
        return widget

    def _update_status(self, status: str):
        colors = {
            "idle": "#4CAF50", "syncing": "#2196F3",
            "paused": "#FF9800", "error": "#F44336", "offline": "#9E9E9E",
        }
        labels = {
            "idle": "Up to date", "syncing": "Syncing...",
            "paused": "Paused", "error": "Error", "offline": "Not connected",
        }
        color = colors.get(status, "#9E9E9E")
        self._status_icon.setStyleSheet(f"color: {color}; font-size: 18px;")
        self._status_text.setText(labels.get(status, status))

        # Show/hide pause button
        connected = status not in ("offline",)
        self._pause_btn.setVisible(connected)
        if status == "paused":
            self._pause_btn.setText("▶ Resume")
            self._pause_btn.setStyleSheet(
                "QPushButton { background: #4CAF50; color: white; border: none; padding: 6px 16px; "
                "border-radius: 4px; font-weight: bold; } QPushButton:hover { background: #388E3C; }")
        else:
            self._pause_btn.setText("⏸ Pause")
            self._pause_btn.setStyleSheet(
                "QPushButton { background: #FF9800; color: white; border: none; padding: 6px 16px; "
                "border-radius: 4px; font-weight: bold; } QPushButton:hover { background: #F57C00; }")

    def _toggle_pause(self):
        if self.drive_app.status == "paused":
            self.drive_app.resume()
        else:
            self.drive_app.pause()

    def _on_sync_progress(self, data: dict):
        pass  # Could update task list items with progress

    def _refresh_tasks(self):
        """Refresh the task list widget."""
        self._task_list.clear()
        for task in self.drive_app.config.sync_tasks:
            item = QListWidgetItem()
            status = "✓ Active" if task.enabled else "⏸ Disabled"
            direction = {"bidirectional": "↔", "upload_only": "↑", "download_only": "↓"}
            arrow = direction.get(task.direction, "↔")
            item.setText(f"{task.name}  {arrow}  {task.local_path}  ⟷  {task.remote_path}  [{status}]")
            item.setData(Qt.UserRole, task.id)
            self._task_list.addItem(item)

    def _add_task(self):
        task = SyncTask()
        dlg = TaskEditorDialog(task, self.drive_app.api_client, parent=self)
        if dlg.exec():
            self.drive_app.add_task(task)
            self._refresh_tasks()

    def _edit_task(self, item):
        if not item:
            return
        task_id = item.data(Qt.UserRole)
        for task in self.drive_app.config.sync_tasks:
            if task.id == task_id:
                dlg = TaskEditorDialog(task, self.drive_app.api_client, parent=self)
                if dlg.exec():
                    self.drive_app.config.save()
                    self._refresh_tasks()
                break

    def _remove_task(self):
        item = self._task_list.currentItem()
        if not item:
            return
        task_id = item.data(Qt.UserRole)
        reply = QMessageBox.question(self, "Remove Task",
                                     "Remove this sync task? Local files will not be deleted.",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.drive_app.remove_task(task_id)
            self._refresh_tasks()

    def _sync_selected(self):
        item = self._task_list.currentItem()
        if item:
            self.drive_app.sync_task(item.data(Qt.UserRole))

    def _disconnect(self):
        reply = QMessageBox.question(self, "Disconnect",
                                     "Disconnect from server? Sync will stop.",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.drive_app.disconnect()
            self.drive_app.config.clear_credentials()

    def _save_settings(self):
        cfg = self.drive_app.config
        cfg.auto_start = self._auto_start_cb.isChecked()
        cfg.start_minimized = self._start_min_cb.isChecked()
        cfg.show_notifications = self._notify_cb.isChecked()
        cfg.mount_as_drive = self._mount_drive_cb.isChecked()
        cfg.auto_update = self._auto_update_cb.isChecked()
        cfg.max_concurrent_transfers = self._max_transfers.value()
        cfg.log_level = self._log_level.currentText()
        cfg.save()

    def _on_auto_start_changed(self, enabled: bool):
        self._save_settings()
        self.drive_app._apply_auto_start()

    def _on_mount_drive_changed(self, enabled: bool):
        self._save_settings()
        if enabled:
            self.drive_app._mount_drive()
        else:
            self.drive_app._unmount_drive()

    def _reconnect(self):
        self.drive_app.disconnect()
        self.drive_app.show_login()

    def _check_for_updates(self):
        """Manual update check from settings."""
        self._check_update_btn.setEnabled(False)
        self._check_update_btn.setText("Checking...")
        self._update_status_label.setText("")
        self.drive_app.updater.no_update.connect(self._on_no_update)
        self.drive_app.check_for_updates()

    def _on_no_update(self):
        self._check_update_btn.setEnabled(True)
        self._check_update_btn.setText("Check Now")
        self._update_status_label.setText("✓ You're up to date!")
        self._update_status_label.setStyleSheet("color: #4CAF50;")
        try:
            self.drive_app.updater.no_update.disconnect(self._on_no_update)
        except RuntimeError:
            pass

    def _on_update_available(self, version: str, url: str, notes: str):
        """Show update info in settings tab."""
        self._check_update_btn.setEnabled(True)
        self._check_update_btn.setText("Check Now")
        self._update_status_label.setText(f"⬆ Version {version} available!")
        self._update_status_label.setStyleSheet("color: #2196F3; font-weight: bold;")

        reply = QMessageBox.question(
            self, "Update Available",
            f"EthOS Drive v{version} is available.\n\n{notes[:300]}\n\nDownload and install now?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.drive_app.download_and_install_update(url)

    def show_activity_tab(self):
        self._tabs.setCurrentWidget(self._activity_widget)

    def show_settings_tab(self):
        self._tabs.setCurrentWidget(self._settings_tab)

    def closeEvent(self, event):
        """Hide instead of close — app lives in system tray."""
        event.ignore()
        self.hide()
