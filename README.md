# YouDownloader

A modern YouTube downloader for **Windows and macOS** with a clean CustomTkinter GUI,
built on yt-dlp. Installers for both, with built-in automatic updates.

## Features

### Core
- **Video downloads** — MP4 or MOV, quality from 480p up to 4K / Native
  - **MOV** is QuickTime-ready (H.264 + AAC, opens in QuickTime, Final Cut, Premiere).
    Up to 1080p it uses YouTube's own H.264 stream (fast, lossless). For 1440p/4K,
    where YouTube only offers VP9/AV1, it re-encodes to H.264, on the GPU
    (NVENC / Quick Sync) when available, otherwise libx264 (slower).
- **Audio downloads** — MP3 (320 or 128 kbps) or WAV (16-bit/44.1 kHz CD,
  16-bit at the original rate, or 24-bit/48 kHz). YouTube audio is lossy at the
  source, so WAV is for editing convenience, not extra fidelity.
- **Download queue** — queue links, process sequentially (Start / Stop), persisted across restarts; per-item retry / remove / reveal-in-folder via an overflow (⋯) menu
- **Single video from playlist links** — a `watch?v=…&list=…` link (e.g. from a Mix) downloads just that video; `/playlist?list=…` links download the playlist
- **File names** — type a name before downloading (blank = the video title), or
  **Rename** afterwards from the finished download or a queue row's ⋯ menu.
  Subtitle files are renamed along with the video; invalid names are explained.
- **Clips** — optional start/end times (e.g. `1:30` – `2:45`) to download just part of a video, in any format
- **Cover art & tags** — title / artist / date (and chapters for video) embedded; cover art in MP3 and MP4
- **Subtitles** — optional `.srt` subtitles in your language (Settings)
- **Playlists** — `/playlist?list=…` links ask first, then save into their own folder, numbered in order
- **Paste list…** — add many links to the queue at once
- **Clipboard auto-fill** — copy a YouTube link, switch to the app, and it's filled in and previewed
- **When done** — Play / Show in folder buttons, and the taskbar button flashes if the app is in the background
- **Full quality with sign-in** — import a cookies.txt in Settings (see below)
- **Keeps yt-dlp current** — a banner appears when yt-dlp is over 60 days old; update from Settings in one click
- **Video preview** — fetch thumbnail, title, channel, and duration before downloading; playlist detection
- **Live URL check** — a status dot turns green/red as you type
- **Progress tracking** — real-time percent, speed, and ETA

### Faster downloads
YouTube throttles plain downloads (~0.3 Mbps). yt-dlp defeats this by running a
JavaScript challenge solver, which needs a JS runtime (Deno; Node also works).
The solver is **bundled locally** (`yt-dlp-ejs`, installed by `yt-dlp[default]`),
so nothing is fetched at runtime by default.

- On first launch a one-time **consent dialog** asks whether yt-dlp may also fetch
  an *updated* solver from GitHub when the bundled one goes stale. It's off unless
  you opt in, and can be flipped any time in Settings.
- Install Deno with `install_deno.bat`. That wrapper runs the
  committed, readable `install_deno.ps1`, which **downloads the official installer,
  shows its SHA-256, and asks before running it** — instead of piping remote code
  straight into `iex`. (Set `$ExpectedHash` in the script to pin a known-good hash.)

### Interface
A dark, minimal "space" design:
- **Starfield header**: a procedurally rendered deep-space band (faint violet and
  cyan nebula, star dust) with a few twinkling stars and a satellite on a hairline
  orbit that speeds up while downloading. Turn motion off in Settings → Interface.
- **One palette**: void background, near-black navy cards separated by hairlines,
  cool grey text and a single violet accent. Windows 11 title bars are tinted to match;
  on macOS the window uses the dark appearance.
- **Typography**: Inter (Regular / Medium / SemiBold) when installed, falling back
  to Segoe UI Variable / Segoe UI on Windows and SF Pro / Helvetica Neue on macOS.
  Tracked uppercase labels, a monospaced readout for speed and time left.
- **Icons** from Segoe Fluent Icons on Windows and the bundled Material Icons font
  on macOS, rendered crisply at any DPI.
- **Calm layout**: content sits in a centered column (max 880px), so wide or
  maximized windows don't stretch the cards.
- **Themed menus and dialogs**: dropdowns, row menus and right-click menus are
  custom popups (not native menus); every dialog shares one style with
  Esc / Enter support. Right-click (or Control-click on a Mac) works in text fields.
- **Keyboard shortcuts:** `Ctrl+D` download · `Ctrl+S` stop · `Ctrl+O` folder ·
  `Ctrl+,` settings · `F5` preview · `Enter` in the link box previews · `Ctrl+Q` quit.
  On macOS use ⌘ instead of Ctrl (⌘, opens Settings, ⌘Q quits).

### Under the hood
- Modular architecture with a token-based design system (see below)
- Atomic, crash-safe settings writes
- Logging to file and console
- Robust URL and path validation
- Threaded, non-blocking downloads and queue operations

## Download (Windows and macOS)

Get the latest version from the
[**Releases page**](https://github.com/kanishkar-oss/youdownloader/releases/latest).
FFmpeg and Deno come built in; there's nothing else to install.

| System | File |
| --- | --- |
| Windows 10 / 11 (64-bit) | `YouDownloader-<version>-windows-setup.exe` |
| Mac with Apple Silicon (M1 and newer) | `YouDownloader-<version>-mac-apple-silicon.dmg` |
| Mac with an Intel chip | `YouDownloader-<version>-mac-intel.dmg` |

Not sure which Mac you have? Apple menu → About This Mac → "Chip" (Apple M…) or
"Processor" (Intel).

**Windows:** run the installer. It installs just for you (no admin prompt) and
adds a Start Menu shortcut. The builds aren't code-signed yet, so SmartScreen
may say "Windows protected your PC": click **More info → Run anyway**.

**macOS:** open the .dmg and drag YouDownloader into Applications. The app
isn't notarized by Apple yet, so the first launch is blocked:
1. Open it once (it will be refused), then go to **System Settings → Privacy &
   Security**, scroll down and click **Open Anyway**, or
2. in Terminal run `xattr -dr com.apple.quarantine /Applications/YouDownloader.app`.

macOS asks once for permission to save to your Downloads folder.

### Updates
The app checks for a new version each time it opens and shows a banner when
there is one. **Update** downloads it, checks its SHA-256, installs it and
restarts the app; settings, queue and sign-in are kept. Turn the check off, or
check by hand, in **Settings → About & updates**.

On a Mac the app must be in a folder you can write to (Applications is fine)
to update itself. If it can't, it offers the download page instead.

## Releasing updates (maintainer)

Every release is built by GitHub Actions (`.github/workflows/release.yml`) on
Windows, Apple Silicon and Intel runners and published as a GitHub Release,
which installed copies pick up on their next launch. From your machine:

```powershell
.\scripts\release.ps1 5.1.1 -Notes "Fixes playlist folder names"
```

(`./scripts/release.sh 5.1.1 "notes"` on macOS/Linux.) It bumps
`src/version.py`, commits, tags `v5.1.1` (the tag message becomes the release
notes; without `-Notes` they're the commit messages since the last release)
and pushes. The builds take about 15 minutes; follow them on the repo's
**Actions** tab. Every build runs the unit tests and a smoke test of the packaged
app (`YouDownloader --self-test report.txt`) before anything is published.

Every build installs the newest yt-dlp, so YouTube fixes reach testers
through app updates. Cut a release every month or two even without code
changes.

To get test builds without publishing, run the workflow by hand (Actions →
Build & release → Run workflow) and download the artifacts from the run.

### Building locally
```powershell
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-build.txt
.venv\Scripts\python packaging\build.py
```
This fetches ffmpeg, ffprobe and Deno (`packaging/fetch_tools.py`, SHA-256
checked), runs PyInstaller (`packaging/YouDownloader.spec`) and makes the
installer: Inno Setup 6 on Windows (`packaging/windows/installer.iss`), or a .dmg
and .zip on macOS. A Mac build has to be made on a Mac, which is why CI does it.
`--skip-installer` stops after `dist/YouDownloader/`.

## Run from source

### Prerequisites
- Python 3.10+ (3.12 recommended; on macOS use the python.org installer, which
  includes Tk)
- FFmpeg: needed for MOV, MP3 and WAV, and to merge separate video and audio
  streams for MP4. Without it MP4 falls back to a lower-quality single-file stream.
  - **Windows**: download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
  - **macOS**: `brew install ffmpeg`
- Deno, for fast downloads: `install_deno.bat` on Windows, `brew install deno` on macOS

### Set up the project-local environment
Windows:
```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```
macOS:
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

### Run
**Windows:** double-click `YouDownloader.pyw`, or use the **YouDownloader**
shortcut on your Desktop / in the Start Menu (`install_shortcut.bat` creates
it). Both open the app with no console window, and opening it again just
brings the existing window forward. `run.bat` shows a console with logs.

**macOS:** `./run.sh`.

If the app fails to start, a message box shows the error and it's written to
the log (see Logging).

### Full quality: sign in with cookies.txt
YouTube only serves 720p and above to signed-in sessions; without sign-in most
videos are capped at ~360p. Chrome and Edge encrypt their cookies, so yt-dlp
can't read them directly. Export them instead:

1. Install the **Get cookies.txt LOCALLY** extension in Chrome or Edge.
2. Open youtube.com while signed in, click the extension, **Export**.
3. In the app: **Settings → YouTube sign-in → Choose…** and pick the file.

The file is checked (signed in? expiry date?) and copied to the private app
data folder (`%LOCALAPPDATA%\YouDownloader\cookies.txt` on Windows,
`~/Library/Application Support/YouDownloader/cookies.txt` on macOS), outside
OneDrive/iCloud, since it holds live session tokens. Delete the exported copy
afterwards. Re-export when Settings says the cookies have expired. yt-dlp's own
docs warn that heavy use with account cookies can get an account flagged, so a
secondary Google account is safest.

### Keep yt-dlp current (source installs)
YouTube changes often and old yt-dlp versions stop working. Update it from
Settings, or:

```powershell
.venv\Scripts\python -m pip install -U "yt-dlp[default]"
```

## Usage

1. Paste a YouTube link — the validity dot confirms it's recognized.
2. (Optional) Click **Preview** to fetch the title, channel, duration, and thumbnail.
3. Choose a format (MP4 / MOV video, MP3 / WAV audio) and quality.
4. Pick a save location.
5. Click **Download** to start now, or **Add to Queue** to batch it. Use **Start**
   in the Queue panel to process pending items.

## Tests

A unit-test suite lives in `tests/` (validators, config crash-safety, logging,
formats/quality presets, engine options, queue cancel):

```powershell
.venv\Scripts\python -m unittest discover -s tests
```

## Project Structure

```
YouDownload/
├── src/
│   ├── app.py                 # Main application window
│   ├── version.py             # Version + GitHub repo used by the updater
│   ├── selftest.py            # --self-test for packaged builds (CI smoke test)
│   ├── ui/
│   │   ├── tokens.py          # Design tokens: spacing, radius, type (runtime font pick), motion
│   │   ├── palettes.py        # The dark "space" palette
│   │   ├── icons.py           # Segoe Fluent / Material icon fonts → crisp tinted images
│   │   ├── themes.py          # Thin facade over the palette system
│   │   ├── components.py      # Logo loader, progress display
│   │   ├── dialogs.py         # Error/Info/Confirm, consent, quality, Settings sheet
│   │   └── widgets/           # Atomic widgets
│   │       ├── header.py      # Starfield header (wordmark, sign-in chip, settings)
│   │       ├── popup.py       # Themed popup menus
│   │       ├── buttons.py     # Primary / Secondary / Ghost / Danger / Icon buttons
│   │       ├── entry.py       # Field entry + dropdown select
│   │       ├── pip.py         # Status dot
│   │       ├── banner.py      # Dismissable inline banner
│   │       └── motion.py      # Color crossfade animation helper
│   ├── downloader/
│   │   ├── engine.py          # Core download logic
│   │   ├── queue.py           # Queue management
│   │   ├── convert.py         # FFmpeg → QuickTime MOV (copy or H.264 re-encode)
│   │   └── formats.py         # Format / quality handling
│   ├── utils/
│   │   ├── config.py          # Atomic settings persistence
│   │   ├── logger.py          # Logging
│   │   ├── validators.py      # URL / path / disk validation
│   │   ├── helpers.py         # Helpers (FFmpeg check, formatting)
│   │   ├── cookies.py         # cookies.txt import + validity check
│   │   ├── updater.py         # yt-dlp age check / self-update (source installs)
│   │   ├── app_update.py      # App self-update from GitHub Releases
│   │   ├── paths.py           # Where config/logs/resources live (source vs installed)
│   │   ├── winsys.py          # Single instance, taskbar flash / Dock bounce, reveal, title bar
│   │   ├── files.py           # Safe rename of downloads (+ subtitle sidecars)
│   │   └── constants.py       # Constants
│   └── models/
│       └── download.py        # Download item model
├── tests/                     # Unit tests
├── packaging/                 # PyInstaller spec, Inno Setup script, build + tool fetch scripts
├── scripts/release.ps1/.sh    # Cut a release (bump version, tag, push)
├── .github/workflows/         # CI: build Windows + Mac, publish GitHub Release
├── config/                    # settings.json, queue.json (from source; not committed)
├── assets/                    # App icons (.ico/.icns/.png), logo, fonts/ (Material Icons)
├── logs/                      # Application logs (from source; not committed)
├── main.py                    # Entry point (single instance, crash dialog)
├── YouDownloader.pyw          # Double-click launcher (no console)
├── install_shortcut.bat/.ps1  # Desktop + Start Menu shortcuts
├── requirements.txt           # Dependencies
├── run.bat / run.sh           # Launchers (prefer .venv)
├── install_deno.bat           # Verify-then-run Deno installer wrapper
└── install_deno.ps1           # Readable installer (download → show hash → confirm)
```

The UI is built on a small design system: `tokens.py` is the single source of
truth for spacing/radius/type/motion, `palettes.py` holds the color palettes, and
`widgets/` provides reusable atoms. `themes.py` is now a thin palette facade that
also resolves legacy theme names (`tech`/`dark`/`light`) to the new palettes.

## Notes
- **aria2c** is no longer used by default: with it yt-dlp reports no progress
  (so the bar and Stop can't work) and it wasn't faster than yt-dlp's own
  downloader. It's still available to code via `download(..., use_aria2c=True)`.
- **HDR videos in MOV**: the SDR version is preferred; if a video is HDR-only it's
  tone-mapped to SDR (BT.709) so colors don't look washed out in QuickTime.

## Configuration

Settings are stored in `settings.json` and written atomically (a crash
mid-write can never corrupt the file). From source it's `config/settings.json`;
the installed app keeps it in `%LOCALAPPDATA%\YouDownloader\config\` (Windows) or
`~/Library/Application Support/YouDownloader/config/` (macOS). Notable keys:

- `download_path`, `format` (`Video (MP4)`, `Video (MOV)`, `Audio (MP3)`, `Audio (WAV)`), `quality`
- `theme` — ignored; there is one dark theme (old values are harmless)
- `visual_effects_enabled` — toggle UI animations
- `js_runtime_consent` — tri-state for fetching solver updates from GitHub:
  `null` (not yet asked), `true` (opted in), `false` (declined)
- `cookies_file` — Netscape cookies.txt for sign-in-gated / full-quality videos
  (falls back to the imported `cookies.txt` in the app data folder if present)
- `embed_metadata` — embed tags and cover art (default on)
- `auto_download_subtitles`, `subtitle_language` — subtitle download
- `banner_dismissed_ffmpeg`, `banner_dismissed_deno` — remembered banner dismissals
- `window_width` / `window_height` / `window_x` / `window_y` / `window_maximized` — window geometry
- `auto_check_updates`, `skipped_update_version` — app updates (installed app)
- `ffmpeg_path`, plus speed knobs (`max_concurrent_fragments`, `http_chunk_size`,
  `adaptive_chunk_size`)

The download queue is persisted separately in `queue.json` next to it.

## Logging

Logs are written to `youdownloader.log` with rotation (10MB max, 5 backups): `logs/`
from source, `%LOCALAPPDATA%\YouDownloader\logs\` in the installed Windows app,
`~/Library/Logs/YouDownloader/` on macOS.
Levels: DEBUG, INFO, WARNING, ERROR, CRITICAL.

## License

Provided as-is for personal use.

## Credits

- Built with [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
- Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- Uses [Pillow](https://python-pillow.org/) for image handling
- Bundles [FFmpeg](https://ffmpeg.org/) (GPL builds by yt-dlp and Martin Riedl), [Deno](https://deno.com/), and
  [Material Icons](https://github.com/google/material-design-icons) (Apache 2.0)
