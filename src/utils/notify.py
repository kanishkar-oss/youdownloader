"""Desktop notifications (fire and forget, never raises).

- Windows: a toast through Windows PowerShell's WinRT bridge, under the app's
  AppUserModelID ("YouDownloader.App", set on the installer's Start Menu
  shortcut), so it shows with the app's name and icon. From source (no such
  shortcut) Windows may drop it silently; the taskbar flash still happens.
- macOS: Notification Center through osascript.
"""
import base64
import os
import subprocess
import sys
import threading

APP_ID = "YouDownloader.App"

_TOAST_PS = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$t = [System.Security.SecurityElement]::Escape($env:YD_TOAST_TITLE)
$b = [System.Security.SecurityElement]::Escape($env:YD_TOAST_BODY)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>")
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:YD_TOAST_APPID).Show($toast)
"""

_MAC_SCRIPT = ["on run argv", "display notification (item 2 of argv) with title (item 1 of argv)", "end run"]


def command(title: str, body: str):
    """(argv, extra env) for this platform, or None if unsupported."""
    if sys.platform == "win32":
        encoded = base64.b64encode(_TOAST_PS.encode("utf-16-le")).decode("ascii")
        return (["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                 "-EncodedCommand", encoded],
                {"YD_TOAST_TITLE": title, "YD_TOAST_BODY": body, "YD_TOAST_APPID": APP_ID})
    if sys.platform == "darwin":
        argv = ["/usr/bin/osascript"]
        for line in _MAC_SCRIPT:
            argv += ["-e", line]
        return argv + [title, body], {}
    return None


def _send(title: str, body: str) -> None:
    cmd = command(title, body)
    if not cmd:
        return
    argv, extra = cmd
    try:
        subprocess.run(argv, env={**os.environ, **extra}, capture_output=True, timeout=20,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass


def notify(title: str, body: str) -> None:
    threading.Thread(target=_send, args=(title, body), daemon=True).start()
