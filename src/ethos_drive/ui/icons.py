"""Shared application icon helpers.

Provides a single get_app_icon() function that all windows and dialogs
should use so the icon appears correctly in title bars, taskbar, and Alt+Tab
on Windows.
"""

import os
import sys
import logging

from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPen
from PySide6.QtCore import Qt

log = logging.getLogger(__name__)

_cached_icon: QIcon | None = None


def _find_ico_path() -> str:
    """Find the ethos-drive.ico file (works both frozen and dev)."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        exe_dir = os.path.dirname(sys.executable)
        candidates = [
            os.path.join(meipass, "resources", "icons", "ethos-drive.ico") if meipass else "",
            os.path.join(exe_dir, "resources", "icons", "ethos-drive.ico"),
            os.path.join(exe_dir, "_internal", "resources", "icons", "ethos-drive.ico"),
        ]
    else:
        base = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base, "..", "..", "resources", "icons", "ethos-drive.ico"),
            os.path.join(base, "..", "resources", "icons", "ethos-drive.ico"),
        ]
    for c in candidates:
        if c:
            p = os.path.normpath(c)
            if os.path.isfile(p):
                return p
    return ""


def _create_fallback_icon(size: int = 64) -> QIcon:
    """Generate a simple icon when .ico file is not found."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#2196F3"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 8, 8)
    painter.setPen(QPen(QColor("#FFFFFF")))
    font = QFont("Arial", int(size * 0.45))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "E")
    painter.end()
    return QIcon(pixmap)


def get_app_icon() -> QIcon:
    """Return the application icon, loading and caching it on first call.

    All windows and dialogs should call this and pass the result to
    setWindowIcon() to ensure the icon shows in the title bar on Windows.
    """
    global _cached_icon
    if _cached_icon is not None:
        return _cached_icon

    ico_path = _find_ico_path()
    if ico_path:
        log.info("App icon: %s", ico_path)
        _cached_icon = QIcon(ico_path)
    else:
        log.warning("Icon file not found, using generated fallback")
        _cached_icon = _create_fallback_icon()

    return _cached_icon
