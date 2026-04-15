"""Sync task editor dialog — configure folder pairs, filters, and sync options."""

import logging
from typing import Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QSpinBox, QGroupBox,
    QFormLayout, QFileDialog, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QWidget, QListWidget, QListWidgetItem, QMessageBox,
    QApplication,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor

from ethos_drive.config import SyncTask, FilterRule
from ethos_drive.api.client import EthosAPIClient

log = logging.getLogger(__name__)


class TaskEditorDialog(QDialog):
    """Dialog for creating or editing a sync task."""

    def __init__(self, task: SyncTask, api_client: Optional[EthosAPIClient] = None,
                 parent=None):
        super().__init__(parent)
        self.task = task
        self.api = api_client
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Sync Task" if self.task.name == "My Sync" else f"Edit: {self.task.name}")
        self.setMinimumSize(550, 480)

        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Tab 1: General
        tabs.addTab(self._create_general_tab(), "General")

        # Tab 2: Filters
        tabs.addTab(self._create_filters_tab(), "Filters")

        # Tab 3: Advanced
        tabs.addTab(self._create_advanced_tab(), "Advanced")

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _create_general_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setSpacing(10)

        # Task name
        self._name_input = QLineEdit(self.task.name)
        form.addRow("Task Name:", self._name_input)

        # Local folder
        local_row = QHBoxLayout()
        self._local_input = QLineEdit(self.task.local_path)
        self._local_input.setPlaceholderText("C:\\Users\\you\\EthOS Drive")
        local_row.addWidget(self._local_input)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_local)
        local_row.addWidget(browse_btn)
        form.addRow("Local Folder:", local_row)

        # Remote folder
        remote_row = QHBoxLayout()
        self._remote_input = QLineEdit(self.task.remote_path)
        self._remote_input.setPlaceholderText("/  (your home folder root)")
        self._remote_input.setToolTip(
            "Path relative to your home folder on EthOS.\n"
            "'/' = entire home folder\n"
            "'/Documents' = only Documents subfolder"
        )
        remote_row.addWidget(self._remote_input)
        if self.api:
            browse_remote_btn = QPushButton("Browse...")
            browse_remote_btn.clicked.connect(self._browse_remote)
            remote_row.addWidget(browse_remote_btn)
        form.addRow("Remote Folder:", remote_row)

        # Sync direction
        self._direction = QComboBox()
        self._direction.addItems([
            "Two-way (Bidirectional)",
            "Download Only (Server → PC)",
            "Upload Only (PC → Server)",
        ])
        dir_map = {"bidirectional": 0, "download_only": 1, "upload_only": 2}
        self._direction.setCurrentIndex(dir_map.get(self.task.direction, 0))
        form.addRow("Sync Direction:", self._direction)

        # Conflict strategy
        self._conflict = QComboBox()
        self._conflict.addItems([
            "Keep Newer File",
            "Keep Server Version",
            "Keep Local Version",
            "Keep Both (rename local)",
            "Ask Me Each Time",
        ])
        strat_map = {"keep_newer": 0, "keep_server": 1, "keep_local": 2, "keep_both": 3, "ask": 4}
        self._conflict.setCurrentIndex(strat_map.get(self.task.conflict_strategy, 0))
        form.addRow("On Conflict:", self._conflict)

        # Enabled
        self._enabled = QCheckBox("Enable this sync task")
        self._enabled.setChecked(self.task.enabled)
        form.addRow("", self._enabled)

        return widget

    def _create_filters_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("Exclude files matching these patterns:"))

        self._filter_list = QListWidget()
        for rule in self.task.filters:
            item = QListWidgetItem(f"{rule.type}: {rule.pattern}")
            if rule.max_size_mb:
                item.setText(f"{rule.type}: > {rule.max_size_mb} MB")
            item.setData(Qt.UserRole, rule)
            self._filter_list.addItem(item)
        layout.addWidget(self._filter_list)

        # Add filter controls
        add_row = QHBoxLayout()
        self._filter_pattern = QLineEdit()
        self._filter_pattern.setPlaceholderText("*.tmp, *.log, node_modules/")
        add_row.addWidget(self._filter_pattern)

        add_btn = QPushButton("Add Exclude")
        add_btn.clicked.connect(self._add_filter)
        add_row.addWidget(add_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda: self._filter_list.takeItem(self._filter_list.currentRow()))
        add_row.addWidget(remove_btn)
        layout.addLayout(add_row)

        # Max file size
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Skip files larger than:"))
        self._max_size = QSpinBox()
        self._max_size.setRange(0, 100000)
        self._max_size.setSuffix(" MB")
        self._max_size.setSpecialValueText("No limit")
        layout.addLayout(size_row)
        size_row.addWidget(self._max_size)

        # Sync hidden files
        self._sync_hidden = QCheckBox("Sync hidden files (dotfiles)")
        self._sync_hidden.setChecked(self.task.sync_hidden)
        layout.addWidget(self._sync_hidden)

        return widget

    def _create_advanced_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        # Bandwidth limits
        form.addRow(QLabel("Bandwidth Limits:"))

        self._upload_limit = QSpinBox()
        self._upload_limit.setRange(0, 1000000)
        self._upload_limit.setSuffix(" KB/s")
        self._upload_limit.setSpecialValueText("Unlimited")
        self._upload_limit.setValue(self.task.max_upload_kbps)
        form.addRow("Max Upload Speed:", self._upload_limit)

        self._download_limit = QSpinBox()
        self._download_limit.setRange(0, 1000000)
        self._download_limit.setSuffix(" KB/s")
        self._download_limit.setSpecialValueText("Unlimited")
        self._download_limit.setValue(self.task.max_download_kbps)
        form.addRow("Max Download Speed:", self._download_limit)

        # Sync interval
        self._sync_interval = QSpinBox()
        self._sync_interval.setRange(30, 3600)
        self._sync_interval.setSuffix(" seconds")
        self._sync_interval.setValue(self.task.sync_interval_seconds)
        form.addRow("Full Sync Interval:", self._sync_interval)

        return widget

    def _browse_local(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Local Folder",
                                                   self._local_input.text())
        if folder:
            self._local_input.setText(folder)

    def _browse_remote(self):
        """Open a tree browser dialog for selecting a remote folder."""
        if not self.api:
            return
        dlg = _RemoteBrowserDialog(self.api, self._remote_input.text(), parent=self)
        if dlg.exec():
            selected = dlg.selected_path
            if selected:
                self._remote_input.setText(selected)

    def _add_filter(self):
        pattern = self._filter_pattern.text().strip()
        if pattern:
            rule = FilterRule(type="exclude", pattern=pattern)
            item = QListWidgetItem(f"exclude: {pattern}")
            item.setData(Qt.UserRole, rule)
            self._filter_list.addItem(item)
            self._filter_pattern.clear()

    def _save(self):
        name = self._name_input.text().strip()
        local_path = self._local_input.text().strip()
        remote_path = self._remote_input.text().strip()

        if not name:
            QMessageBox.warning(self, "Error", "Please enter a task name.")
            return
        if not local_path:
            QMessageBox.warning(self, "Error", "Please select a local folder.")
            return
        if not remote_path:
            QMessageBox.warning(self, "Error", "Please enter a remote folder path.")
            return

        self.task.name = name
        self.task.local_path = local_path
        self.task.remote_path = remote_path
        self.task.enabled = self._enabled.isChecked()

        dir_map = {0: "bidirectional", 1: "download_only", 2: "upload_only"}
        self.task.direction = dir_map.get(self._direction.currentIndex(), "bidirectional")

        strat_map = {0: "keep_newer", 1: "keep_server", 2: "keep_local", 3: "keep_both", 4: "ask"}
        self.task.conflict_strategy = strat_map.get(self._conflict.currentIndex(), "keep_newer")

        # Collect filters
        self.task.filters = []
        for i in range(self._filter_list.count()):
            rule = self._filter_list.item(i).data(Qt.UserRole)
            if isinstance(rule, FilterRule):
                self.task.filters.append(rule)

        if self._max_size.value() > 0:
            self.task.filters.append(FilterRule(
                type="exclude", max_size_mb=self._max_size.value(), apply_to="files"
            ))

        self.task.sync_hidden = self._sync_hidden.isChecked()
        self.task.max_upload_kbps = self._upload_limit.value()
        self.task.max_download_kbps = self._download_limit.value()
        self.task.sync_interval_seconds = self._sync_interval.value()

        self.accept()


class _RemoteBrowserDialog(QDialog):
    """Tree browser dialog for selecting a remote folder from EthOS server.

    Uses native Windows styling (no forced dark theme) and ASCII-safe icons
    so it works reliably across all Windows versions and DPI settings.
    """

    def __init__(self, api: EthosAPIClient, initial_path: str = "/", parent=None):
        super().__init__(parent)
        self.api = api
        self.selected_path = initial_path or "/"
        self._setup_ui()
        # Load after dialog is fully constructed
        QTimer.singleShot(100, lambda: self._load_path("/"))

    def _setup_ui(self):
        self.setWindowTitle("Select Remote Folder")
        self.setMinimumSize(480, 420)
        self.resize(520, 520)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header
        header = QLabel("Select a folder from your EthOS home directory:")
        layout.addWidget(header)

        # Current path display
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Path:"))
        self._path_edit = QLineEdit("/")
        self._path_edit.setReadOnly(True)
        path_row.addWidget(self._path_edit)
        layout.addLayout(path_row)

        # Navigation buttons
        nav_row = QHBoxLayout()
        self._up_btn = QPushButton("<< Parent Folder")
        self._up_btn.clicked.connect(self._go_up)
        self._up_btn.setEnabled(False)
        nav_row.addWidget(self._up_btn)

        self._home_btn = QPushButton("Home (/)")
        self._home_btn.clicked.connect(lambda: self._load_path("/"))
        nav_row.addWidget(self._home_btn)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(lambda: self._load_path(self.selected_path))
        nav_row.addWidget(self._refresh_btn)

        nav_row.addStretch()
        layout.addLayout(nav_row)

        # Folder list (simple QListWidget is more reliable on Windows than QTreeWidget)
        self._folder_list = QListWidget()
        self._folder_list.setAlternatingRowColors(True)
        self._folder_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._folder_list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._folder_list)

        # Status
        self._status = QLabel("Connecting...")
        layout.addWidget(self._status)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._select_btn = QPushButton("Select This Folder")
        self._select_btn.setDefault(True)
        self._select_btn.clicked.connect(self._select_current)
        btn_row.addWidget(self._select_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _load_path(self, path: str):
        """Load directory contents from the server."""
        self._folder_list.clear()
        self.selected_path = path
        self._path_edit.setText(path)
        self._up_btn.setEnabled(path != "/")
        self._status.setText("Loading...")
        self._select_btn.setEnabled(False)

        # Force UI update before blocking API call
        QApplication.processEvents()

        try:
            log.info("Browsing remote path: %s", path)
            data = self.api.browse(path)
            log.info("Browse response: ok=%s, entries=%d",
                     data.get("ok"), len(data.get("entries", [])))

            if data.get("error"):
                self._status.setText(f"Error: {data['error']}")
                self._select_btn.setEnabled(True)
                return

            entries = data.get("entries", [])
            dirs = sorted([e for e in entries if e.get("is_dir")],
                          key=lambda e: e["name"].lower())
            files = sorted([e for e in entries if not e.get("is_dir")],
                           key=lambda e: e["name"].lower())

            # Show directories first (these are navigable)
            for entry in dirs:
                item = QListWidgetItem(f"[Folder]  {entry['name']}")
                item.setData(Qt.UserRole, entry["path"])
                item.setData(Qt.UserRole + 1, True)  # is_dir
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                self._folder_list.addItem(item)

            # Then files (dimmed, not selectable as target)
            for entry in files:
                size_str = self._format_size(entry.get("size", 0))
                item = QListWidgetItem(f"          {entry['name']}  ({size_str})")
                item.setData(Qt.UserRole, entry["path"])
                item.setData(Qt.UserRole + 1, False)
                item.setForeground(QColor(128, 128, 128))
                self._folder_list.addItem(item)

            dir_count = len(dirs)
            file_count = len(files)
            self._status.setText(
                f"{dir_count} folder{'s' if dir_count != 1 else ''}, "
                f"{file_count} file{'s' if file_count != 1 else ''}")

            if not entries:
                self._status.setText("Empty folder")

            self._select_btn.setEnabled(True)

        except Exception as e:
            log.error("Browse error for path '%s': %s", path, e, exc_info=True)
            self._status.setText(f"Error: {e}")
            self._select_btn.setEnabled(True)

    def _on_item_double_clicked(self, item):
        """Double-click on folder = navigate into it."""
        is_dir = item.data(Qt.UserRole + 1)
        if is_dir:
            path = item.data(Qt.UserRole)
            self._load_path(path)

    def _on_item_clicked(self, item):
        """Single click on folder = select it as target."""
        is_dir = item.data(Qt.UserRole + 1)
        if is_dir:
            path = item.data(Qt.UserRole)
            self.selected_path = path
            self._path_edit.setText(path)

    def _go_up(self):
        """Navigate to parent directory."""
        path = self.selected_path.rstrip("/")
        if "/" in path:
            parent = path.rsplit("/", 1)[0]
            if not parent:
                parent = "/"
            self._load_path(parent)
        else:
            self._load_path("/")

    def _select_current(self):
        """Select the currently displayed folder."""
        self.accept()

    @staticmethod
    def _format_size(b: int) -> str:
        if b < 1024:
            return f"{b} B"
        if b < 1024 * 1024:
            return f"{b / 1024:.1f} KB"
        if b < 1024 * 1024 * 1024:
            return f"{b / (1024 * 1024):.1f} MB"
        return f"{b / (1024 * 1024 * 1024):.2f} GB"
