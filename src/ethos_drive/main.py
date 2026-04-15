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

    # On Windows, set AppUserModelID BEFORE QApplication so the taskbar
    # and window title bars use our custom icon instead of the Python default.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "EthOS.Drive.Client.1")
        except Exception:
            pass

    # Allow clean Ctrl+C shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon

    from ethos_drive.app import EthosDriveApp
    from ethos_drive.utils.logging import setup_logging
    from ethos_drive.ui.icons import get_app_icon

    setup_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("EthOS Drive")
    app.setOrganizationName("EthOS")
    app.setQuitOnLastWindowClosed(False)

    # Keep lock handle alive
    app._instance_lock = _lock

    # Set application icon (propagates to all windows on most platforms)
    app.setWindowIcon(get_app_icon())

    start_minimized = "--minimized" in sys.argv

    drive_app = EthosDriveApp()
    drive_app.start(minimized=start_minimized)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
