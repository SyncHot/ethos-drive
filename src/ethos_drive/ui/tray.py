"""System tray icon and menu — the always-visible entry point for EthOS Drive."""

import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPen, QAction
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from ethos_drive.app import EthosDriveApp

from ethos_drive.ui.icons import get_app_icon, _find_ico_path

log = logging.getLogger(__name__)

# Status colors
STATUS_COLORS = {
    "idle":     "#4CAF50",   # Green
    "syncing":  "#2196F3",   # Blue
    "paused":   "#FF9800",   # Orange
    "error":    "#F44336",   # Red
    "offline":  "#9E9E9E",   # Gray
}

STATUS_LABELS = {
    "idle":     "Up to date",
    "syncing":  "Syncing...",
    "paused":   "Paused",
    "error":    "Error — click for details",
    "offline":  "Not connected",
}


def _create_status_icon(color_hex: str, size: int = 64) -> QIcon:
    """Generate a colored tray icon for status indication."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    bg = QColor(color_hex)
    painter.setBrush(bg)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 6, 6)
    painter.setPen(QPen(QColor("#FFFFFF")))
    font = QFont("Arial", int(size * 0.45))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "E")
    painter.end()
    return QIcon(pixmap)


class SystemTray(QSystemTrayIcon):
    """System tray icon with context menu for EthOS Drive."""

    def __init__(self, app: "EthosDriveApp"):
        super().__init__()
        self.drive_app = app

        self._ico_path = _find_ico_path()
        self._base_icon = get_app_icon()
        self.setIcon(self._base_icon)
        self.setToolTip("EthOS Drive")

        self._build_menu()
        self._update_status("offline")

        # Connect signals
        app.status_changed.connect(self._update_status)
        self.activated.connect(self._on_activated)

    def _build_menu(self):
        """Build the tray context menu."""
        menu = QMenu()

        self._status_label = QAction("EthOS Drive", menu)
        self._status_label.setEnabled(False)
        menu.addAction(self._status_label)
        menu.addSeparator()

        self._connect_action = QAction("Connect to Server...", menu)
        self._connect_action.triggered.connect(self.drive_app.show_login)
        menu.addAction(self._connect_action)

        self._sync_now_action = QAction("Sync Now", menu)
        self._sync_now_action.triggered.connect(self.drive_app.sync_all)
        menu.addAction(self._sync_now_action)

        self._pause_action = QAction("Pause Syncing", menu)
        self._pause_action.triggered.connect(self._toggle_pause)
        menu.addAction(self._pause_action)

        menu.addSeparator()

        open_action = QAction("Open EthOS Drive", menu)
        open_action.triggered.connect(self._open_main_window)
        menu.addAction(open_action)

        activity_action = QAction("Recent Activity", menu)
        activity_action.triggered.connect(self._open_activity)
        menu.addAction(activity_action)

        menu.addSeparator()

        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        self._update_action = QAction("Check for Updates", menu)
        self._update_action.triggered.connect(self._check_updates)
        menu.addAction(self._update_action)

        # Listen for update availability
        self.drive_app.update_available.connect(self._on_update_available)

        menu.addSeparator()

        open_log_action = QAction("Open Log File", menu)
        open_log_action.triggered.connect(self._open_log_file)
        menu.addAction(open_log_action)

        restart_action = QAction("Restart", menu)
        restart_action.triggered.connect(self._restart_app)
        menu.addAction(restart_action)

        menu.addSeparator()

        quit_action = QAction("Quit EthOS Drive", menu)
        quit_action.triggered.connect(self.drive_app.quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def _update_status(self, status: str):
        """Update tray tooltip based on sync status."""
        # Always use the same icon (.ico file has multiple sizes built in)
        # Status is shown only in tooltip and menu label
        label = STATUS_LABELS.get(status, status)
        self.setToolTip(f"EthOS Drive - {label}")
        self._status_label.setText(f"EthOS Drive - {label}")

        # Show connect when offline, hide when connected
        self._connect_action.setVisible(status in ("offline", "error"))
        self._sync_now_action.setEnabled(status not in ("offline",))

        # Update pause button text
        if status == "paused":
            self._pause_action.setText("Resume Syncing")
        else:
            self._pause_action.setText("Pause Syncing")

    def _toggle_pause(self):
        if self.drive_app.status == "paused":
            self.drive_app.resume()
        else:
            self.drive_app.pause()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._open_main_window()

    def _open_main_window(self):
        from ethos_drive.ui.main_window import MainWindow
        if not hasattr(self, "_main_window") or self._main_window is None:
            self._main_window = MainWindow(self.drive_app)
        self._main_window.show()
        self._main_window.raise_()
        self._main_window.activateWindow()

    def _open_activity(self):
        self._open_main_window()
        if hasattr(self._main_window, "show_activity_tab"):
            self._main_window.show_activity_tab()

    def _open_settings(self):
        self._open_main_window()
        if hasattr(self._main_window, "show_settings_tab"):
            self._main_window.show_settings_tab()

    def _check_updates(self):
        self.drive_app.check_for_updates()

    def _on_update_available(self, version: str, url: str, notes: str):
        """Show update action in tray menu when an update is available."""
        self._pending_update_url = url
        self._update_action.setText(f"Update to v{version}...")
        self._update_action.triggered.disconnect()
        self._update_action.triggered.connect(self._install_pending_update)

    def _install_pending_update(self):
        url = getattr(self, "_pending_update_url", "")
        if url:
            self.drive_app.download_and_install_update(url)

    def _open_log_file(self):
        """Open the log file in the default text editor."""
        import platformdirs
        from pathlib import Path
        log_file = Path(platformdirs.user_log_dir("EthOS Drive", "EthOS")) / "ethos-drive.log"
        if not log_file.exists():
            self.showMessage("EthOS Drive", "Log file not found yet.",
                             QSystemTrayIcon.MessageIcon.Warning, 3000)
            return
        if os.name == "nt":
            os.startfile(str(log_file))
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(log_file)])

    def _restart_app(self):
        """Restart the application."""
        import sys
        log.info("User requested restart")
        self.drive_app.disconnect()
        executable = sys.executable
        args = sys.argv[:]
        if getattr(sys, "frozen", False):
            # PyInstaller frozen app — re-launch the exe
            os.execv(executable, [executable] + args[1:])
        else:
            os.execv(executable, [executable] + args)
