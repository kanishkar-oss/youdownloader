"""Smoke test for packaged builds (used by CI on every platform).

    YouDownloader --self-test report.txt [--download URL]

Checks the frozen app can import its dependencies, find and run the bundled
ffmpeg / ffprobe / deno, load the icon font and open Tk; with --download it
also downloads URL as MP4 into a temp folder (exercises yt-dlp + the JS solver
+ ffmpeg merging). Writes a report to the given file (windowed builds have no
console) and exits 0 on success, 1 on any failure.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import traceback


def run(argv) -> int:
    out_path = argv[argv.index("--self-test") + 1] if len(argv) > argv.index("--self-test") + 1 else None
    url = argv[argv.index("--download") + 1] if "--download" in argv else None
    lines, ok = [], True

    def check(name, fn):
        nonlocal ok
        try:
            lines.append(f"PASS {name}: {fn()}")
        except Exception as e:
            ok = False
            lines.append(f"FAIL {name}: {e}\n{traceback.format_exc()}")

    from src.utils import paths
    from src.version import __version__
    lines.append(f"YouDownloader {__version__} on {sys.platform} ({'packaged' if paths.FROZEN else 'source'})")
    lines.append(f"resources: {paths.resource_root()}")
    lines.append(f"config: {paths.config_dir()}  logs: {paths.log_dir()}")

    def tool(name, args):
        def fn():
            exe = shutil.which(name)
            if not exe:
                raise RuntimeError(f"{name} not on PATH")
            if paths.FROZEN and not os.path.normcase(exe).startswith(os.path.normcase(paths.bundled_bin_dir())):
                raise RuntimeError(f"{name} resolved outside the bundle: {exe}")
            r = subprocess.run([exe] + args, capture_output=True, text=True, timeout=60,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode != 0:
                raise RuntimeError(f"{exe} exited {r.returncode}: {r.stderr[-300:]}")
            return f"{exe} | {(r.stdout or r.stderr).splitlines()[0]}"
        return fn

    check("ffmpeg", tool("ffmpeg", ["-hide_banner", "-version"]))
    check("ffprobe", tool("ffprobe", ["-hide_banner", "-version"]))
    check("deno", tool("deno", ["--version"]))

    def imports():
        import customtkinter, yt_dlp, yt_dlp_ejs, PIL, requests  # noqa: F401
        from yt_dlp.version import __version__ as v
        return f"yt-dlp {v}, customtkinter {customtkinter.__version__}"
    check("imports", imports)

    def icon_font():
        from src.ui import icons
        if not icons.available():
            raise RuntimeError("no icon font")
        return icons._font_path()
    check("icons", icon_font)

    def tk():
        import customtkinter
        from src.ui.tokens import init_fonts
        root = customtkinter.CTk()
        root.withdraw()
        family = init_fonts(root)
        root.update()
        root.destroy()
        return f"Tk ok, font {family}"
    check("tk", tk)

    if url:
        def download():
            from src.downloader.engine import DownloadEngine
            folder = tempfile.mkdtemp(prefix="yd-selftest-")
            engine = DownloadEngine()
            if not engine.download(url=url, output_path=folder, format_mode="Video (MP4)", quality="720p",
                                   embed_metadata=True):
                raise RuntimeError("download returned False")
            files = [os.path.basename(f) for f in engine.downloaded_files]
            sizes = [os.path.getsize(f) for f in engine.downloaded_files if os.path.exists(f)]
            shutil.rmtree(folder, ignore_errors=True)
            return f"{files} {sizes}"
        check("download", download)

    lines.append("RESULT: " + ("OK" if ok else "FAILED"))
    report = "\n".join(lines)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report + "\n")
    try:
        print(report)
    except Exception:
        pass
    return 0 if ok else 1
