"""Core download engine using yt-dlp"""
import os
import re
import shutil
import yt_dlp
from typing import Optional, Callable, Dict, Any, Tuple, List

from src.utils.logger import get_logger
from urllib.parse import urlparse

from src.utils.validators import validate_youtube_url, format_timestamp
from src.downloader.formats import FormatManager, VIDEO_MOV, VIDEO_MP4, AUDIO_WAV
from src.downloader.convert import ConversionCancelled, ConversionError, to_quicktime_mov
from src.utils.constants import (
    REMOTE_COMPONENTS_SPEC,
    DEFAULT_CONCURRENT_FRAGMENTS,
    DEFAULT_HTTP_CHUNK_SIZE,
    DEFAULT_SOCKET_TIMEOUT,
    DEFAULT_RETRIES,
)

logger = get_logger()

# Compiled once: strips ANSI escape codes (e.g. "\x1b[0;31m") from yt-dlp errors.
_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m|\[\d+(?:;\d+)*m')

# Bound the title segment (180 bytes) so a pathological video title can't blow
# past the OS path limit; yt-dlp still sanitizes the title.
_OUTTMPL = '%(title).180B.%(ext)s'

# Download attempts, in the order the engine falls back through them.
_PRIMARY = "primary"          # requested quality
_BEST = "best"                # anything downloadable
_PROGRESSIVE = "progressive"  # single-file ~360p stream (survives SABR gating)


class _DownloadCancelled(Exception):
    """Raised from the progress hook to abort an in-flight yt-dlp download."""


class DownloadEngine:
    """Core download engine using yt-dlp"""

    def __init__(
        self,
        progress_callback: Optional[Callable] = None,
        allow_remote_components: bool = False,
        cookie_file: Optional[str] = None,
        ffmpeg_path: Optional[str] = None,
    ):
        """
        Initialize download engine.

        Args:
            progress_callback: Callback for progress dicts. Receives yt-dlp's
                hook dicts ('downloading'/'finished') plus
                {'status': 'converting', 'progress': 0..1, 'action': str}
                while a MOV is being packaged/re-encoded.
            allow_remote_components: When True, yt-dlp may fetch an updated JS
                challenge solver from GitHub if the bundled yt-dlp-ejs one is
                missing or outdated. Gated behind explicit user consent.
            cookie_file: Path to a Netscape-format cookies.txt. Lets yt-dlp send
                authenticated requests so SABR/auth-gated high-quality formats
                become downloadable.
            ffmpeg_path: FFmpeg executable (defaults to the one on PATH).
        """
        self.progress_callback = progress_callback
        self.allow_remote_components = allow_remote_components
        self.cookie_file = cookie_file
        self.ffmpeg_path = ffmpeg_path or shutil.which('ffmpeg')
        self.ydl_instance: Optional[yt_dlp.YoutubeDL] = None
        self.cancelled = False
        self.logger = logger
        # Temp/.part files yt-dlp reports via the progress hook, removed on
        # cancel/failure so aborted downloads don't litter the output directory.
        self._partial_files: set = set()
        # Final file paths of the last successful download (after post-processing).
        self.downloaded_files: List[str] = []

    # ----- shared option building ----------------------------------------

    def _common_opts(self) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            # A watch?v=…&list=… link (e.g. copied from a Mix) downloads just
            # that video; pure /playlist links still download the playlist.
            'noplaylist': True,
        }
        if self.allow_remote_components:
            opts['remote_components'] = [REMOTE_COMPONENTS_SPEC]
        if self.cookie_file:
            opts['cookiefile'] = self.cookie_file
        js_runtime = self._get_js_runtime()
        if js_runtime:
            opts['js_runtimes'] = js_runtime
        if self.ffmpeg_path:
            opts['ffmpeg_location'] = self.ffmpeg_path
        return opts

    def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Get video information without downloading.

        Args:
            url: YouTube URL

        Returns:
            Video information dictionary or None on error
        """
        is_valid, error_msg = validate_youtube_url(url)
        if not is_valid:
            self.logger.error(f"Invalid URL: {error_msg}")
            return None

        ydl_opts = {
            **self._common_opts(),
            'quiet': True,
            'no_warnings': True,
            # Don't resolve every entry of a playlist just to show a preview.
            'extract_flat': 'in_playlist',
            'skip_download': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                entries = info.get('entries')
                is_playlist = entries is not None
                if is_playlist and not isinstance(entries, list):
                    entries = list(entries)
                return {
                    'id': info.get('id'),
                    'url': url,
                    'title': info.get('title'),
                    'duration': info.get('duration'),
                    'thumbnail': info.get('thumbnail'),
                    'uploader': info.get('uploader') or info.get('channel'),
                    'view_count': info.get('view_count'),
                    'formats': info.get('formats', []),
                    'is_playlist': is_playlist,
                    'playlist_count': len(entries) if is_playlist else 0,
                }
        except Exception as e:
            self.logger.error(f"Error getting video info: {self._clean_error_message(str(e))}")
            return None

    def check_available_quality(
        self,
        url: str,
        format_mode: str,
        quality: str,
        info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str], List[str]]:
        """
        Check if requested quality is available and return available resolutions.

        Args:
            url: YouTube URL
            format_mode: a FormatManager mode (e.g. "Video (MP4)")
            quality: Requested quality preset
            info: Already-fetched video info (from a preview) to avoid a refetch

        Returns:
            Tuple of (is_available, best_available_resolution, all_available_resolutions)
        """
        if not FormatManager.is_video(format_mode):
            return True, None, []
        # "Native (Max Quality)" means "best available" — always satisfiable.
        if FormatManager.get_quality_height(quality) is None:
            return True, None, []

        try:
            if not info or not info.get('formats'):
                info = self.get_video_info(url)
            if not info or not info.get('formats'):
                return True, None, []  # Can't determine, allow download

            formats = info['formats']
            available = FormatManager.get_available_resolutions(formats)
            if not available:
                return True, None, []

            _, best_res, is_exact = FormatManager.get_best_available_resolution(formats, quality)
            return is_exact, best_res, [res for _, res in available]
        except Exception as e:
            self.logger.error(f"Error checking available quality: {e}", exc_info=True)
            return True, None, []  # On error, allow download

    @staticmethod
    def is_playlist_url(url: str) -> bool:
        """A /playlist?list=… link (watch?v=…&list=… is treated as one video)."""
        parsed = urlparse(url if "://" in url else "https://" + url)
        return parsed.path.rstrip("/") == "/playlist"

    @staticmethod
    def _outtmpl(output_path: str, url: str, clip: Optional[Tuple[float, Optional[float]]],
                 filename: Optional[str] = None) -> str:
        custom = filename.replace('%', '%%') if filename else None
        if custom and DownloadEngine.is_playlist_url(url):
            # A custom name on a playlist names its folder.
            return os.path.join(output_path, custom, '%(playlist_index)03d - ' + _OUTTMPL)
        if custom:
            return os.path.join(output_path, custom + '.%(ext)s')
        name = _OUTTMPL
        if clip:
            start, end = clip
            label = f"{format_timestamp(start)}-{format_timestamp(end) if end else 'end'}"
            # Distinct filename so a clip never overwrites the full download.
            # ':' isn't allowed in Windows names; '%' must be escaped for yt-dlp.
            name = f"%(title).160B (clip {label.replace(':', '.')}).%(ext)s"
        if DownloadEngine.is_playlist_url(url):
            # Playlists go into their own folder, numbered in playlist order.
            name = os.path.join('%(playlist_title).100B', '%(playlist_index)03d - ' + name)
        return os.path.join(output_path, name)

    def _build_opts(
        self,
        output_path: str,
        format_mode: str,
        quality: str,
        attempt: str,
        use_aria2c: bool,
        download_subtitles: bool,
        subtitle_language: str,
        url: str = "",
        embed_metadata: bool = False,
        clip: Optional[Tuple[float, Optional[float]]] = None,
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """yt-dlp options for one download attempt."""
        mode = FormatManager.normalize_mode(format_mode)
        is_video = FormatManager.is_video(mode)

        ydl_opts: Dict[str, Any] = {
            **self._common_opts(),
            'outtmpl': self._outtmpl(output_path, url, clip, filename),
            'progress_hooks': [self._progress_hook],
            'post_hooks': [self._post_hook],
            'concurrent_fragment_downloads': DEFAULT_CONCURRENT_FRAGMENTS,
            'http_chunk_size': DEFAULT_HTTP_CHUNK_SIZE,
            'socket_timeout': DEFAULT_SOCKET_TIMEOUT,
            'retries': DEFAULT_RETRIES,
            'fragment_retries': DEFAULT_RETRIES,
            'file_access_retries': DEFAULT_RETRIES,
            'buffersize': 1024 * 1024,
            'quiet': False,
            'no_warnings': False,
            'noprogress': False,
        }

        if attempt == _PRIMARY:
            ydl_opts.update(FormatManager.get_selection(mode, quality))
        elif attempt == _BEST:
            ydl_opts['format'] = "bestvideo*+bestaudio/best" if is_video else "bestaudio/best"
        else:  # _PROGRESSIVE: one muxed file — works even when DASH is SABR-gated.
            ydl_opts['format'] = "best[vcodec!=none][acodec!=none]/18/best"

        if clip:
            start, end = clip
            ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(
                None, [(start, end if end is not None else float('inf'))])
            # Accurate cuts. Required for audio too: without it ffmpeg's input
            # seek on YouTube's audio streams is ignored and the clip starts at 0.
            ydl_opts['force_keyframes_at_cuts'] = True
            use_aria2c = False  # sections are fetched by ffmpeg, not aria2c

        # aria2c (parallel connections) only on the first try; it's flaky
        # against YouTube's CDN (e.g. "exited with code 22").
        if use_aria2c:
            ydl_opts['external_downloader'] = 'aria2c'
            ydl_opts['external_downloader_args'] = {
                'aria2c': [
                    '-x', '16', '-s', '16', '-k', '1M',
                    '--min-split-size=1M',
                    '--max-connection-per-server=16',
                    '--file-allocation=none',
                ]
            }

        postprocessors: List[Dict[str, Any]] = []
        if mode == VIDEO_MP4:
            ydl_opts['merge_output_format'] = 'mp4'
        elif mode == VIDEO_MOV:
            # Merge into MKV (accepts any codec); _finalize_mov then remuxes or
            # re-encodes it into a QuickTime-compatible .mov.
            ydl_opts['merge_output_format'] = 'mkv'
        elif mode == AUDIO_WAV:
            codec, rate = FormatManager.get_wav_spec(quality)
            postprocessors.append({'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav'})
            pcm_args = ['-c:a', codec] + (['-ar', str(rate)] if rate else [])
            ydl_opts['postprocessor_args'] = {'extractaudio+ffmpeg_o': pcm_args}
        else:  # MP3
            postprocessors.append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': FormatManager.get_audio_quality_value(quality),
            })

        if embed_metadata and self.ffmpeg_path:
            # Title / artist / date / description tags (+ chapters for video).
            postprocessors.append({'key': 'FFmpegMetadata', 'add_metadata': True,
                                   'add_chapters': is_video})
            # Cover art where the container supports it (WAV can't carry it, and
            # MOV is rebuilt from an MKV, which would drop it).
            if mode not in (AUDIO_WAV, VIDEO_MOV):
                ydl_opts['writethumbnail'] = True
                postprocessors.insert(0, {'key': 'FFmpegThumbnailsConvertor',
                                          'format': 'jpg', 'when': 'before_dl'})
                postprocessors.append({'key': 'EmbedThumbnail', 'already_have_thumbnail': False})

        if download_subtitles:
            postprocessors.append({'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'})
            ydl_opts['writesubtitles'] = True
            ydl_opts['writeautomaticsub'] = True
            ydl_opts['subtitleslangs'] = [subtitle_language]

        if postprocessors:
            ydl_opts['postprocessors'] = postprocessors
        return ydl_opts

    # ----- download --------------------------------------------------------

    def download(
        self,
        url: str,
        output_path: str,
        format_mode: str,
        quality: str,
        download_subtitles: bool = False,
        subtitle_language: str = "en",
        use_aria2c: bool = False,
        embed_metadata: bool = True,
        clip_start: Optional[float] = None,
        clip_end: Optional[float] = None,
        filename: Optional[str] = None,
    ) -> bool:
        """
        Download video or audio, falling back automatically when needed:
        aria2c failure -> built-in downloader; SABR/403 -> progressive ~360p;
        (aria2c is opt-in: it reports no progress, so the UI can't show a bar or
        cancel mid-download, and it wasn't faster than yt-dlp's own downloader);
        "format not available" -> best available.

        Returns:
            True on success, False if cancelled or the URL is invalid.

        Raises:
            Exception with a user-readable message on failure.
        """
        is_valid, error_msg = validate_youtube_url(url)
        if not is_valid:
            self.logger.error(f"Invalid URL: {error_msg}")
            return False

        mode = FormatManager.normalize_mode(format_mode)
        if FormatManager.needs_ffmpeg(mode) and not self.ffmpeg_path:
            raise Exception(f"FFmpeg is required for {FormatManager.label(mode)} downloads. "
                            "Install it and add it to your PATH.")

        self.cancelled = False
        self.downloaded_files = []
        use_aria2c = use_aria2c and self._check_aria2c_available()
        clip = (clip_start or 0.0, clip_end) if (clip_start or clip_end) else None
        attempt = _PRIMARY

        while True:
            ydl_opts = self._build_opts(
                output_path, mode, quality, attempt, use_aria2c,
                download_subtitles, subtitle_language,
                url=url, embed_metadata=embed_metadata, clip=clip, filename=filename,
            )
            try:
                self._run(url, ydl_opts, mode)
                self.logger.info(f"Successfully downloaded ({attempt}): {url}")
                return True

            except (_DownloadCancelled, ConversionCancelled):
                self.logger.info("Download cancelled by user")
                self._cleanup_partials()
                return False

            except ConversionError as e:
                self._cleanup_partials()
                self.logger.error(str(e))
                raise Exception(str(e))

            except yt_dlp.utils.DownloadError as e:
                self._cleanup_partials()
                if self.cancelled:
                    return False
                msg = self._clean_error_message(str(e))

                friendly = self._friendly_error(msg)
                if friendly:
                    self.logger.error(f"Download error: {msg}")
                    raise Exception(friendly)

                if use_aria2c and ("aria2c" in msg.lower() or "exited with code" in msg.lower()):
                    self.logger.warning(f"aria2c failed ({msg}); retrying without it")
                    use_aria2c = False
                    continue

                # Clips are cut by ffmpeg reading the stream URLs itself. When
                # YouTube refuses those (403, typically without sign-in) yt-dlp
                # only reports "ffmpeg exited with code N", so treat an ffmpeg
                # failure on a clip like the 403 it usually is.
                clip_ffmpeg_failed = bool(clip) and "ffmpeg exited with code" in msg.lower()
                if clip_ffmpeg_failed and attempt == _PROGRESSIVE:
                    self.logger.error(f"Clip download failed: {msg}")
                    raise Exception(
                        "Couldn't download this clip. YouTube may need you to sign in for it: "
                        "add a cookies.txt in Settings, or download the whole video instead."
                    )

                if self._is_sabr_block(msg) or clip_ffmpeg_failed:
                    if attempt != _PROGRESSIVE:
                        # YouTube is gating the high-quality (DASH) formats behind
                        # SABR / bot-check auth, so their URLs 403. The progressive
                        # single-file format is usually still served (~360p).
                        self.logger.warning(
                            f"High-quality formats are restricted ({msg}); "
                            f"falling back to the best progressive format"
                        )
                        attempt = _PROGRESSIVE
                        continue
                    raise Exception(
                        "YouTube requires sign-in for this video's downloadable formats. "
                        "Add a cookies.txt file in Settings to download it."
                    )

                if attempt == _PRIMARY and "Requested format is not available" in msg:
                    self.logger.warning(f"Requested format not available, retrying with best: {msg}")
                    attempt = _BEST
                    continue

                self.logger.error(f"Download error: {msg}")
                raise Exception(msg)

            except Exception as e:
                self._cleanup_partials()
                if self.cancelled:
                    return False
                self.logger.error(f"Unexpected error during download: {e}", exc_info=True)
                raise

            finally:
                self.ydl_instance = None

    def _run(self, url: str, ydl_opts: Dict[str, Any], mode: str) -> None:
        """One yt-dlp attempt, plus MOV finalization."""
        self._partial_files.clear()
        self.downloaded_files = []
        self.ydl_instance = yt_dlp.YoutubeDL(ydl_opts)
        if self.cancelled:
            raise _DownloadCancelled()
        with self.ydl_instance as ydl:
            ydl.download([url])
        self._partial_files.clear()  # Files were finalized; nothing to clean.
        if mode == VIDEO_MOV:
            self._finalize_mov()

    def _finalize_mov(self) -> None:
        """Turn each downloaded file into an H.264/AAC .mov."""
        finished = []
        for path in self.downloaded_files:
            if not os.path.exists(path):
                continue
            try:
                finished.append(to_quicktime_mov(
                    path, self.ffmpeg_path,
                    is_cancelled=lambda: self.cancelled,
                    on_progress=self._report_conversion,
                ))
            except ConversionCancelled:
                self._partial_files.add(path)  # user cancelled: drop the intermediate too
                raise
            except ConversionError as e:
                # Keep the good download rather than throwing it away.
                raise ConversionError(f"{e}\nThe video was kept as {os.path.basename(path)}.")
        self.downloaded_files = finished

    def _report_conversion(self, fraction: float, action: str) -> None:
        if self.progress_callback:
            self.progress_callback({'status': 'converting', 'progress': fraction, 'action': action})

    @staticmethod
    def _friendly_error(msg: str) -> Optional[str]:
        """Map well-known terminal yt-dlp errors to short messages."""
        if "Private video" in msg:
            return "This video is private or unavailable"
        if "Video unavailable" in msg:
            return "Video is unavailable or has been removed"
        if "Sign in to confirm your age" in msg:
            return "This video requires age verification (add a cookies.txt in Settings)"
        if "not a bot" in msg:
            return "YouTube wants to confirm you're not a bot. Add a cookies.txt file in Settings."
        return None

    @staticmethod
    def _is_sabr_block(error_msg: str) -> bool:
        """Detect YouTube's SABR / bot-check gating of high-quality format URLs."""
        msg = error_msg.lower()
        return any(s in msg for s in (
            "403", "forbidden", "sabr", "missing a url",
            "downloaded file is empty", "unable to download video data",
        ))

    def _progress_hook(self, d: Dict[str, Any]) -> None:
        """Internal progress hook: tracks temp files, honors cancellation, relays progress."""
        # Remember the in-progress temp file so we can clean it up on abort.
        tmp = d.get('tmpfilename')
        if tmp:
            self._partial_files.add(tmp)

        # Aborting from the hook is the reliable cross-version way to actually
        # stop an in-flight download (the YoutubeDL.cancel() API isn't universal).
        if self.cancelled:
            raise _DownloadCancelled()

        if self.progress_callback:
            try:
                self.progress_callback(d)
            except Exception as e:
                # A UI bug must never abort the download itself.
                self.logger.debug(f"Progress callback error: {e}")

    def _post_hook(self, filepath: str) -> None:
        """Called by yt-dlp with each final file path after post-processing."""
        self.downloaded_files.append(filepath)

    def cancel(self) -> None:
        """Cancel ongoing download. The progress hook (or ffmpeg loop) performs the abort."""
        self.cancelled = True
        # Older/newer yt-dlp builds may not expose cancel(); call it only if present.
        cancel_method = getattr(self.ydl_instance, 'cancel', None)
        if callable(cancel_method):
            try:
                cancel_method()
            except (AttributeError, RuntimeError) as e:
                self.logger.warning(f"Error cancelling download: {e}")

    def _cleanup_partials(self) -> None:
        """Remove any temp/.part files left behind by an aborted or failed download."""
        for path in list(self._partial_files):
            try:
                if os.path.exists(path):
                    os.remove(path)
                    self.logger.debug(f"Removed partial file: {path}")
            except OSError as e:
                self.logger.debug(f"Could not remove partial file {path}: {e}")
        self._partial_files.clear()

    def _check_aria2c_available(self) -> bool:
        """Check if aria2c is available in PATH for faster downloads."""
        return shutil.which('aria2c') is not None

    def _get_js_runtime(self) -> Optional[Dict[str, Dict]]:
        """
        Check for available JavaScript runtimes needed for YouTube n-parameter decryption.
        Without a JS runtime, YouTube downloads will be throttled.

        Returns:
            JS runtimes dict for yt-dlp in format {runtime: {config}} or None if not available
        """
        runtimes: Dict[str, Dict] = {}

        # Deno is preferred by yt-dlp. paths.setup_tool_path() (run at startup)
        # puts the bundled copy and ~/.deno/bin first on PATH.
        deno_path = shutil.which('deno')
        if deno_path:
            runtimes['deno'] = {'path': deno_path}
        if shutil.which('node'):
            runtimes['node'] = {}
        if shutil.which('bun'):
            runtimes['bun'] = {}

        if runtimes:
            return runtimes

        self.logger.warning(
            "No JavaScript runtime found (deno, node, bun). "
            "YouTube downloads may be throttled. Install Deno for faster downloads: "
            "https://deno.land/manual/getting_started/installation"
        )
        return None

    def _clean_error_message(self, error_msg: str) -> str:
        """Remove ANSI escape codes from yt-dlp error messages."""
        return _ANSI_ESCAPE.sub('', error_msg)
