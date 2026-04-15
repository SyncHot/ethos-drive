"""Login and server connection dialog."""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QMessageBox, QProgressBar,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

from ethos_drive.config import Config
from ethos_drive.api.client import EthosAPIClient, APIError

log = logging.getLogger(__name__)


def _normalize_server_url(server: str) -> str:
    """Add scheme to server URL — http for LAN IPs, https for domains."""
    if server.startswith(("http://", "https://")):
        return server
    host_part = server.split(":")[0].split("/")[0]
    is_ip = host_part.replace(".", "").isdigit()
    is_local = host_part in ("localhost", "127.0.0.1") or host_part.endswith(".local")
    if is_ip or is_local:
        return "http://" + server
    return "https://" + server


class _LoginWorker(QThread):
    """Background thread for login to keep UI responsive."""
    # success, result_type ("token"/"totp_required"), value (token or "")
    finished = Signal(bool, str, str)

    def __init__(self, server_url: str, username: str, password: str,
                 verify_ssl: bool, totp_code: str = ""):
        super().__init__()
        self.server_url = server_url
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.totp_code = totp_code

    def run(self):
        try:
            client = EthosAPIClient(self.server_url, verify_ssl=self.verify_ssl)
            data = client.login(self.username, self.password, self.totp_code)
            client.close()

            if data.get("totp_required"):
                self.finished.emit(True, "totp_required", "")
                return

            token = data.get("token")
            if token:
                self.finished.emit(True, "token", token)
            else:
                self.finished.emit(False, "error",
                    "Login failed — server returned no token. Check credentials.")

        except APIError as e:
            if e.status_code == 401:
                msg = e.response.get("error", "Invalid username or password.") if e.response else str(e)
                self.finished.emit(False, "error", msg)
            else:
                self.finished.emit(False, "error", str(e))
        except Exception as e:
            err = str(e)
            if "https://" in self.server_url and ("SSL" in err or "CERTIFICATE" in err.upper()
                                                   or "Connect" in err or "timed out" in err.lower()):
                self.finished.emit(False, "error",
                    f"Connection failed. If your server uses HTTP, change the address to:\n"
                    f"http://{self.server_url.replace('https://', '')}\n\nError: {err}")
            else:
                self.finished.emit(False, "error", f"Connection error: {err}")


class LoginDialog(QDialog):
    """Server connection and authentication dialog."""

    login_successful = Signal(str, str, str)  # server_url, username, token

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Connect to EthOS Server")
        self.setFixedSize(420, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        # Title
        title = QLabel("EthOS Drive")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Connect to your EthOS server")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #888; margin-bottom: 8px;")
        layout.addWidget(subtitle)

        # Server URL
        layout.addWidget(QLabel("Server Address:"))
        self._server_input = QLineEdit()
        self._server_input.setPlaceholderText("192.168.1.100:9000 or my-nas.local:9000")
        self._server_input.setText(self.config.server_url)
        layout.addWidget(self._server_input)

        # Username
        layout.addWidget(QLabel("Username:"))
        self._username_input = QLineEdit()
        self._username_input.setPlaceholderText("admin")
        self._username_input.setText(self.config.username)
        layout.addWidget(self._username_input)

        # Password
        layout.addWidget(QLabel("Password:"))
        self._password_input = QLineEdit()
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.setPlaceholderText("••••••••")
        layout.addWidget(self._password_input)

        # TOTP (hidden initially, shown when server requires it)
        self._totp_label = QLabel("2FA Code:")
        self._totp_label.hide()
        layout.addWidget(self._totp_label)
        self._totp_input = QLineEdit()
        self._totp_input.setPlaceholderText("6-digit code from authenticator app")
        self._totp_input.setMaxLength(6)
        self._totp_input.hide()
        layout.addWidget(self._totp_input)

        # SSL verification
        self._verify_ssl = QCheckBox("Verify SSL certificate")
        self._verify_ssl.setChecked(self.config.verify_ssl)
        layout.addWidget(self._verify_ssl)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # Indeterminate
        self._progress.hide()
        layout.addWidget(self._progress)

        # Buttons
        btn_row = QHBoxLayout()
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setDefault(True)
        self._connect_btn.clicked.connect(self._on_connect)
        btn_row.addStretch()
        btn_row.addWidget(self._connect_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        # Enter key triggers connect
        self._password_input.returnPressed.connect(self._on_connect)
        self._totp_input.returnPressed.connect(self._on_connect)

    def _on_connect(self):
        server = _normalize_server_url(self._server_input.text().strip())
        username = self._username_input.text().strip()
        password = self._password_input.text()
        totp_code = self._totp_input.text().strip()

        if not server or server in ("http://", "https://"):
            QMessageBox.warning(self, "Error", "Please enter a server address.")
            return
        if not username:
            QMessageBox.warning(self, "Error", "Please enter a username.")
            return
        if not password:
            QMessageBox.warning(self, "Error", "Please enter a password.")
            return
        if self._totp_input.isVisible() and not totp_code:
            QMessageBox.warning(self, "Error", "Please enter your 2FA code.")
            return

        self._connect_btn.setEnabled(False)
        self._progress.show()

        self._worker = _LoginWorker(server, username, password,
                                     self._verify_ssl.isChecked(), totp_code)
        self._worker.finished.connect(self._on_login_result)
        self._worker.start()

    def _on_login_result(self, success: bool, result_type: str, value: str):
        self._progress.hide()
        self._connect_btn.setEnabled(True)

        if not success:
            QMessageBox.critical(self, "Connection Failed", value)
            return

        if result_type == "totp_required":
            # Show TOTP input and let user enter code
            self._totp_label.show()
            self._totp_input.show()
            self._totp_input.setFocus()
            self.setFixedSize(420, 440)
            return

        # result_type == "token"
        server = _normalize_server_url(self._server_input.text().strip())
        username = self._username_input.text().strip()

        self.config.server_url = server
        self.config.username = username
        self.config.verify_ssl = self._verify_ssl.isChecked()
        self.config.save_credentials(username, self._password_input.text())
        self.config.save_token(value)
        self.config.save()

        self.login_successful.emit(server, username, value)
        self.accept()
