"""Update download progress dialog."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ethos_drive.ui.icons import get_app_icon


class UpdateProgressDialog(QDialog):
    """Shows download and install progress for app updates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Updating EthOS Drive")
        self.setWindowIcon(get_app_icon())
        self.setFixedSize(400, 180)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        self._title = QLabel("Downloading update...")
        self._title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(True)
        self._bar.setFixedHeight(22)
        self._bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 4px;
                text-align: center;
                background: #f0f0f0;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2196F3, stop:1 #42A5F5
                );
                border-radius: 3px;
            }
        """)
        layout.addWidget(self._bar)

        self._status = QLabel("0%")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color: #666;")
        layout.addWidget(self._status)

        layout.addStretch()

    def set_progress(self, percent: int):
        """Update progress bar (0-100)."""
        self._bar.setValue(percent)
        self._status.setText(f"{percent}%")

    def set_installing(self):
        """Switch to 'installing' state."""
        self._title.setText("Installing update...")
        self._bar.setRange(0, 0)  # indeterminate
        self._status.setText("The app will restart automatically.")

    def set_error(self, message: str):
        """Show error state."""
        self._title.setText("Update failed")
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._status.setText(message)
        self._status.setStyleSheet("color: #F44336;")
