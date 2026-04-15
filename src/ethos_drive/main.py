"""EthOS Drive entry point."""

import sys
import os
import signal

def main():
    """Launch EthOS Drive application."""
    # Allow clean Ctrl+C shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon

    from ethos_drive.app import EthosDriveApp
    from ethos_drive.utils.logging import setup_logging

    setup_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("EthOS Drive")
    app.setOrganizationName("EthOS")
    app.setQuitOnLastWindowClosed(False)

    # Set application icon — try .ico first (Windows), then .png
    icon_dir = os.path.join(os.path.dirname(__file__), "..", "resources", "icons")
    for icon_name in ("ethos-drive.ico", "ethos-drive.png"):
        icon_path = os.path.join(icon_dir, icon_name)
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            break

    start_minimized = "--minimized" in sys.argv

    drive_app = EthosDriveApp()
    drive_app.start(minimized=start_minimized)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
