"""Windows-specific integration — auto-start, virtual drive, notifications, shell."""

import logging
import os
import subprocess
import sys
import string

log = logging.getLogger(__name__)


def set_auto_start(enabled: bool):
    """Enable or disable auto-start with Windows login via registry."""
    if os.name != "nt":
        return

    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)

        if enabled:
            if getattr(sys, "frozen", False):
                exe_path = f'"{sys.executable}" --minimized'
            else:
                exe_path = f'"{sys.executable}" -m ethos_drive --minimized'
            winreg.SetValueEx(key, "EthOS Drive", 0, winreg.REG_SZ, exe_path)
            log.info("Auto-start enabled: %s", exe_path)
        else:
            try:
                winreg.DeleteValue(key, "EthOS Drive")
                log.info("Auto-start disabled")
            except FileNotFoundError:
                pass

        winreg.CloseKey(key)
    except Exception as e:
        log.error("Failed to set auto-start: %s", e)


def is_auto_start_enabled() -> bool:
    """Check if auto-start is enabled."""
    if os.name != "nt":
        return False

    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, "EthOS Drive")
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def get_default_sync_folder() -> str:
    """Get the default sync folder path (e.g., C:\\Users\\<user>\\EthOS Drive)."""
    home = os.path.expanduser("~")
    return os.path.join(home, "EthOS Drive")


# ─── Virtual drive mapping ─────────────────────────────────────

def _get_used_drive_letters() -> set[str]:
    """Return set of drive letters currently in use (e.g. {'C', 'D'})."""
    used = set()
    if os.name != "nt":
        return used
    for letter in string.ascii_uppercase:
        if os.path.exists(f"{letter}:\\"):
            used.add(letter)
    return used


def _find_free_drive_letter(preferred: str = "E") -> str:
    """Find a free drive letter, preferring the given letter."""
    used = _get_used_drive_letters()
    preferred = preferred.upper()
    if preferred not in used:
        return preferred
    # Try E-Z, then D-B (skip A: floppy, C: system)
    for letter in "EFGHIJKLMNOPQRSTUVWXYZDB":
        if letter not in used:
            return letter
    return ""


def mount_virtual_drive(folder_path: str, drive_letter: str = "") -> str:
    """Map a local folder as a Windows drive letter using subst.
    Returns the drive letter used, or '' on failure.
    """
    if os.name != "nt":
        return ""

    folder_path = os.path.abspath(folder_path)
    os.makedirs(folder_path, exist_ok=True)

    if not drive_letter:
        drive_letter = _find_free_drive_letter("E")
    if not drive_letter:
        log.error("No free drive letter available")
        return ""

    drive_letter = drive_letter.upper()

    # Check if already mounted
    if os.path.exists(f"{drive_letter}:\\"):
        # Verify it points to our folder
        try:
            result = subprocess.run(
                ["subst"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if line.startswith(f"{drive_letter}:\\") and folder_path.lower() in line.lower():
                    log.info("Drive %s: already mapped to %s", drive_letter, folder_path)
                    return drive_letter
        except Exception:
            pass
        # In use by something else — find another letter
        drive_letter = _find_free_drive_letter()
        if not drive_letter:
            return ""

    try:
        subprocess.run(
            ["subst", f"{drive_letter}:", folder_path],
            check=True, capture_output=True, timeout=10,
        )
        log.info("Mounted %s as %s:", folder_path, drive_letter)

        # Set custom label — Explorer shows "Ethos (E:)"
        _set_drive_label(drive_letter, "Ethos")
        # Set drive icon from our .ico file
        _set_drive_icon(drive_letter)
        # Notify Explorer to refresh drive list
        _notify_explorer_refresh()

        return drive_letter
    except subprocess.CalledProcessError as e:
        log.error("subst failed: %s", e.stderr)
        return ""
    except Exception as e:
        log.error("Mount failed: %s", e)
        return ""


def unmount_virtual_drive(drive_letter: str):
    """Unmap a virtual drive."""
    if os.name != "nt" or not drive_letter:
        return
    try:
        subprocess.run(
            ["subst", f"{drive_letter}:", "/d"],
            check=True, capture_output=True, timeout=10,
        )
        _remove_drive_label(drive_letter)
        log.info("Unmounted drive %s:", drive_letter)
    except Exception as e:
        log.debug("Unmount %s: %s", drive_letter, e)


def _set_drive_label(letter: str, label: str):
    """Set a custom label for a drive in the registry (shows in Explorer)."""
    try:
        import winreg
        key_path = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\DriveIcons\{letter}\DefaultLabel"
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, label)
        winreg.CloseKey(key)
    except Exception as e:
        log.debug("Drive label failed: %s", e)


def _remove_drive_label(letter: str):
    """Remove custom drive label and icon."""
    try:
        import winreg
        base = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\DriveIcons\{letter}"
        for sub in ("DefaultLabel", "DefaultIcon"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{base}\\{sub}")
            except Exception:
                pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)
        except Exception:
            pass
    except Exception:
        pass


def _set_drive_icon(letter: str):
    """Set a custom icon for the drive in Explorer using the .ico file."""
    try:
        import winreg
        icon_path = _find_icon_path()
        if not icon_path:
            log.debug("No icon file found for drive %s", letter)
            return
        key_path = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\DriveIcons\{letter}\DefaultIcon"
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, icon_path)
        winreg.CloseKey(key)
        log.info("Drive icon set: %s -> %s", letter, icon_path)
    except Exception as e:
        log.debug("Drive icon failed: %s", e)


def _find_icon_path() -> str:
    """Find the .ico file path (works frozen and dev)."""
    # Frozen (PyInstaller --onefile or --onedir)
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        candidates = [
            os.path.join(base, "resources", "icons", "ethos-drive.ico"),
            os.path.join(base, "_internal", "resources", "icons", "ethos-drive.ico"),
            # PyInstaller --onefile extracts to temp — icon is next to exe
            sys.executable + ",0",  # use exe's embedded icon as fallback
        ]
        for c in candidates:
            if c.endswith(",0") or os.path.isfile(c):
                return c
    else:
        base = os.path.dirname(os.path.abspath(__file__))
        p = os.path.normpath(os.path.join(base, "..", "resources", "icons", "ethos-drive.ico"))
        if os.path.isfile(p):
            return p
    return ""


def _notify_explorer_refresh():
    """Tell Explorer to refresh drive list after registry changes."""
    try:
        import ctypes
        SHCNE_DRIVEADD = 0x00000100
        SHCNF_PATH = 0x0005
        ctypes.windll.shell32.SHChangeNotify(SHCNE_DRIVEADD, SHCNF_PATH, None, None)
    except Exception:
        pass


def setup_virtual_drive_on_boot(folder_path: str, drive_letter: str):
    """Ensure the virtual drive is re-created on login (subst doesn't persist reboots).
    Adds a RunOnce registry entry or uses the auto-start to handle it.
    """
    if os.name != "nt" or not drive_letter:
        return
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        cmd = f'subst {drive_letter}: "{os.path.abspath(folder_path)}"'
        winreg.SetValueEx(key, "EthOS Drive Map", 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        log.info("Virtual drive %s: will persist across reboots", drive_letter)
    except Exception as e:
        log.error("Failed to persist drive mapping: %s", e)


def remove_virtual_drive_on_boot():
    """Remove the persistent drive mapping."""
    if os.name != "nt":
        return
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, "EthOS Drive Map")
        winreg.CloseKey(key)
    except Exception:
        pass


# ─── Explorer context menu ─────────────────────────────────────

def add_to_explorer_context_menu():
    """Add 'Sync with EthOS' to Windows Explorer right-click context menu."""
    if os.name != "nt":
        return

    try:
        import winreg

        exe_path = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" -m ethos_drive'

        # Folder context menu
        key_path = r"Software\Classes\Directory\shell\EthOSDrive"
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Sync with EthOS Drive")
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, exe_path)
        winreg.CloseKey(key)

        cmd_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command")
        winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, f'{exe_path} --sync-folder "%1"')
        winreg.CloseKey(cmd_key)

        log.info("Explorer context menu added")
    except Exception as e:
        log.error("Failed to add context menu: %s", e)


def remove_explorer_context_menu():
    """Remove EthOS Drive from Explorer context menu."""
    if os.name != "nt":
        return

    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Classes\Directory\shell\EthOSDrive\command")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Classes\Directory\shell\EthOSDrive")
        log.info("Explorer context menu removed")
    except Exception as e:
        log.debug("Context menu removal: %s", e)


def show_windows_notification(title: str, message: str, icon_path: str = None):
    """Show a Windows 10/11 toast notification."""
    if os.name != "nt":
        return
    try:
        pass  # Handled by SystemTray's showMessage()
    except Exception as e:
        log.debug("Notification failed: %s", e)
