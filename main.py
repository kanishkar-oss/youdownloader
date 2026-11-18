"""Entry point for YouDownloader (Windows and macOS).

From source: run.bat / run.sh, double-click YouDownloader.pyw (Windows), or the
shortcut made by install_shortcut.bat. Packaged: PyInstaller builds this into
YouDownloader.exe / YouDownloader.app (see packaging/).
"""
import os
import sys
import traceback


def _ensure_streams() -> None:
    """pythonw / a windowed app has no console: sys.stdout/stderr are None and
    any print (yt-dlp writes progress there) would crash. Send them to a null
    device instead."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _show_fatal(message: str) -> None:
    """Surface a startup crash even when there's no console to print to."""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "YouDownloader failed to start", 0x10)
            return
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("YouDownloader failed to start", message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    _ensure_streams()
    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)

    from src.utils import paths, winsys
    # Relative paths given on the command line mean "relative to where I ran it".
    argv = [os.path.abspath(a) if i and sys.argv[i - 1] == "--self-test" else a
            for i, a in enumerate(sys.argv)]
    # Never run with the working directory inside the (signed, replaceable)
    # app bundle: nothing may be written there.
    os.chdir(os.path.expanduser("~") if paths.FROZEN else paths.resource_root())
    # Bundled ffmpeg / ffprobe / deno (packaged app), ~/.deno/bin, Homebrew.
    paths.setup_tool_path()

    if "--wait-for-pid" in argv:  # a restart: let the old copy finish quitting first
        try:
            winsys.wait_for_exit(int(argv[argv.index("--wait-for-pid") + 1]))
        except (IndexError, ValueError):
            pass

    # Packaged app: use a newer yt-dlp downloaded since this build, if any.
    # Must run before anything imports yt_dlp.
    from src.utils import ytdlp_override
    ytdlp_override.activate()

    if "--self-test" in argv:
        from src.selftest import run
        return run(argv)

    if "--update-ytdlp" in argv:  # support: fetch a newer yt-dlp without opening the window
        ok, msg, _new = ytdlp_override.install()
        print(msg)
        return 0 if ok else 1

    if paths.IS_WINDOWS:
        try:
            # Own taskbar identity, so Windows shows our icon rather than pythonw's.
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YouDownloader.App")
        except Exception:
            pass

    if not winsys.acquire_single_instance():
        # Already open: bring that window forward instead of starting a second
        # copy (two instances would fight over the queue file).
        winsys.focus_existing_window()
        return 0

    try:
        from src.app import YouDownloaderApp
        app = YouDownloaderApp()
        app.mainloop()
        if getattr(app, "exit_for_update", False):
            # The installer / swap script is waiting for this process to end.
            # State is saved; don't wait on any lingering worker threads.
            import logging
            logging.shutdown()
            os._exit(0)
        return 0
    except Exception:
        details = traceback.format_exc()
        try:
            from src.utils.logger import get_logger
            get_logger().critical(f"Fatal error:\n{details}")
        except Exception:
            pass
        log_file = os.path.join(paths.log_dir(), "youdownloader.log")
        _show_fatal(f"{details[-1500:]}\n\nDetails are in {log_file}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
