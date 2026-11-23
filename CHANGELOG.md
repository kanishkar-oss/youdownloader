# Changelog - YouDownloader

## Unreleased — one Downloads list

- **One Downloads list** replaces the status panel and the queue. **Download** adds
  the link to the list and starts it, or queues it behind what's downloading, so you
  can keep adding links. **Add for later** adds it without starting.
- Each row shows its own progress ("Video 42% · 8.4 MB/s · 1:12 left"), then Play
  and Show in folder when it's saved (with its size and folder), or the reason and
  Retry when it fails ("What went wrong…" in the ⋯ menu shows the full error).
- Downloading first, then what's waiting in order, then finished downloads newest
  first. A row's play button downloads it next. **Pause all** puts the current
  download back to waiting; **Start** / **Start all** carries on.
- Rows show the video's title even when the link wasn't previewed.
- One notification when everything you started has finished ("Download finished" or
  "Downloads finished: 3 downloaded, 1 failed").
- Quitting mid-download leaves it waiting for next time instead of "Cancelled".
- Readable colours (labels, placeholders, input edges, the Download button), errors
  shown under the link box instead of dialogs, links that preview by themselves, and
  a slimmer header.

## Version 5.1.7 — browser button, M4A audio

- **Browser button**: Settings → Downloads → Browser button opens a page with
  a "Send to YouDownloader" bookmark. Clicking it on a YouTube video brings the
  app forward with that video loaded, in any browser. The installed app
  registers `youdownloader://` links (Windows registry, macOS Info.plist); a
  link reaching a second copy is handed to the open window.
- **M4A audio**: YouTube's own AAC stream saved without re-encoding (the best
  audio quality available), with cover art and tags.
- **Drag and drop on macOS accepts every drag type**, so links dragged from
  browsers that don't include plain text (e.g. Dia) work; HTML links are read too.
- CI checks the link scheme on the installed Windows app and the shipped Mac app.

## Version 5.1.6 — drag and drop, notifications, diagnostics

(5.1.5 was built but not published: its Apple Silicon check failed. 5.1.6 signs
every native library inside the Mac app, and CI now posts its check results
on the run's public summary page.)

- **Drag a link onto the window** (from a browser's address bar or tab, or a
  .url / .webloc file): it goes into the link box and is previewed.
- **Desktop notifications** when a download or the queue finishes (or a
  download fails) while the app is in the background. Settings → Interface.
- **Copy diagnostics** (Settings → About & updates → Report a problem):
  versions, tools, settings and recent log lines, home folder shortened, never
  cookies, ready to paste into a bug report.
- The packaged app bundles the whole Python standard library, so yt-dlp
  versions the app downloads later can't trip over a missing module; the
  self-test checks it on every platform.
- The installer registers the app's notification identity on its Start Menu
  shortcut.

## Version 5.1.4 — YouTube fixes without app updates, licenses, permanent links

- **YouTube fixes arrive by themselves**: the installed app downloads newer
  yt-dlp versions from PyPI in the background (about 3 MB, SHA-256 verified)
  and offers a restart to use them. A copy that fails to load is set aside
  automatically. Settings → Downloader: switch it off, update by hand, or go
  back to the built-in version. Support: `YouDownloader --update-ytdlp`.
- **Licenses**: YouDownloader is MIT-licensed. Every build ships full
  third-party notices (FFmpeg's GPL with links to its exact source, Deno,
  Python, Tcl/Tk, every Python package): Settings → About & updates →
  Open-source licenses.
- **Permanent download links**: each release also carries
  `YouDownloader-windows-setup.exe`, `-mac-apple-silicon.dmg` and
  `-mac-intel.dmg`, so `releases/latest/download/<name>` always gets the newest.
- Restart from inside the app (after a yt-dlp update) waits for the old copy
  to close first.
- CI's self-test checks that a downloaded yt-dlp takes precedence inside the
  packaged app on every platform.

## Version 5.1.0 — macOS, installers and automatic updates

### macOS support
- Runs on Macs with Apple Silicon and Intel, from source (`run.sh`) or as an app.
- ⌘ shortcuts (⌘D / ⌘S / ⌘O), ⌘, opens Settings and ⌘Q quits from the app menu
  (saving window size and queue like closing the window does).
- Icons from a bundled Material Icons font (Segoe icons are Windows-only);
  SF Pro / Helvetica Neue text when Inter isn't installed.
- Reveal in Finder, Dock bounce when a background download finishes, dark
  window chrome, right-click / Control-click menus.
- Hardware H.264 encoding with VideoToolbox for MOV.
- Settings, queue and logs live in ~/Library/Application Support and
  ~/Library/Logs for the installed app.

### Installers
- Windows installer (per-user, no admin prompt) and Mac .dmg for Apple Silicon
  and Intel, built by GitHub Actions for every release.
- FFmpeg, ffprobe and Deno are built in: nothing else to install.
- `YouDownloader --self-test` checks a packaged build (used by CI).

### Automatic updates
- The installed app checks GitHub Releases on launch and offers new versions;
  updates download with progress, are SHA-256 verified, install and restart.
- Settings → About & updates: version, Check for updates, automatic check switch.
- `scripts/release.ps1` / `release.sh` publish a new version in one command.

---

## Version 5.0.0 — redesign

### Design audit (what was wrong)
- Weights never rendered: the type stack asked for "Inter" bold/normal only, so
  every label was regular or heavy bold; nothing in between.
- Icons were emoji / text glyphs (⚙ ⋯ ↯ ●) that change size and baseline by font.
- Dialogs still used the old neon "tech" style: 48px emoji, accent-colored body
  text, red buttons, fixed sizes that clipped long messages.
- Menus (dropdown, row ⋯, right-click) were native Windows-95-style popups that
  ignored the palette. The title bar was the default system color.
- Cards stretched edge to edge on wide windows; the progress bar showed a stray
  dot at 0%; the preview text was centered; the queue rebuilt every row three
  times a second while downloading (flicker).
- Three palettes (Midnight / Daylight / Graphite) diluted the look.

### New design
- One dark **space** palette: void background, hairline-separated navy cards,
  cool grey text, single violet accent, softened state colors.
- **Starfield header** with nebula glow, twinkling stars, and an orbiting satellite
  (faster while downloading); a **sign-in chip** shows whether you'll get full quality.
- **Inter** with real Medium / SemiBold weights (falls back to Segoe UI Variable),
  tracked uppercase section labels, monospaced stats.
- **Segoe Fluent Icons** across buttons, rows, banners and dialogs.
- Centered content column (max 880px). Link field styled as a search bar with
  Paste and Preview inside; labelled form grid (Format, Quality, File name, Clip,
  Save to); violet Download button that turns into a red-outlined Stop.
- Status panel: status line, mono speed / time-left readout, thin progress bar,
  Play / Show in folder / Rename when done.
- Queue rows with status icons, format chips and in-place progress updates
  (no more flicker); a proper empty state.
- Themed popup menus and dropdowns; one consistent dialog style with icon badges;
  Settings regrouped into cards with switches.
- Windows 11 title bars tinted to the app; rounded popup corners.

### New
- **File rename**: set a file name before downloading (also names a playlist's
  folder), or rename afterwards from the finished download or a queue row.
  Sidecar subtitle files follow; reserved/invalid names are explained.
- `Enter` in the link field previews; `Ctrl+,` opens Settings.

### Removed
- Daylight and Graphite palettes (old settings still load).

---

## Version 4.2.0

### Easier to open
- **Double-click `YouDownloader.pyw`** or the new **Desktop / Start Menu shortcut**
  (`install_shortcut.bat` creates them). No console window; uses the project's
  `.venv` automatically.
- Single instance: opening it again brings the existing window forward instead
  of starting a second copy that would fight over the queue.
- Startup crashes show a message box (there's no console to print to) and are logged.
- Proper square app icon in the title bar, taskbar and shortcuts.

### New features
- **Clips**: optional start/end time to download part of a video (any format).
- **Cover art & tags** embedded (title, artist, date, chapters); cover art for MP3/MP4.
- **Subtitles** (.srt, chosen language): the old unused setting now has a switch.
- **Playlists**: confirm before downloading; saved into a numbered subfolder.
- **Paste list…**: queue many links at once.
- **Clipboard auto-fill**: a copied YouTube link is filled in and previewed when
  you switch to the app.
- **Finished downloads** show Play / Show in folder buttons instead of a modal
  dialog, and the taskbar flashes when the app is in the background. "Added to
  queue" no longer pops a dialog either.
- **Right-click Cut / Copy / Paste** in text fields.
- **yt-dlp updates**: Settings shows the version and age with a one-click update;
  a banner appears when it's over 60 days old.
- **Cookies (sign-in)**: Settings imports a cookies.txt to a private folder outside
  OneDrive, and shows whether it's signed in and when it expires.

### Fixes
- **Progress bar and Stop didn't work when aria2c was installed** (aria2c gives
  yt-dlp no progress). aria2c is now opt-in; it wasn't faster anyway.
- **Audio clips ignored the start time** (fixed by forcing accurate cuts).
- **MOV: 10-bit H.264 was copied as-is**, which QuickTime can't play. Only 8-bit
  4:2:0 H.264 is copied now; anything else is re-encoded.
- **MOV: HDR videos looked washed out.** SDR streams are preferred, and HDR-only
  sources are tone-mapped to BT.709.
- Preview strip now appears under the link instead of below the Download button.
- Tests no longer write fake errors into the real `logs/youdownloader.log`.

### Verified
- Real 4K MOV download with sign-in cookies: 3840x2160 H.264 8-bit BT.709 + AAC
  (NVENC re-encode), 57 s for an 82 s 4K60 video.
- Stop mid-download and mid-conversion leaves no partial files.

---

## Version 4.1.0

### New formats
- **MOV video**: QuickTime-ready H.264 + AAC. Up to 1080p it remuxes YouTube's
  own H.264 stream (fast, lossless); for 1440p/4K it re-encodes VP9/AV1 to H.264,
  using NVENC / Quick Sync when available and libx264 otherwise. Progress is shown
  while converting, and Stop cancels the conversion cleanly.
- **WAV audio**: 16-bit/44.1 kHz (CD), 16-bit at the original rate, or 24-bit/48 kHz.
- The format picker is now `MP4 · MOV · MP3 · WAV`; switching MP4/MOV keeps the
  chosen quality. Works for direct downloads and the queue.

### Fixes
- **"Download complete!" appeared too early**: it fired when the first stream
  (video) finished, before the audio stream, merging, or MP3 conversion. Completion
  is now reported only when the whole download really finishes.
- **Downloads could crash on progress** when yt-dlp reported an unknown size
  (`total_bytes: None` raised a TypeError inside the progress hook).
- **MP3 "Best (320kbps)" was encoded at 192 kbps.** It's now 320 kbps.
- **Letterboxed / vertical videos falsely said "Quality not available"** (e.g.
  1920x960 was read as 720p). Resolution tiers now follow YouTube's labelling,
  and quality limits are a preference rather than a hard filter.
- **Links copied from a Mix/playlist** (`watch?v=...&list=...`) downloaded the entire
  playlist. They now download just that video.
- **Stop during "Preparing..." didn't stop**: the download started anyway once the
  quality check returned.
- **Queue:** cancelling recorded the item as *Failed* and immediately started the
  next one, and there was no way to stop the queue. The queue button now toggles
  Start / Stop, cancelled items are marked *Cancelled*, and Retry works for them.
- **Queue UI** was rebuilt from worker threads on every progress tick (flicker,
  thread-unsafe Tk calls). It now refreshes from the main thread a few times a second.
- **Wrong title in the queue**: a previewed video's title was attached to a
  different URL added afterwards.
- **Fallback downloads ran without the JS runtime**, so they were throttled and
  often failed with "Requested format is not available".
- **Window icon never showed** (Tk needs a PhotoImage, and the asset path was
  relative to the working directory).
- **Maximized window** was saved as a giant normal window; it's now restored maximized.
- MP3/WAV/MOV without FFmpeg now show a clear message up front instead of a
  cryptic yt-dlp error.
- "Reveal in folder" selects the downloaded file.

### Dependencies
- **yt-dlp was pinned below 2026** and stuck at 2025.12.08. Now
  `yt-dlp[default]>=2026.10.26` with no upper bound (old yt-dlp breaks as
  YouTube changes).
- `[default]` bundles the JS challenge solver (`yt-dlp-ejs`), so fast downloads
  no longer need to fetch code from GitHub. The consent setting now only controls
  fetching *updated* solver code.

---

## Version 4.0.0

A focused rework of the interface, setup flow, and faster-downloads path.

### Redesign
- **New default look**: the "Midnight" palette — a dark theme built around a
  single tasteful indigo accent. The old neon "tech" theme has been removed.
- **Palette options**: "Daylight" (light) and "Graphite" (OLED-friendly near-black)
  alternatives. Legacy theme names (`tech`/`dark`/`light`) auto-migrate to the new
  palettes, so existing settings keep working.
- **Design system**: introduced `src/ui/tokens.py` (spacing/radius/type/motion/
  sizing), `src/ui/palettes.py` (color palettes), and `src/ui/widgets/` (Primary/
  Secondary/Ghost/Icon buttons, field entry, status pip, inline banner, motion
  helper). `src/ui/themes.py` is now a thin facade over the palette system.
- **Top bar**: wordmark replaces the loud logo header (the bitmap logo remains the
  window icon). Added a Settings button (⚙).
- **Settings sheet**: switch palette, toggle visual effects (animations), re-show
  dismissed setup banners, and toggle the remote JS-runtime consent.
- **Dismissable setup banners** replace always-on warning labels; dismissals are
  remembered per setting.

### Setup & environment
- **Project-local virtualenv**: setup now creates `.venv` with
  `py -3 -m venv .venv` and installs from `requirements.txt`. `run.bat` prefers
  `.venv\Scripts\python.exe`, falling back to the `py` launcher / `python`.

### Faster downloads (opt-in)
- Faster downloads now require **explicit one-time consent**, because reaching full
  speed fetches and runs a JavaScript challenge solver from GitHub. Consent is
  tri-state (`null`/`true`/`false`) and changeable in Settings.
- `install_deno.bat` no longer pipes remote code into `iex`. It runs the committed,
  readable `install_deno.ps1`, which downloads the official installer, prints its
  SHA-256, and asks before running it (with an optional pinned-hash mode).

### Quality & safety
- Added a unit-test suite under `tests/` (run with
  `.venv\Scripts\python -m unittest discover -s tests`).
- Settings are now written atomically (temp file + `os.replace`) so a crash
  mid-write can't corrupt `settings.json`.

### Unchanged
- Keyboard shortcuts: `Ctrl+D` (download), `Ctrl+S` (stop), `Ctrl+O` (browse),
  `Ctrl+Q` (quit), `F5` (preview).

---

## Version 3.0.0

### Major Changes

#### Architecture Refactoring
- **Modular Structure**: Complete refactoring from single-file to modular architecture
  - Separated into `src/ui/`, `src/downloader/`, `src/utils/`, and `src/models/` modules
  - Improved code organization and maintainability
  - Better separation of concerns

#### New Features
- **Download Queue System**: 
  - Add multiple downloads to queue
  - Sequential processing
  - Queue persistence (survives app restart)
  - Progress tracking per item
  - Remove items from queue
  - Clear completed items

- **Video Preview & Metadata**:
  - Automatic video info fetching on URL paste
  - Display title, channel, duration
  - Playlist detection
  - File size estimates

- **Configuration Management**:
  - JSON-based settings file
  - Persistent user preferences
  - Auto-save on changes
  - Window position/size memory

- **Logging System**:
  - File logging with rotation (10MB max, 5 backups)
  - Multiple log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - Console output for errors

- **Enhanced Error Handling**:
  - User-friendly error dialogs
  - Actionable error messages
  - Better error recovery

- **Keyboard Shortcuts**:
  - `Ctrl+D`: Start download
  - `Ctrl+S`: Stop download
  - `Ctrl+O`: Browse folder
  - `Ctrl+Q`: Quit
  - `F5`: Refresh video info

#### Code Quality Improvements
- **Type Hints**: Full type annotations throughout
- **Documentation**: Comprehensive docstrings
- **Constants**: Centralized constants file
- **Validation**: Robust URL and path validation
- **Thread Safety**: Proper threading implementation

#### UI Improvements
- **Modern Components**: Reusable UI components
- **Theme Management**: Centralized theme system
- **Dialog Windows**: Error, info, and confirmation dialogs
- **Progress Display**: Enhanced progress visualization
- **Queue Display**: Visual queue management interface

### Technical Details

#### New Modules
- `src/utils/config.py`: Configuration management
- `src/utils/logger.py`: Logging system
- `src/utils/validators.py`: Validation functions
- `src/utils/helpers.py`: Helper utilities
- `src/utils/constants.py`: Application constants
- `src/models/download.py`: Download data models
- `src/downloader/engine.py`: Core download engine
- `src/downloader/queue.py`: Queue management
- `src/downloader/formats.py`: Format handling
- `src/ui/components.py`: Reusable UI components
- `src/ui/dialogs.py`: Dialog windows
- `src/ui/themes.py`: Theme configuration

#### File Structure
```
YouDownload/
├── src/                    # Source code
│   ├── app.py             # Main application
│   ├── ui/                # UI components
│   ├── downloader/        # Download engine
│   ├── utils/             # Utilities
│   └── models/            # Data models
├── config/                # Configuration files
├── logs/                  # Application logs
├── main.py                # Entry point
└── requirements.txt       # Dependencies
```

### Backward Compatibility
- Main entry point (`main.py`) still works
- Existing functionality preserved
- Settings automatically migrated

### Future Enhancements (Planned for v3.1+)
- Download history with database
- Batch downloads from file
- Subtitle download support
- More format options
- System notifications
- Concurrent downloads
- Download resume capability



