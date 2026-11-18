"""Small OS integrations: single instance, taskbar flash / dock bounce,
reveal/open files, native window chrome. Windows and macOS.

Everything degrades to a no-op if an OS call fails.
"""
import os
import subprocess
import sys

_IS_WINDOWS = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"
_MUTEX_NAME = "Local\\YouDownloaderSingleInstance"
_ERROR_ALREADY_EXISTS = 183
_mutex_handle = None  # kept alive for the life of the process
_lock_file = None     # POSIX: flock()ed file, held for the life of the process


def acquire_single_instance() -> bool:
    """True if this is the only running instance.

    Windows: a named mutex. macOS/Linux: an exclusive flock on a file in the
    app-data folder (released automatically when the process exits).
    """
    global _mutex_handle, _lock_file
    if _IS_WINDOWS:
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            _mutex_handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
            return kernel32.GetLastError() != _ERROR_ALREADY_EXISTS
        except Exception:
            return True
    try:
        import fcntl
        from src.utils import paths
        os.makedirs(paths.user_data_dir(), exist_ok=True)
        _lock_file = open(os.path.join(paths.user_data_dir(), ".instance.lock"), "w")
        fcntl.flock(_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    except Exception:
        return True


def focus_existing_window(title: str = "YouDownloader") -> bool:
    """Bring an already-running instance's window to the front."""
    if _IS_MAC:
        # A second copy run from source; the .app is single-instance via
        # LaunchServices already. Activating by name is best effort.
        try:
            subprocess.Popen(["osascript", "-e", f'tell application "{title}" to activate'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False
    if not _IS_WINDOWS:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def flash_taskbar(tk_window) -> None:
    """Draw attention when a download finishes in the background: flash the
    taskbar button (Windows) or bounce the Dock icon (macOS)."""
    try:
        if tk_window.focus_displayof() is not None:
            return  # already in front; nothing to draw attention to
    except Exception:
        pass
    if _IS_MAC:
        try:
            tk_window.wm_attributes("-notify", 1)  # Tk/aqua: bounce the Dock icon
        except Exception:
            pass
        return
    if not _IS_WINDOWS:
        return
    try:
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND),
                        ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT),
                        ("dwTimeout", wintypes.DWORD)]

        hwnd = ctypes.windll.user32.GetParent(tk_window.winfo_id()) or tk_window.winfo_id()
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x3 | 0xC, 0, 0)  # ALL | TIMERNOFG
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass


def reveal_file(path: str) -> None:
    """Show the file selected in Explorer / Finder (or open its folder)."""
    if os.path.isfile(path) and _IS_WINDOWS:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif os.path.exists(path) and _IS_MAC:
        subprocess.Popen(["open", "-R", path])
    else:
        open_path(path if os.path.isdir(path) else os.path.dirname(path))


def open_path(path: str) -> None:
    """Open a file with its default app, or a folder in Explorer / Finder."""
    if _IS_WINDOWS:
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["open" if _IS_MAC else "xdg-open", path])


def open_url(url: str) -> None:
    import webbrowser
    webbrowser.open(url)


def _hex_to_colorref(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def style_window(tk_window, caption: str = None, text: str = None, border: str = None,
                 rounded: bool = False) -> None:
    """Native chrome to match the dark app.

    Windows 11: dark title bar tinted to the app background, plus optional
    rounded corners (popup menus). macOS: force the dark (aqua) appearance so
    the title bar is dark even when the system is in light mode.
    """
    if _IS_MAC:
        try:
            tk_window.wm_attributes("-appearance", "darkaqua")
        except Exception:
            pass
        return
    if not _IS_WINDOWS:
        return
    try:
        import ctypes
        from ctypes import wintypes
        tk_window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(tk_window.winfo_id()) or tk_window.winfo_id()
        dwm = ctypes.windll.dwmapi

        def setattr_(attr, value):
            v = wintypes.DWORD(value)
            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))

        setattr_(20, 1)  # DWMWA_USE_IMMERSIVE_DARK_MODE
        if caption:
            setattr_(35, _hex_to_colorref(caption))   # DWMWA_CAPTION_COLOR
        if text:
            setattr_(36, _hex_to_colorref(text))      # DWMWA_TEXT_COLOR
        if border:
            setattr_(34, _hex_to_colorref(border))    # DWMWA_BORDER_COLOR
        if rounded:
            setattr_(33, 2)                           # DWMWA_WINDOW_CORNER_PREFERENCE = ROUND
    except Exception:
        pass


def context_menu_events():
    """Tk event names for a right-click: Button-3 on Windows; on macOS the
    secondary button is Button-2 in Tk 8.6 (Button-3 in Tk 9), plus Control-click."""
    if _IS_MAC:
        return ("<Button-2>", "<Button-3>", "<Control-Button-1>")
    return ("<Button-3>",)
