# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for YouDownloader (Windows .exe folder, macOS .app).

Build with `python packaging/build.py` (fetches tools, runs this, then makes
the installer / dmg). Bundled tools come from build/tools/bin (override with
YD_TOOLS_DIR); without them the app falls back to whatever is on PATH.
"""
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
from src.version import APP_NAME, BUNDLE_ID, __version__  # noqa: E402

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
TOOLS = os.environ.get("YD_TOOLS_DIR", os.path.join(ROOT, "build", "tools", "bin"))

datas = [
    (os.path.join(ROOT, "assets", "fonts"), os.path.join("assets", "fonts")),
    (os.path.join(ROOT, "assets", "youdownloader.ico"), "assets"),
    (os.path.join(ROOT, "assets", "icon.png"), "assets"),
    (os.path.join(ROOT, "assets", "logo.png"), "assets"),
]
# License notices + what this build ships (written by packaging/build.py).
NOTICES = os.path.join(ROOT, "build", "notices")
for name in ("THIRD-PARTY-NOTICES.txt", "LICENSE.txt"):
    if os.path.isfile(os.path.join(NOTICES, name)):
        datas.append((os.path.join(NOTICES, name), "licenses"))
    else:
        print(f"WARNING: {name} missing; run packaging/make_notices.py")
BUILD_INFO = os.path.join(ROOT, "build", "build_info.json")
if os.path.isfile(BUILD_INFO):
    datas.append((BUILD_INFO, "."))
datas += collect_data_files("customtkinter")
datas += collect_data_files("yt_dlp_ejs")   # the bundled JS challenge solver
datas += collect_data_files("certifi")

binaries = []
for tool in ("ffmpeg", "ffprobe", "deno"):
    path = os.path.join(TOOLS, tool + (".exe" if IS_WIN else ""))
    if os.path.isfile(path):
        binaries.append((path, "bin"))
    else:
        print(f"WARNING: {path} not found; the app will rely on {tool} being installed")

hiddenimports = collect_submodules("yt_dlp_ejs") + ["darkdetect"]

# The whole standard library, not just what today's yt-dlp imports: the app
# downloads newer yt-dlp versions by itself (src/utils/ytdlp_override.py), and
# those may use modules this build's yt-dlp didn't. Costs a few MB.
from src.stdlib_list import stdlib_names  # noqa: E402
_stdlib = stdlib_names()
hiddenimports += _stdlib
for _pkg in _stdlib:
    if _pkg in ("email", "xml", "json", "http", "urllib", "html", "concurrent", "asyncio", "ctypes",
                "sqlite3", "logging", "importlib", "encodings", "zoneinfo", "wsgiref", "xmlrpc", "dbm",
                "collections", "multiprocessing", "curses", "unittest"):
        hiddenimports += collect_submodules(_pkg, filter=lambda n: ".test" not in n)
print(f"Bundling {len(_stdlib)} standard library modules")

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "unittest.mock", "numpy", "pandas", "matplotlib", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if IS_WIN:
    # Windows file properties (Explorer → Properties → Details).
    from PyInstaller.utils.win32.versioninfo import (VSVersionInfo, FixedFileInfo, StringFileInfo,
                                                     StringTable, StringStruct, VarFileInfo, VarStruct)
    nums = tuple(int(p) for p in (__version__.split(".") + ["0", "0", "0"])[:4])
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", APP_NAME),
                StringStruct("FileDescription", "YouDownloader - YouTube video and audio downloader"),
                StringStruct("FileVersion", __version__),
                StringStruct("ProductName", APP_NAME),
                StringStruct("ProductVersion", __version__),
                StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
else:
    version_info = None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    icon=os.path.join(ROOT, "assets", "youdownloader.icns" if IS_MAC else "youdownloader.ico"),
    version=version_info,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)

def _min_macos(binary_paths, floor=(11, 0)):
    """Highest minimum-macOS of the bundled binaries (from otool's
    LC_BUILD_VERSION / LC_VERSION_MIN_MACOSX), so Info.plist doesn't promise
    support for a macOS the bundled ffmpeg/deno can't run on."""
    import re
    import subprocess
    best = floor
    for path in binary_paths:
        try:
            out = subprocess.run(["otool", "-l", path], capture_output=True, text=True, timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        found = re.findall(r"minos (\d+)\.(\d+)", out)
        found += re.findall(r"LC_VERSION_MIN_MACOSX\n.*\n\s*version (\d+)\.(\d+)", out)
        for major, minor in found:
            best = max(best, (int(major), int(minor)))
    print(f"Minimum macOS for this build: {best[0]}.{best[1]}")
    return f"{best[0]}.{best[1]}"


if IS_MAC:
    MIN_MACOS = _min_macos([src for _dest, src, kind in a.binaries if kind in ("BINARY", "EXTENSION")])
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=os.path.join(ROOT, "assets", "youdownloader.icns"),
        bundle_identifier=BUNDLE_ID,
        version=__version__,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "LSMinimumSystemVersion": MIN_MACOS,
            "NSHighResolutionCapable": True,
            # Let the dark title bar follow Tk's dark appearance.
            "NSRequiresAquaSystemAppearance": False,
            "NSDownloadsFolderUsageDescription": "YouDownloader saves your videos and audio to Downloads.",
            "NSDesktopFolderUsageDescription": "YouDownloader saves downloads to a folder you choose.",
            "NSDocumentsFolderUsageDescription": "YouDownloader saves downloads to a folder you choose.",
        },
    )
