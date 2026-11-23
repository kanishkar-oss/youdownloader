"""Download queue management"""
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import List, Optional, Callable
from datetime import datetime

from src.models.download import DownloadItem, DownloadStatus
from src.utils.logger import get_logger
from src.downloader.engine import DownloadEngine

logger = get_logger()


def progress_fraction(d: dict) -> Optional[float]:
    """Fraction complete from a yt-dlp progress dict, or None if unknown.

    yt-dlp may include 'total_bytes' with a None value, so test values, not keys.
    """
    total = d.get('total_bytes') or d.get('total_bytes_estimate')
    done = d.get('downloaded_bytes') or 0
    if not total:
        return None
    return max(0.0, min(1.0, done / total))


class DownloadQueue:
    """Manages download queue with persistence"""

    def __init__(self, queue_file: Optional[str] = None):
        """
        Initialize download queue.

        Args:
            queue_file: Path to queue persistence file
        """
        if queue_file is None:
            from src.utils import paths
            queue_dir = Path(paths.config_dir())
            queue_dir.mkdir(parents=True, exist_ok=True)
            queue_file = str(queue_dir / "queue.json")

        self.queue_file = Path(queue_file)
        self._queue: List[DownloadItem] = []
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()  # Separate lock for file I/O
        self._current_download: Optional[DownloadItem] = None
        self._engine: Optional[DownloadEngine] = None
        self._download_thread: Optional[threading.Thread] = None
        self._status_callback: Optional[Callable] = None
        # Set by stop() / pause(): finish/cancel the current item and don't start the next.
        self._stop_requested = False
        # Set by pause(): the cancelled current item goes back to waiting, not "Cancelled".
        self._requeue_current = False
        # Bounds concurrent metadata prefetches so a long queue can't fan out an
        # unbounded number of network threads. Daemon threads keep app exit fast.
        self._prefetch_semaphore = threading.Semaphore(2)
        # Set by the app from Config["js_runtime_consent"]; gates the remote
        # JS-runtime speed path for downloads started from the queue.
        self.allow_remote_components = False
        # Set by the app from Config["cookies_file"]; enables authenticated downloads.
        self.cookie_file = None
        # Mirrors of the app's download settings, applied when an item starts.
        self.embed_metadata = True
        self.download_subtitles = False
        self.subtitle_language = "en"
        self.logger = logger
        self.load()

    def set_status_callback(self, callback: Callable) -> None:
        """Set callback for queue status updates.

        It may be called from worker threads, so it must only flag the UI for a
        refresh (never touch widgets directly).
        """
        self._status_callback = callback

    def _notify(self) -> None:
        if self._status_callback:
            try:
                self._status_callback()
            except Exception as e:
                self.logger.error(f"Error in status callback: {e}")

    def _save_async(self) -> None:
        """Save queue to file asynchronously (non-blocking)"""
        threading.Thread(target=self.save, daemon=True).start()

    def add(self, item: DownloadItem) -> None:
        """Add item to queue (non-blocking - saves asynchronously)."""
        with self._lock:
            self._queue.append(item)
        self.logger.info(f"Added to queue: {item.url}")
        if not item.title:  # so the row shows a title, not the link
            self._prefetch_metadata(item)
        self._save_async()
        self._notify()

    def remove(self, index: int) -> bool:
        """Remove item from queue by index. Returns True if removed."""
        with self._lock:
            if not (0 <= index < len(self._queue)):
                return False
            if self._queue[index] is self._current_download:
                return False  # Never yank the item that's downloading.
            item = self._queue.pop(index)
        self.logger.info(f"Removed from queue: {item.url}")
        self._save_async()
        self._notify()
        return True

    def reorder(self, old_index: int, new_index: int) -> bool:
        """Reorder queue items. Returns True if reordered."""
        with self._lock:
            if not (0 <= old_index < len(self._queue) and 0 <= new_index < len(self._queue)):
                return False
            item = self._queue.pop(old_index)
            self._queue.insert(new_index, item)
        self._save_async()
        self._notify()
        return True

    def get_all(self) -> List[DownloadItem]:
        """Get all queue items"""
        with self._lock:
            return self._queue.copy()

    def get_pending(self) -> List[DownloadItem]:
        """Get all pending items"""
        with self._lock:
            return [item for item in self._queue if item.status == DownloadStatus.PENDING]

    def get_waiting(self) -> List[DownloadItem]:
        """Items not started yet: pending (automatic) and held (added without starting)."""
        with self._lock:
            return [item for item in self._queue
                    if item.status in (DownloadStatus.PENDING, DownloadStatus.PAUSED)]

    def index_of(self, item: DownloadItem) -> int:
        """Position of this exact item (by identity), or -1."""
        with self._lock:
            return next((i for i, it in enumerate(self._queue) if it is item), -1)

    @property
    def current(self) -> Optional[DownloadItem]:
        return self._current_download

    def is_running(self) -> bool:
        return self._current_download is not None

    def clear_completed(self) -> int:
        """Clear finished (completed/failed/cancelled) items. Returns number removed."""
        with self._lock:
            initial_count = len(self._queue)
            self._queue = [
                item for item in self._queue
                if item.status not in (DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED)
            ]
            removed = initial_count - len(self._queue)
        if removed:
            self._save_async()
        return removed

    def start_all(self) -> bool:
        """Release held items too, then start. Returns True if one started."""
        with self._lock:
            for item in self._queue:
                if item.status == DownloadStatus.PAUSED:
                    item.status = DownloadStatus.PENDING
        self._save_async()
        return self.start()

    def start_item(self, item: DownloadItem) -> bool:
        """Make this item the next to download (now, if nothing is running).

        Works for waiting, held, failed and cancelled items. Returns False if
        the item isn't in the list or is downloading / done.
        """
        with self._lock:
            idx = next((i for i, it in enumerate(self._queue) if it is item), -1)
            if idx < 0 or item.status in (DownloadStatus.DOWNLOADING, DownloadStatus.COMPLETED):
                return False
            item.status = DownloadStatus.PENDING
            item.progress = 0.0
            item.speed = 0.0
            item.error_message = None
            # Ahead of every other waiting item (the list keeps its order otherwise).
            first = next((i for i, it in enumerate(self._queue)
                          if it.status == DownloadStatus.PENDING and it is not item), None)
            if first is not None and first < idx:
                self._queue.pop(idx)
                self._queue.insert(first, item)
        self._save_async()
        self._notify()
        self.start()
        return True

    def retry(self, index: int) -> bool:
        """Reset a failed/cancelled item back to pending."""
        with self._lock:
            if not (0 <= index < len(self._queue)):
                return False
            item = self._queue[index]
            if item.status not in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
                return False
            item.status = DownloadStatus.PENDING
            item.progress = 0.0
            item.speed = 0.0
            item.error_message = None
        self._save_async()
        self._notify()
        return True

    def start(self) -> bool:
        """Start (or resume) processing pending items. Returns True if one started."""
        self._stop_requested = False
        return self.start_next()

    def stop(self) -> None:
        """Cancel the current download and stop processing the queue."""
        self._stop_requested = True
        self.cancel_current()

    def pause(self) -> None:
        """Stop processing; the current download goes back to waiting (start() restarts it)."""
        self._stop_requested = True
        item, engine = self._current_download, self._engine
        if item is None:
            return
        self._requeue_current = True
        if engine:
            engine.cancel()
        self._notify()

    def is_paused(self) -> bool:
        """Stopped by stop() / pause() with items still waiting."""
        return self._stop_requested and not self.is_running() and bool(self.get_pending())

    def start_next(self) -> bool:
        """
        Start next pending download.

        Returns:
            True if started, False if no pending items, already running, or stopped
        """
        if self._stop_requested:
            return False
        with self._lock:
            if self._current_download is not None:
                return False
            pending = [i for i in self._queue if i.status == DownloadStatus.PENDING]
            if not pending:
                return False
            item = pending[0]
            item.status = DownloadStatus.DOWNLOADING
            item.progress = 0.0
            item.error_message = None
            self._current_download = item

        # Pre-fetch metadata for next item in queue (optimization)
        if len(pending) > 1 and not pending[1].title:
            self._prefetch_metadata(pending[1])

        engine = DownloadEngine(
            allow_remote_components=self.allow_remote_components,
            cookie_file=self.cookie_file,
        )

        def progress_callback(d: dict) -> None:
            if item.status != DownloadStatus.DOWNLOADING:
                return
            status = d.get('status')
            if status == 'downloading':
                fraction = progress_fraction(d)
                if fraction is not None:
                    item.progress = fraction
                item.downloaded_bytes = d.get('downloaded_bytes') or 0
                item.file_size = d.get('total_bytes') or d.get('total_bytes_estimate')
                item.speed = d.get('speed') or 0.0
                item.eta = d.get('eta')
                info = d.get('info_dict') or {}
                # Video and audio arrive as separate streams; say which one this is.
                item.stage = ("Audio" if info.get('vcodec') == 'none' else
                              "Video" if info.get('acodec') == 'none' else "Downloading")
            elif status == 'finished':
                # One stream is done (video and audio arrive separately);
                # merging/conversion still follows, so this isn't completion.
                item.progress = 1.0
                item.speed = 0.0
                item.stage = "Processing"
            elif status == 'converting':
                item.progress = d.get('progress', 0.0)
                item.speed = 0.0
                item.stage = d.get('action', "Converting")
            self._notify()

        engine.progress_callback = progress_callback

        def download_thread():
            try:
                success = engine.download(
                    url=item.url,
                    output_path=item.output_path,
                    format_mode=item.format,
                    quality=item.quality,
                    embed_metadata=self.embed_metadata,
                    download_subtitles=self.download_subtitles,
                    subtitle_language=self.subtitle_language,
                    clip_start=item.clip_start,
                    clip_end=item.clip_end,
                    filename=item.custom_name,
                )
                if success:
                    item.status = DownloadStatus.COMPLETED
                    item.progress = 1.0
                    item.completed_at = datetime.now()
                    if engine.downloaded_files:
                        item.file_path = engine.downloaded_files[-1]
                    item.file_count = len(engine.downloaded_files)
                    if not item.title and item.file_path and item.file_count == 1:
                        item.title = os.path.splitext(os.path.basename(item.file_path))[0]
                elif engine.cancelled:
                    item.status = self._cancelled_status()
                else:
                    item.status = DownloadStatus.FAILED
                    item.error_message = "Download failed"
            except Exception as e:
                if engine.cancelled:
                    item.status = self._cancelled_status()
                else:
                    item.status = DownloadStatus.FAILED
                    item.error_message = str(e)
                    self.logger.error(f"Download failed: {e}")
            finally:
                item.speed = 0.0
                item.stage = None
                if item.status == DownloadStatus.PENDING:
                    item.progress = 0.0
                with self._lock:
                    if self._current_download is item:
                        self._current_download = None
                    self._engine = None if self._engine is engine else self._engine
                self.save()
                self._notify()
                self.start_next()

        self._engine = engine
        self._download_thread = threading.Thread(target=download_thread, daemon=True)
        self._download_thread.start()
        self._save_async()
        self._notify()
        return True

    def _cancelled_status(self) -> DownloadStatus:
        if self._requeue_current:
            self._requeue_current = False
            return DownloadStatus.PENDING
        return DownloadStatus.CANCELLED

    def cancel_current(self) -> bool:
        """
        Cancel current download. The worker thread records CANCELLED once the
        engine has actually stopped.

        Returns:
            True if a download was being cancelled, False if none was active
        """
        item, engine = self._current_download, self._engine
        if item is None:
            return False
        self._requeue_current = False
        if engine:
            engine.cancel()
        item.status = DownloadStatus.CANCELLED
        self._notify()
        return True

    def save(self) -> None:
        """
        Save queue to file atomically (thread-safe, callable from any thread).

        Snapshots under the main lock, then writes to a temp file and os.replace()s
        it into place so a crash mid-write can't corrupt queue.json.
        """
        try:
            with self._save_lock:
                with self._lock:
                    data = [item.to_dict() for item in self._queue]

                payload = json.dumps(data, indent=2, ensure_ascii=False)
                fd, tmp_path = tempfile.mkstemp(
                    dir=self.queue_file.parent, prefix=".queue-", suffix=".tmp"
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(payload)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, self.queue_file)
                except BaseException:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                    raise
        except Exception as e:
            self.logger.error(f"Error saving queue: {e}")

    def load(self) -> None:
        """Load queue from file"""
        if not self.queue_file.exists():
            return

        try:
            with open(self.queue_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            with self._lock:
                self._queue = [DownloadItem.from_dict(item) for item in data]
                # Items interrupted by a crash/exit go back to pending.
                for item in self._queue:
                    if item.status == DownloadStatus.DOWNLOADING:
                        item.status = DownloadStatus.PENDING
                        item.progress = 0.0
        except Exception as e:
            self.logger.error(f"Error loading queue: {e}")

    def _prefetch_metadata(self, item: DownloadItem) -> None:
        """Pre-fetch a pending item's title in the background."""
        def prefetch_thread():
            # Cap concurrent prefetches; daemon threads still let the app exit fast.
            with self._prefetch_semaphore:
                try:
                    engine = DownloadEngine(
                        allow_remote_components=self.allow_remote_components,
                        cookie_file=self.cookie_file,
                    )
                    info = engine.get_video_info(item.url)
                    if info and info.get('title'):
                        item.title = info['title']
                        self._notify()
                except Exception as e:
                    self.logger.debug(f"Error pre-fetching metadata: {e}")

        threading.Thread(target=prefetch_thread, daemon=True).start()
