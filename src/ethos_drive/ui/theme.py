"""Modern UI theme for EthOS Drive — 2025+ design system.

Provides a centralized QSS stylesheet and color palette used by all windows.
Dark theme by default with clean surfaces, subtle borders, and accent colors.
"""

# ── Color Palette ──────────────────────────────────────────────
BG_PRIMARY = "#16161e"       # main window background
BG_SURFACE = "#1e1e2e"       # card / panel surface
BG_ELEVATED = "#262637"      # elevated surface (hover, active tab)
BG_INPUT = "#2a2a3d"         # input fields, search bars
BORDER = "#2e2e44"           # subtle borders
BORDER_FOCUS = "#6c63ff"     # focused input border

TEXT_PRIMARY = "#e4e4ef"     # main text
TEXT_SECONDARY = "#8888a8"   # secondary / muted text
TEXT_DISABLED = "#555570"    # disabled state

ACCENT = "#6c63ff"           # primary accent (buttons, links, progress)
ACCENT_HOVER = "#7b73ff"     # accent hover
ACCENT_ACTIVE = "#5b53e0"    # accent pressed
ACCENT_SUBTLE = "#6c63ff22"  # accent background tint

SUCCESS = "#4ade80"          # success / upload
WARNING = "#fbbf24"          # warning / conflict
ERROR = "#f87171"            # error / fail
INFO = "#60a5fa"             # info / download

SCROLLBAR = "#333350"
SCROLLBAR_HOVER = "#444468"

RADIUS = "8px"
RADIUS_SM = "6px"
RADIUS_LG = "12px"

FONT_FAMILY = "'Segoe UI', 'Inter', system-ui, sans-serif"
FONT_SIZE = "13px"
FONT_SIZE_SM = "11px"
FONT_SIZE_LG = "15px"
FONT_SIZE_XL = "18px"
FONT_SIZE_TITLE = "22px"


def app_stylesheet() -> str:
    """Return the complete application QSS stylesheet."""
    return f"""
    /* ── Global ─────────────────────────────────────── */
    QWidget {{
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE};
        color: {TEXT_PRIMARY};
        background: transparent;
    }}

    QMainWindow, QDialog {{
        background: {BG_PRIMARY};
    }}

    /* ── Labels ─────────────────────────────────────── */
    QLabel {{
        color: {TEXT_PRIMARY};
        background: transparent;
        padding: 0;
    }}

    QLabel[class="heading"] {{
        font-size: {FONT_SIZE_XL};
        font-weight: 600;
    }}

    QLabel[class="subtext"] {{
        font-size: {FONT_SIZE_SM};
        color: {TEXT_SECONDARY};
    }}

    /* ── Buttons ────────────────────────────────────── */
    QPushButton {{
        background: {BG_ELEVATED};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM};
        padding: 7px 18px;
        font-weight: 500;
        min-height: 20px;
    }}
    QPushButton:hover {{
        background: {BG_INPUT};
        border-color: {TEXT_SECONDARY};
    }}
    QPushButton:pressed {{
        background: {ACCENT_ACTIVE};
        border-color: {ACCENT};
    }}
    QPushButton:disabled {{
        color: {TEXT_DISABLED};
        background: {BG_SURFACE};
        border-color: {BORDER};
    }}

    QPushButton[class="primary"] {{
        background: {ACCENT};
        color: #fff;
        border: none;
        font-weight: 600;
    }}
    QPushButton[class="primary"]:hover {{
        background: {ACCENT_HOVER};
    }}
    QPushButton[class="primary"]:pressed {{
        background: {ACCENT_ACTIVE};
    }}

    QPushButton[class="flat"] {{
        background: transparent;
        border: none;
        color: {TEXT_SECONDARY};
        padding: 4px 10px;
    }}
    QPushButton[class="flat"]:hover {{
        color: {TEXT_PRIMARY};
        background: {ACCENT_SUBTLE};
    }}

    /* ── Tab Widget ─────────────────────────────────── */
    QTabWidget::pane {{
        background: {BG_PRIMARY};
        border: none;
    }}
    QTabBar {{
        background: {BG_PRIMARY};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {TEXT_SECONDARY};
        padding: 10px 22px;
        margin: 0 2px;
        border: none;
        border-bottom: 2px solid transparent;
        font-weight: 500;
        font-size: {FONT_SIZE};
    }}
    QTabBar::tab:hover {{
        color: {TEXT_PRIMARY};
        background: {ACCENT_SUBTLE};
        border-bottom: 2px solid {TEXT_SECONDARY};
    }}
    QTabBar::tab:selected {{
        color: {ACCENT};
        border-bottom: 2px solid {ACCENT};
        font-weight: 600;
    }}

    /* ── Scroll Areas ───────────────────────────────── */
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {SCROLLBAR};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {SCROLLBAR_HOVER};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
    }}
    QScrollBar::handle:horizontal {{
        background: {SCROLLBAR};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {SCROLLBAR_HOVER};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* ── Input fields ───────────────────────────────── */
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background: {BG_INPUT};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM};
        padding: 7px 10px;
        selection-background-color: {ACCENT};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border-color: {BORDER_FOCUS};
    }}

    QComboBox {{
        background: {BG_INPUT};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM};
        padding: 6px 10px;
        min-height: 20px;
    }}
    QComboBox:hover {{
        border-color: {TEXT_SECONDARY};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background: {BG_ELEVATED};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT};
    }}

    QSpinBox {{
        background: {BG_INPUT};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM};
        padding: 5px 8px;
    }}

    /* ── Check / Radio ──────────────────────────────── */
    QCheckBox, QRadioButton {{
        color: {TEXT_PRIMARY};
        spacing: 8px;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 18px; height: 18px;
        border: 2px solid {TEXT_SECONDARY};
        border-radius: 4px;
        background: {BG_INPUT};
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}
    QRadioButton::indicator {{
        border-radius: 9px;
    }}
    QRadioButton::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}

    /* ── Progress Bar ───────────────────────────────── */
    QProgressBar {{
        background: {BG_INPUT};
        border: none;
        border-radius: 4px;
        height: 6px;
        text-align: center;
        font-size: 0;
    }}
    QProgressBar::chunk {{
        background: {ACCENT};
        border-radius: 4px;
    }}

    /* ── Group Box ──────────────────────────────────── */
    QGroupBox {{
        background: {BG_SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
        margin-top: 12px;
        padding: 16px 12px 12px 12px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 14px;
        padding: 0 6px;
        color: {TEXT_SECONDARY};
    }}

    /* ── Tooltips ───────────────────────────────────── */
    QToolTip {{
        background: {BG_ELEVATED};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 6px 10px;
    }}

    /* ── Menu ───────────────────────────────────────── */
    QMenu {{
        background: {BG_ELEVATED};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM};
        padding: 4px 0;
    }}
    QMenu::item {{
        padding: 8px 28px 8px 16px;
    }}
    QMenu::item:selected {{
        background: {ACCENT_SUBTLE};
        color: {ACCENT};
    }}
    QMenu::separator {{
        height: 1px;
        background: {BORDER};
        margin: 4px 10px;
    }}

    /* ── Frame / Separator ──────────────────────────── */
    QFrame[frameShape="4"], QFrame[frameShape="5"] {{
        color: {BORDER};
    }}
    """


def card_style() -> str:
    """Return QSS for a card-like container widget."""
    return f"""
        background: {BG_SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
    """


def status_dot_style(status: str) -> str:
    """Return color for a status dot."""
    colors = {
        "idle": SUCCESS,
        "syncing": ACCENT,
        "paused": WARNING,
        "error": ERROR,
        "offline": TEXT_DISABLED,
    }
    return colors.get(status, TEXT_DISABLED)


def format_size(nbytes: int) -> str:
    """Human-readable file size."""
    if nbytes < 1024:
        return f"{nbytes} B"
    for unit in ("KB", "MB", "GB", "TB"):
        nbytes /= 1024.0
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
    return f"{nbytes:.1f} PB"


def format_speed(bps: float) -> str:
    """Human-readable transfer speed."""
    if bps <= 0:
        return "—"
    return format_size(int(bps)) + "/s"


def format_eta(seconds: float) -> str:
    """Human-readable ETA."""
    if seconds <= 0:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m"


def time_ago(timestamp: float) -> str:
    """Human-readable time-ago string."""
    import time
    diff = time.time() - timestamp
    if diff < 60:
        return "just now"
    if diff < 3600:
        m = int(diff / 60)
        return f"{m}m ago"
    if diff < 86400:
        h = int(diff / 3600)
        return f"{h}h ago"
    d = int(diff / 86400)
    return f"{d}d ago"
