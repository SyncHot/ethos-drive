"""Auto-updater — checks GitHub Releases for new versions and applies updates."""

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
ASSET_NAME = "EthOS.Drive.exe"


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

            # Find the installer asset
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

    def install_update(self, installer_path: str = ""):
        """Launch the installer and quit the app."""
        path = installer_path or self._pending_installer
        if not path or not os.path.isfile(path):
            log.error("No installer to run")
            return

        log.info("Launching installer: %s", path)
        try:
            # /SILENT = no UI, /CLOSEAPPLICATIONS = close running instance
            subprocess.Popen(
                [path, "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0,
            )
            # Quit the app so installer can replace files
            from PySide6.QtWidgets import QApplication
            QApplication.quit()
        except Exception as e:
            log.error("Failed to launch installer: %s", e)
