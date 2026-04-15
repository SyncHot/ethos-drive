"""EthOS Drive entry point."""

import sys
import os
import signal


def _acquire_single_instance_lock():
    """Ensure only one instance of EthOS Drive is running.

    On Windows, uses a named kernel mutex.
    On other platforms, uses a lock file with fcntl.
    Returns a lock handle that must be kept alive for the process lifetime.
    Calls sys.exit(0) if another instance is already running.
    """
    LOCK_NAME = "EthOSDrive_SingleInstance"

    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, True, LOCK_NAME)
        ERROR_ALREADY_EXISTS = 183
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(mutex)
            # Try to bring existing window to front
            try:
                import ctypes.wintypes
                hwnd = ctypes.windll.user32.FindWindowW(None, "EthOS Drive")
                if hwnd:
                    SW_SHOW = 5
                    ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW)
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
            sys.exit(0)
        return mutex  # prevent GC
    else:
        import fcntl
        lock_path = os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
            f".{LOCK_NAME}.lock",
        )
        lock_file = open(lock_path, "w")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_file.write(str(os.getpid()))
            lock_file.flush()
            return lock_file  # prevent GC
        except OSError:
            sys.exit(0)


def main():
    """Launch EthOS Drive application."""
    # Single instance check — must be first
    _lock = _acquire_single_instance_lock()

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

    # Keep lock handle alive
    app._instance_lock = _lock

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
