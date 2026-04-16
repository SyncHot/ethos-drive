"""Auto-updater — checks GitHub Releases for new versions and applies updates.

Update flow (Windows, --onefile PyInstaller):
  1. Download new .exe to a temp file
  2. Write a tiny .cmd script that waits for our process to die,
     copies the new exe over the old one, starts it, and cleans up
  3. Launch the .cmd script as a fully detached process
  4. Quit the current app (releases file lock + mutex)
"""

import logging
import os
import subprocess
import sys
import tempfile
from packaging import version as pkg_version

from PySide6.QtCore import QObject, Signal, QThread

log = logging.getLogger(__name__)

GITHUB_REPO = "SyncHot/ethos-drive"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


class _UpdateCheckWorker(QThread):
    """Background thread that checks for updates."""
    result = Signal(bool, str, str, str)  # has_update, new_version, download_url, release_notes

    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version

    def run(self):
        try:
            import httpx
            resp = httpx.get(RELEASES_URL, timeout=15, follow_redirects=True)
            if resp.status_code != 200:
                log.debug("Update check: HTTP %s", resp.status_code)
                self.result.emit(False, "", "", "")
                return

            data = resp.json()
            tag = data.get("tag_name", "").lstrip("v")
            if not tag:
                self.result.emit(False, "", "", "")
                return

            try:
                remote = pkg_version.parse(tag)
                local = pkg_version.parse(self.current_version)
                has_update = remote > local
            except Exception:
                has_update = tag != self.current_version

            if not has_update:
                log.info("Up to date (v%s)", self.current_version)
                self.result.emit(False, tag, "", "")
                return

            # Find the exe asset
            download_url = ""
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name.lower().endswith(".exe"):
                    download_url = asset.get("browser_download_url", "")
                    break

            notes = data.get("body", "")[:500]
            log.info("Update available: v%s -> v%s", self.current_version, tag)
            self.result.emit(True, tag, download_url, notes)

        except Exception as e:
            log.error("Update check failed: %s", e)
            self.result.emit(False, "", "", "")


class _DownloadWorker(QThread):
    """Background thread that downloads the update installer."""
    progress = Signal(int)        # 0-100
    finished = Signal(bool, str)  # success, file_path_or_error

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            import httpx
            tmp = tempfile.mktemp(suffix=".exe", prefix="EthOSDrive_update_")

            with httpx.stream("GET", self.url, timeout=120, follow_redirects=True) as resp:
                if resp.status_code != 200:
                    self.finished.emit(False, f"HTTP {resp.status_code}")
                    return

                total = int(resp.headers.get("content-length", 0))
                downloaded = 0

                with open(tmp, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=256 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            self.progress.emit(int(downloaded / total * 100))

            log.info("Update downloaded: %s (%d bytes)", tmp, downloaded)
            self.finished.emit(True, tmp)

        except Exception as e:
            log.error("Update download failed: %s", e)
            self.finished.emit(False, str(e))


class AutoUpdater(QObject):
    """Manages automatic update checking and installation."""

    update_available = Signal(str, str, str)  # version, download_url, notes
    update_downloaded = Signal(str)           # installer_path
    download_progress = Signal(int)           # 0-100
    download_failed = Signal(str)             # error message
    no_update = Signal()

    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version
        self._check_worker = None
        self._download_worker = None
        self._pending_installer = ""

    def check_for_updates(self):
        """Start a background update check."""
        if self._check_worker and self._check_worker.isRunning():
            return
        self._check_worker = _UpdateCheckWorker(self.current_version)
        self._check_worker.result.connect(self._on_check_result)
        self._check_worker.start()

    def _on_check_result(self, has_update: bool, version: str, url: str, notes: str):
        if has_update and url:
            self.update_available.emit(version, url, notes)
        else:
            self.no_update.emit()

    def download_update(self, url: str):
        """Download the update installer in background."""
        if self._download_worker and self._download_worker.isRunning():
            return
        self._download_worker = _DownloadWorker(url)
        self._download_worker.progress.connect(self.download_progress.emit)
        self._download_worker.finished.connect(self._on_download_done)
        self._download_worker.start()

    def _on_download_done(self, success: bool, result: str):
        if success:
            self._pending_installer = result
            self.update_downloaded.emit(result)
        else:
            log.error("Download failed: %s", result)
            self.download_failed.emit(result)

    install_failed = Signal(str)  # error message

    def install_update(self, installer_path: str = ""):
        """Replace the running exe with the downloaded update and restart.

        Strategy (Windows --onefile PyInstaller):
          • Write a small .cmd script to a temp file
          • The script polls until our PID is gone (exe file unlocked)
          • Copies the new exe over the old one
          • Launches the new exe with --minimized
          • Deletes itself
        """
        new_exe = installer_path or self._pending_installer
        if not new_exe or not os.path.isfile(new_exe):
            msg = "No update file to install"
            log.error(msg)
            self.install_failed.emit(msg)
            return

        current_exe = self._get_current_exe()
        if not current_exe:
            msg = "Cannot determine executable path — not a frozen app"
            log.error(msg)
            self.install_failed.emit(msg)
            return

        log.info("Self-update: %s -> %s", new_exe, current_exe)
        try:
            script = self._write_update_script(new_exe, current_exe)
            # Launch the updater script fully detached
            subprocess.Popen(
                ["cmd.exe", "/c", script],
                creationflags=(
                    subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NO_WINDOW
                ) if os.name == "nt" else 0,
                close_fds=True,
            )
            # Hard-exit so the exe file lock is released immediately.
            # QApplication.quit() doesn't always terminate when background
            # threads (sync engine, websocket, watchers) are still alive.
            log.info("Update script launched — force-exiting in 1s")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(500, lambda: os._exit(0))
        except Exception as e:
            msg = f"Failed to launch update script: {e}"
            log.error(msg)
            self.install_failed.emit(msg)

    # ------------------------------------------------------------------
    @staticmethod
    def _get_current_exe() -> str:
        """Return the path to the currently running frozen executable (or '')."""
        if getattr(sys, "frozen", False):
            return sys.executable
        return ""

    @staticmethod
    def _write_update_script(new_exe: str, current_exe: str) -> str:
        """Write a .cmd batch script that replaces the exe after we exit."""
        script_path = os.path.join(
            tempfile.gettempdir(), "ethos_drive_update.cmd",
        )
        log_path = os.path.join(
            tempfile.gettempdir(), "ethos_drive_update.log",
        )
        pid = os.getpid()
        with open(script_path, "w") as f:
            f.write(f"""@echo off
setlocal enabledelayedexpansion
set "NEW={new_exe}"
set "OLD={current_exe}"
set "LOG={log_path}"

echo [%date% %time%] Update script started (PID to wait for: {pid}) > "%LOG%"
echo [%date% %time%] NEW=%NEW% >> "%LOG%"
echo [%date% %time%] OLD=%OLD% >> "%LOG%"

REM --- Wait for the old process to exit ---
set TRIES=0
:wait
timeout /t 2 /nobreak > nul
tasklist /fi "PID eq {pid}" 2>nul | find /i "{pid}" >nul
if not errorlevel 1 (
    set /a TRIES+=1
    echo [%date% %time%] Waiting for PID {pid} to exit... attempt !TRIES!/15 >> "%LOG%"
    if !TRIES! LSS 15 goto wait
    echo [%date% %time%] FAIL: Process {pid} did not exit after 30s >> "%LOG%"
    exit /b 1
)

echo [%date% %time%] Process exited >> "%LOG%"

REM Grace period for file handle release
timeout /t 1 /nobreak > nul

REM --- Replace the exe (retry on lingering lock) ---
set TRIES=0
:copy
copy /y "%NEW%" "%OLD%" > nul 2>&1
if not errorlevel 1 goto ok
set /a TRIES+=1
echo [%date% %time%] Copy attempt !TRIES!/10 failed (file locked?) >> "%LOG%"
if !TRIES! LSS 10 (
    timeout /t 2 /nobreak > nul
    goto copy
)
echo [%date% %time%] FAIL: Could not copy after 10 attempts >> "%LOG%"
exit /b 1

:ok
echo [%date% %time%] Copy succeeded >> "%LOG%"
echo [%date% %time%] Launching: %OLD% --minimized >> "%LOG%"
start "" "%OLD%" --minimized
del "%NEW%" > nul 2>&1
echo [%date% %time%] Update complete >> "%LOG%"
(goto) 2>nul & del "%~f0"
""")
        log.info("Update script written: %s", script_path)
        return script_path
