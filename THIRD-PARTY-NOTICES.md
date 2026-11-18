# Third-party software

YouDownloader's own code is MIT-licensed ([LICENSE](LICENSE)). The installers
also include the software below, each under its own license. Every build
generates the full notices, with exact versions, FFmpeg's build configuration
and every license text (`packaging/make_notices.py`). They ship inside the app:
**Settings → About & updates → Open-source licenses**.

| Component | License | Notes |
| --- | --- | --- |
| [FFmpeg / ffprobe](https://ffmpeg.org/) | GPL-3.0-or-later | Unmodified static builds run as separate programs. Windows: [yt-dlp/FFmpeg-Builds](https://github.com/yt-dlp/FFmpeg-Builds); macOS: [Martin Riedl](https://ffmpeg.martin-riedl.de/) ([build scripts](https://git.martin-riedl.de/ffmpeg/build-script)). The source for each shipped version is linked in the in-app notices. |
| [Deno](https://deno.com/) | MIT | Runs YouTube's JavaScript challenge. Unmodified binary. |
| [Python](https://www.python.org/) | PSF-2.0 | The bundled interpreter, with the components listed in its license. |
| [Tcl/Tk](https://www.tcl-lang.org/) | TCL (BSD-style) | The GUI toolkit. |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp), yt-dlp-ejs | Unlicense (ejs: Unlicense, MIT, ISC) | The download engine and its JS solver scripts. |
| [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter), darkdetect | MIT / CC0, BSD-3-Clause | UI widgets. |
| [Pillow](https://python-pillow.org/) | MIT-CMU | Images (includes its own bundled libraries' licenses). |
| [mutagen](https://github.com/quodlibet/mutagen) | GPL-2.0-or-later | Tagging, used by yt-dlp. Unmodified. |
| requests, urllib3, certifi, idna, charset-normalizer, brotli, websockets, pycryptodomex, packaging | Apache-2.0, MIT, MPL-2.0, BSD | Networking and support libraries. |
| [Material Icons](https://github.com/google/material-design-icons) | Apache-2.0 | Icon font used on macOS. |
| PyInstaller bootloader | GPL-2.0-or-later with the bootloader exception | Starts the packaged app; the exception allows any license for the app. |

GPL-licensed parts are included unmodified, and their source is linked. If a
link stops working, [open an issue](https://github.com/kanishkar-oss/youdownloader/issues)
and a copy of the exact source will be provided.
