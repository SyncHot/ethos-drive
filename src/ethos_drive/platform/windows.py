"""Windows-specific integration — auto-start, virtual drive, notifications, shell."""

import logging
import os
import subprocess
import sys

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


# ─── Explorer Quick Access / Navigation Pane shortcut ──────────
# Like OneDrive/Dropbox: shows "EthOS Drive" with icon in the Explorer
# sidebar (navigation pane) — no drive letter needed.

# Fixed CLSID for our shell folder — generated once, never changes.
_CLSID = "{7B3A8E2D-1F4C-4A9B-B5D6-8E2F3C4A5B6D}"


def add_explorer_shortcut(folder_path: str) -> bool:
    """Register EthOS Drive as a navigation pane entry in Windows Explorer.

    Creates a CLSID Shell Folder that appears in the Explorer sidebar
    (like OneDrive, Dropbox, Google Drive) with our icon.
    Persists across reboots — no subst or drive letter needed.
    Returns True on success.
    """
    if os.name != "nt":
        return False

    folder_path = os.path.abspath(folder_path)
    os.makedirs(folder_path, exist_ok=True)

    try:
        import winreg
        icon_path = _find_icon_path()

        # 1. Register the CLSID under HKCU\Software\Classes\CLSID\{...}
        clsid_key_path = rf"Software\Classes\CLSID\{_CLSID}"
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, clsid_key_path)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "EthOS Drive")
        # SortOrderIndex: 0x42 puts it near OneDrive in nav pane
        winreg.SetValueEx(key, "SortOrderIndex", 0, winreg.REG_DWORD, 0x42)
        winreg.SetValueEx(key, "System.IsPinnedToNameSpaceTree", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)

        # 2. DefaultIcon
        if icon_path:
            icon_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{clsid_key_path}\DefaultIcon")
            winreg.SetValueEx(icon_key, "", 0, winreg.REG_SZ, icon_path)
            winreg.CloseKey(icon_key)

        # 3. InProcServer32 — marks as shell folder
        ips_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{clsid_key_path}\InProcServer32")
        winreg.SetValueEx(ips_key, "", 0, winreg.REG_EXPAND_SZ, r"%systemroot%\system32\shell32.dll")
        winreg.CloseKey(ips_key)

        # 4. ShellFolder flags
        sf_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{clsid_key_path}\ShellFolder")
        # FolderValueFlags: browse into folder, show in nav pane
        winreg.SetValueEx(sf_key, "FolderValueFlags", 0, winreg.REG_DWORD, 0x28)
        # Attributes: folder | filesystem | hassubfolder
        winreg.SetValueEx(sf_key, "Attributes", 0, winreg.REG_DWORD, 0xF080004D)
        winreg.CloseKey(sf_key)

        # 5. Instance\InitPropertyBag — point to our sync folder
        ipb_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                    rf"{clsid_key_path}\Instance")
        winreg.SetValueEx(ipb_key, "CLSID", 0, winreg.REG_SZ,
                          "{0E5AAE11-A475-4c5b-AB00-C66DE400274E}")
        winreg.CloseKey(ipb_key)

        bag_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                    rf"{clsid_key_path}\Instance\InitPropertyBag")
        winreg.SetValueEx(bag_key, "Attributes", 0, winreg.REG_DWORD, 0x11)
        winreg.SetValueEx(bag_key, "TargetFolderPath", 0, winreg.REG_EXPAND_SZ, folder_path)
        winreg.CloseKey(bag_key)

        # 6. Register in Explorer's namespace to show in navigation pane
        ns_key_path = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\Desktop\NameSpace\{_CLSID}"
        ns_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, ns_key_path)
        winreg.SetValueEx(ns_key, "", 0, winreg.REG_SZ, "EthOS Drive")
        winreg.CloseKey(ns_key)

        # 7. Hide from Desktop (only show in nav pane, not on desktop)
        hide_key_path = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel"
        hide_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, hide_key_path)
        winreg.SetValueEx(hide_key, _CLSID, 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(hide_key)

        _notify_explorer_refresh()
        log.info("Explorer shortcut added: EthOS Drive -> %s", folder_path)
        return True
    except Exception as e:
        log.error("Failed to add Explorer shortcut: %s", e)
        return False


def remove_explorer_shortcut():
    """Remove EthOS Drive from Explorer navigation pane."""
    if os.name != "nt":
        return

    try:
        import winreg

        # Remove namespace registration
        try:
            winreg.DeleteKey(
                winreg.HKEY_CURRENT_USER,
                rf"Software\Microsoft\Windows\CurrentVersion\Explorer\Desktop\NameSpace\{_CLSID}",
            )
        except Exception:
            pass

        # Remove hide-from-desktop entry
        try:
            hide_path = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel"
            hide_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, hide_path, 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(hide_key, _CLSID)
            winreg.CloseKey(hide_key)
        except Exception:
            pass

        # Remove CLSID tree (deepest first)
        clsid_base = rf"Software\Classes\CLSID\{_CLSID}"
        for sub in [
            r"\Instance\InitPropertyBag",
            r"\Instance",
            r"\ShellFolder",
            r"\InProcServer32",
            r"\DefaultIcon",
            "",
        ]:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, clsid_base + sub)
            except Exception:
                pass

        # Clean up legacy subst drive mapping if present
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, "EthOS Drive Map")
            winreg.CloseKey(key)
        except Exception:
            pass

        _notify_explorer_refresh()
        log.info("Explorer shortcut removed")
    except Exception as e:
        log.debug("Shortcut removal: %s", e)


def is_explorer_shortcut_installed() -> bool:
    """Check if the EthOS Drive shortcut is in Explorer nav pane."""
    if os.name != "nt":
        return False
    try:
        import winreg
        winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Microsoft\Windows\CurrentVersion\Explorer\Desktop\NameSpace\{_CLSID}",
            0, winreg.KEY_READ,
        )
        return True
    except Exception:
        return False


def _find_icon_path() -> str:
    """Find the .ico file path (works frozen and dev)."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        candidates = [
            os.path.join(base, "resources", "icons", "ethos-drive.ico"),
            os.path.join(base, "_internal", "resources", "icons", "ethos-drive.ico"),
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
    """Notify Explorer to refresh — picks up registry changes."""
    try:
        import ctypes
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
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
