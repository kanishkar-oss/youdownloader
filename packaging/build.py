"""Build the installable app for the OS you run this on.

    python packaging/build.py [--skip-tools] [--skip-installer]

Windows → dist/release/YouDownloader-<ver>-windows-setup.exe  (Inno Setup)
macOS   → dist/release/YouDownloader-<ver>-mac-<arch>.dmg      (drag to Applications)
          dist/release/YouDownloader-<ver>-mac-<arch>.zip      (used by the in-app updater)

GitHub Actions runs this on Windows and Apple Silicon runners for every
release tag (.github/workflows/release.yml). Needs: pip install -r
requirements.txt -r requirements-build.txt, plus Inno Setup 6 on Windows.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.version import APP_NAME, __version__  # noqa: E402

DIST = os.path.join(ROOT, "dist")
RELEASE = os.path.join(DIST, "release")
TOOLS = os.path.join(ROOT, "build", "tools", "bin")


def run(cmd, **kw):
    print("+", " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def ensure_tools() -> None:
    exe = ".exe" if sys.platform == "win32" else ""
    if all(os.path.isfile(os.path.join(TOOLS, t + exe)) for t in ("ffmpeg", "ffprobe", "deno")):
        print(f"Using bundled tools in {TOOLS}")
        return
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import fetch_tools
    fetch_tools.fetch(TOOLS)


def write_build_info() -> None:
    """build/build_info.json, bundled at the app's resource root: what this
    build ships, read at startup without importing yt_dlp (see
    src/utils/ytdlp_override.py)."""
    import datetime
    import importlib.metadata as md
    import json
    info = {"app_version": __version__, "built": datetime.date.today().isoformat(),
            "yt_dlp": md.version("yt-dlp"), "yt_dlp_ejs": md.version("yt-dlp-ejs")}
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    with open(os.path.join(ROOT, "build", "build_info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    print(f"Build info: {info}")


def notices() -> None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import make_notices
    make_notices.build()


def pyinstaller() -> None:
    run([sys.executable, "-m", "PyInstaller", os.path.join(ROOT, "packaging", "YouDownloader.spec"),
         "--noconfirm", "--clean", "--distpath", DIST, "--workpath", os.path.join(ROOT, "build", "pyinstaller")],
        env={**os.environ, "YD_TOOLS_DIR": TOOLS})


def find_iscc():
    candidates = [os.environ.get("ISCC"), shutil.which("iscc"), shutil.which("ISCC")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            candidates.append(os.path.join(base, "Inno Setup 6", "ISCC.exe"))
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def windows_installer() -> None:
    iscc = find_iscc()
    if not iscc:
        raise SystemExit("Inno Setup 6 (ISCC.exe) not found. Install it from https://jrsoftware.org/isdl.php "
                         "or run with --skip-installer to only build dist/YouDownloader/.")
    run([iscc, f"/DAppVersion={__version__}", f"/DSourceDir={os.path.join(DIST, APP_NAME)}",
         f"/DOutputDir={RELEASE}", os.path.join(ROOT, "packaging", "windows", "installer.iss")])


# Mach-O (thin 32/64-bit, both byte orders) and universal ("fat") binaries.
_MACHO_MAGICS = {bytes.fromhex(h) for h in ("feedface", "feedfacf", "cefaedfe", "cffaedfe", "cafebabe")}


def mac_label() -> str:
    return "apple-silicon" if platform.machine().lower() in ("arm64", "aarch64") else "intel"


def mac_packages() -> None:
    app = os.path.join(DIST, f"{APP_NAME}.app")
    # Apple Silicon refuses to load native code that isn't signed. Some
    # packages ship libraries as data files (tkinterdnd2's tkdnd), which
    # PyInstaller and `codesign --deep` don't sign, so sign every Mach-O file
    # first, then the bundle. (Gatekeeper still warns: not notarized.)
    machos = []
    for dirpath, _dirs, files in os.walk(app):
        for name in files:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                continue
            with open(path, "rb") as f:
                magic = f.read(4)
            if magic in _MACHO_MAGICS:
                machos.append(path)
    print(f"Signing {len(machos)} native files")
    for path in sorted(machos, key=lambda p: -p.count(os.sep)):  # innermost first
        subprocess.run(["codesign", "--force", "--sign", "-", path], check=True, capture_output=True)
    run(["codesign", "--force", "--deep", "--sign", "-", app])
    base = os.path.join(RELEASE, f"{APP_NAME}-{__version__}-mac-{mac_label()}")
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, base + ".zip"])

    staging = os.path.join(ROOT, "build", "dmg")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    run(["ditto", app, os.path.join(staging, f"{APP_NAME}.app")])
    os.symlink("/Applications", os.path.join(staging, "Applications"))
    if os.path.exists(base + ".dmg"):
        os.remove(base + ".dmg")
    run(["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", staging, "-ov", "-format", "UDZO",
         base + ".dmg"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-tools", action="store_true", help="don't bundle ffmpeg/ffprobe/deno")
    ap.add_argument("--skip-installer", action="store_true", help="stop after PyInstaller")
    args = ap.parse_args()

    print(f"Building {APP_NAME} {__version__} for {sys.platform} ({platform.machine()})")
    if not args.skip_tools:
        ensure_tools()
    write_build_info()
    notices()
    pyinstaller()
    if args.skip_installer:
        return
    os.makedirs(RELEASE, exist_ok=True)
    if sys.platform == "win32":
        windows_installer()
    elif sys.platform == "darwin":
        mac_packages()
    else:
        raise SystemExit("Installers are built for Windows and macOS only.")
    print("\nDone:")
    for name in sorted(os.listdir(RELEASE)):
        size = os.path.getsize(os.path.join(RELEASE, name)) / (1 << 20)
        print(f"  dist/release/{name}  ({size:.0f} MB)")


if __name__ == "__main__":
    main()
