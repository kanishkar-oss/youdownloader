"""Write the license notices shipped inside the packaged app.

    python packaging/make_notices.py        (packaging/build.py runs this)

Produces build/notices/THIRD-PARTY-NOTICES.txt (versions and full license
texts of everything bundled: Python and its packages, Tcl/Tk, FFmpeg/ffprobe,
Deno, Material Icons) and build/notices/LICENSE.txt (the app's own license).
Package versions come from the build environment; tool versions and FFmpeg's
build configuration from running the bundled binaries, so the notices always
match what ships.
"""
import datetime
import importlib.metadata as md
import os
import re
import subprocess
import sys
import sysconfig
import tkinter

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.version import APP_NAME, GITHUB_REPO, __version__  # noqa: E402

TOOLS = os.environ.get("YD_TOOLS_DIR", os.path.join(ROOT, "build", "tools", "bin"))
OUT = os.path.join(ROOT, "build", "notices")
LICENSES = os.path.join(ROOT, "packaging", "licenses")
ISSUES = f"https://github.com/{GITHUB_REPO}/issues"
RULE = "=" * 78


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().strip()


def _top_requirements():
    with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                yield Requirement(line)


def bundled_distributions():
    """The runtime requirements and everything they pull in (no build tools)."""
    seen, order = {}, []
    queue = [(r.name, set(r.extras)) for r in _top_requirements()]
    while queue:
        name, extras = queue.pop(0)
        key = canonicalize_name(name)
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        if key in seen and extras <= seen[key]:
            continue
        if key not in seen:
            order.append(dist)
        seen[key] = seen.get(key, set()) | extras
        for spec in dist.requires or []:
            req = Requirement(spec)
            envs = [{"extra": e} for e in (extras or {""})]
            if req.marker and not any(req.marker.evaluate(env) for env in envs):
                continue
            queue.append((req.name, set(req.extras)))
    return sorted(order, key=lambda d: d.metadata["Name"].lower())


def _license_of(dist) -> str:
    m = dist.metadata
    lic = m.get("License-Expression") or ""
    if not lic:
        raw = (m.get("License") or "").strip()
        lic = raw if raw and "\n" not in raw and len(raw) < 80 else ""
    if not lic:
        cls = [c.split("::")[-1].strip() for c in m.get_all("Classifier") or [] if c.startswith("License ::")]
        lic = ", ".join(cls)
    return lic or "see license text below"


def _homepage(dist) -> str:
    m = dist.metadata
    urls = [u.split(",", 1)[1].strip() for u in m.get_all("Project-URL") or [] if "," in u]
    return m.get("Home-page") or next((u for u in urls if "github" in u or "gitlab" in u), urls[0] if urls else "")


def _license_texts(dist):
    for f in dist.files or []:
        name = os.path.basename(str(f)).upper()
        if re.match(r"(LICEN[CS]E|COPYING|NOTICE)", name):
            path = dist.locate_file(f)
            if os.path.isfile(path):
                yield str(f).split("/")[-1], _read(path)


def _run(exe, *args) -> str:
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (r.stdout or r.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _tool(name):
    path = os.path.join(TOOLS, name + (".exe" if sys.platform == "win32" else ""))
    return path if os.path.isfile(path) else None


def ffmpeg_section():
    exe = _tool("ffmpeg")
    if not exe:
        return None
    out = _run(exe, "-hide_banner", "-version")
    first = out.splitlines()[0] if out else "ffmpeg (version unknown)"
    version = first.split(" ")[2] if first.startswith("ffmpeg version ") else "unknown"
    config = next((ln.split(":", 1)[1].strip() for ln in out.splitlines() if ln.startswith("configuration:")), "")
    if "--enable-gpl" in config and "--enable-version3" in config:
        lic = "GPL-3.0-or-later"
    elif "--enable-gpl" in config:
        lic = "GPL-2.0-or-later"
    else:
        lic = "LGPL-2.1-or-later"
    m = re.search(r"-g([0-9a-f]{7,40})", version)
    if "martin-riedl" in first:
        base = version.split("-", 1)[0]
        source = (f"FFmpeg {base}: https://ffmpeg.org/releases/ffmpeg-{base}.tar.xz\n"
                  "  Build scripts (all libraries and versions): https://git.martin-riedl.de/ffmpeg/build-script\n"
                  "  Builds and their library versions: https://ffmpeg.martin-riedl.de/")
    elif "gyan.dev" in first:
        g = re.search(r"git-([0-9a-f]{7,40})", version)
        source = ((f"FFmpeg git commit {g.group(1)}: https://github.com/FFmpeg/FFmpeg/tree/{g.group(1)}\n  "
                   if g else "") + "Builds and sources: https://www.gyan.dev/ffmpeg/builds/")
    elif m:
        source = (f"FFmpeg git commit {m.group(1)}: https://github.com/FFmpeg/FFmpeg/tree/{m.group(1)}\n"
                  "  Build scripts (all libraries and versions): https://github.com/yt-dlp/FFmpeg-Builds")
    else:
        source = "FFmpeg: https://ffmpeg.org/download.html#get-sources"
    return (f"FFmpeg and ffprobe {version}\n"
            f"License: {lic} (the full GPL-3.0 text is at the end of this file)\n"
            f"Homepage: https://ffmpeg.org/\n"
            f"Included unmodified as separate programs (bin/ffmpeg, bin/ffprobe).\n"
            f"Build configuration: {config or 'unknown'}\n\n"
            f"Complete corresponding source code:\n  {source}\n"
            f"If any of these stop working, ask at {ISSUES} and a copy of the exact\n"
            f"source will be provided.\n\n"
            "FFmpeg is a trademark of Fabrice Bellard, originator of the FFmpeg project.")


def deno_section():
    exe = _tool("deno")
    if not exe:
        return None
    first = (_run(exe, "--version").splitlines() or ["deno"])[0]
    m = re.search(r"deno (\S+)", first)
    ver = m.group(1) if m else "unknown"
    return (f"Deno {ver}\nLicense: MIT\nHomepage: https://deno.com/\n"
            f"Source: https://github.com/denoland/deno/tree/v{ver}\n"
            "Included unmodified as a separate program (bin/deno). Deno includes V8 and\n"
            "other components under their own permissive licenses; see its repository.\n\n"
            + _read(os.path.join(LICENSES, "Deno-LICENSE.md")))


def python_section():
    v = sys.version.split()[0]
    candidates = [os.path.join(sys.base_prefix, "LICENSE.txt"),
                  os.path.join(sysconfig.get_path("stdlib"), "LICENSE.txt"),
                  os.path.join(sys.base_prefix, "lib", f"python{sys.version_info[0]}.{sys.version_info[1]}",
                               "LICENSE.txt")]
    text = next((_read(p) for p in candidates if os.path.isfile(p)),
                "Python Software Foundation License Version 2: https://docs.python.org/3/license.html")
    return f"Python {v}\nLicense: PSF-2.0 (and the licenses of the components below)\nHomepage: https://www.python.org/\n\n{text}"


def tcl_tk_section():
    try:
        tk_ver = tkinter.Tcl().eval("info patchlevel")
    except Exception:
        tk_ver = "8.6"
    return (f"Tcl/Tk {tk_ver}\nLicense: TCL (BSD-style)\nHomepage: https://www.tcl-lang.org/\n\n"
            + _read(os.path.join(LICENSES, "Tcl-Tk-license.terms")))


def material_icons_section():
    return ("Material Icons (font, used on macOS)\nLicense: Apache-2.0\n"
            "Homepage: https://github.com/google/material-design-icons\n\n"
            + _read(os.path.join(ROOT, "assets", "fonts", "MaterialIcons-LICENSE.txt")))


def pyinstaller_section():
    try:
        v = md.version("pyinstaller")
    except md.PackageNotFoundError:
        v = ""
    return (f"PyInstaller bootloader {v}\nLicense: GPL-2.0-or-later with the PyInstaller bootloader exception,\n"
            "which allows distributing it with any program under any license.\n"
            "Homepage: https://pyinstaller.org/  Source: https://github.com/pyinstaller/pyinstaller")


def build() -> str:
    os.makedirs(OUT, exist_ok=True)
    sections = []
    for dist in bundled_distributions():
        m = dist.metadata
        head = (f"{m['Name']} {m['Version']}\nLicense: {_license_of(dist)}\n"
                f"Homepage: {_homepage(dist)}\nSource: https://pypi.org/project/{m['Name']}/{m['Version']}/")
        texts = list(_license_texts(dist))
        body = "\n\n".join(f"--- {fname} ---\n{text}" for fname, text in texts) or "(no license file in the package)"
        sections.append(head + "\n\n" + body)
    tools = [s for s in (ffmpeg_section(), deno_section()) if s]
    parts = [
        f"{APP_NAME} {__version__} - third-party software notices",
        f"Generated {datetime.date.today():%Y-%m-%d} for {sys.platform}.",
        "",
        f"{APP_NAME} itself is MIT-licensed (see LICENSE.txt). It includes the",
        "following software, each under its own license. GPL-licensed parts (FFmpeg,",
        "mutagen) are included unmodified, and their source is linked in their sections.",
        "",
    ]
    for section in tools + [python_section(), tcl_tk_section(), pyinstaller_section(),
                            material_icons_section()] + sections:
        parts += [RULE, section, ""]
    if tools:
        parts += [RULE, "GNU GENERAL PUBLIC LICENSE, version 3 (applies to FFmpeg/ffprobe)", "",
                  _read(os.path.join(LICENSES, "GPL-3.0.txt")), ""]
    path = os.path.join(OUT, "THIRD-PARTY-NOTICES.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(parts))
    with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as src, \
            open(os.path.join(OUT, "LICENSE.txt"), "w", encoding="utf-8", newline="\n") as dst:
        dst.write(src.read())
    names = [d.metadata["Name"] for d in bundled_distributions()]
    print(f"Wrote {path}: {len(tools)} tools + Python, Tcl/Tk, icons + {len(names)} packages ({', '.join(names)})")
    return path


if __name__ == "__main__":
    build()
