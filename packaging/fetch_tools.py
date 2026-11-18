"""Download the command-line tools bundled into the packaged app.

    python packaging/fetch_tools.py [--out build/tools/bin]

Puts ffmpeg, ffprobe and deno for *this* OS / CPU into the output folder; the
PyInstaller spec copies them into the app's bin/ folder, and main.py puts that
folder first on PATH. Every archive is checked against the SHA-256 its
publisher posts next to it before anything is extracted.

Sources (all official / widely used static builds):
    Windows ffmpeg + ffprobe  github.com/yt-dlp/FFmpeg-Builds (win64 GPL)
    macOS   ffmpeg + ffprobe  ffmpeg.martin-riedl.de (static, arm64 / amd64)
    deno                      github.com/denoland/deno releases
"""
import argparse
import hashlib
import os
import platform
import re
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "YouDownloader-build"}

YTDLP_FFMPEG = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
RIEDL = "https://ffmpeg.martin-riedl.de"
DENO = "https://github.com/denoland/deno/releases/latest/download/"


def _open(url: str, timeout: int = 120):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)


def _text(url: str) -> str:
    with _open(url, 60) as r:
        return r.read().decode("utf-8", "replace")


def _sha_from(text: str, filename: str = "") -> str:
    """First 64-hex token on a line naming `filename`, else anywhere (some
    publishers post just the hash, or PowerShell's 'Hash : ...' format)."""
    lines = text.splitlines()
    named = [ln for ln in lines if filename and filename in ln]
    for ln in named + lines:
        m = re.search(r"\b([0-9a-fA-F]{64})\b", ln)
        if m:
            return m.group(1).lower()
    raise SystemExit(f"No SHA-256 found for {filename or 'download'}")


def _download(url: str, dest: str, expected_sha: str) -> None:
    print(f"  downloading {url}")
    sha = hashlib.sha256()
    for attempt in range(3):
        try:
            with _open(url) as r, open(dest, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
            break
        except OSError as e:
            if attempt == 2:
                raise
            print(f"  retrying after error: {e}")
            sha = hashlib.sha256()
    if sha.hexdigest() != expected_sha:
        raise SystemExit(f"Checksum mismatch for {url}\n  expected {expected_sha}\n  got      {sha.hexdigest()}")
    print(f"  sha256 ok ({os.path.getsize(dest) // (1 << 20)} MB)")


def _extract(zip_path: str, wanted: dict, out_dir: str) -> None:
    """Copy archive members whose basename is a key in `wanted` to out_dir/value."""
    found = set()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            base = os.path.basename(info.filename)
            if base in wanted and not info.is_dir():
                target = os.path.join(out_dir, wanted[base])
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                found.add(base)
    missing = set(wanted) - found
    if missing:
        raise SystemExit(f"{os.path.basename(zip_path)} is missing {', '.join(sorted(missing))}")


def _resolve_redirect(url: str) -> str:
    with _open(url, 60) as r:
        return r.geturl()


def fetch(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="yd-tools-")
    machine = platform.machine().lower()
    try:
        if sys.platform == "win32":
            name = "ffmpeg-master-latest-win64-gpl.zip"
            sha = _sha_from(_text(YTDLP_FFMPEG + "checksums.sha256"), name)
            _download(YTDLP_FFMPEG + name, os.path.join(tmp, name), sha)
            _extract(os.path.join(tmp, name), {"ffmpeg.exe": "ffmpeg.exe", "ffprobe.exe": "ffprobe.exe"}, out_dir)
            deno = "deno-x86_64-pc-windows-msvc.zip"
            exe = {"deno.exe": "deno.exe"}
        elif sys.platform == "darwin":
            arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
            for tool in ("ffmpeg", "ffprobe"):
                url = _resolve_redirect(f"{RIEDL}/redirect/latest/macos/{arch}/release/{tool}.zip")
                sha = _sha_from(_text(url + ".sha256"))
                dest = os.path.join(tmp, f"{tool}.zip")
                _download(url, dest, sha)
                _extract(dest, {tool: tool}, out_dir)
            deno = "deno-aarch64-apple-darwin.zip" if arch == "arm64" else "deno-x86_64-apple-darwin.zip"
            exe = {"deno": "deno"}
        else:
            raise SystemExit("Bundled tools are only fetched for Windows and macOS builds.")

        sha = _sha_from(_text(DENO + deno + ".sha256sum"), deno)
        _download(DENO + deno, os.path.join(tmp, deno), sha)
        _extract(os.path.join(tmp, deno), exe, out_dir)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"Tools ready in {out_dir}: {', '.join(sorted(os.listdir(out_dir)))}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "tools", "bin"))
    fetch(os.path.abspath(ap.parse_args().out))
