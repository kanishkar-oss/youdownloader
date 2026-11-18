"""Configuration management for YouDownloader"""
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Dict, Any, Optional

from src.utils.logger import get_logger

logger = get_logger()


class Config:
    """Manages application configuration and user preferences"""

    DEFAULT_CONFIG = {
        "download_path": os.path.join(os.path.expanduser("~"), "Downloads"),
        "format": "Video (MP4)",
        "quality": "1080p",
        "theme": "midnight",  # Modern default; legacy tech/dark/light auto-migrate
        "window_width": 720,
        "window_height": 640,
        "window_x": None,
        "window_y": None,
        "ffmpeg_path": None,
        # Path to a Netscape cookies.txt for authenticated (full-quality) downloads.
        "cookies_file": "",
        "concurrent_downloads": 1,
        "auto_download_subtitles": False,
        "subtitle_language": "en",
        "notifications_enabled": True,
        # New speed optimization settings
        "max_concurrent_fragments": 16,
        "http_chunk_size": 20971520,  # 20MB
        "adaptive_chunk_size": True,
        "visual_effects_enabled": True,  # Enable/disable animations
        # Dismissable setup banners (persist so users aren't nagged each launch).
        "banner_dismissed_ffmpeg": False,
        "banner_dismissed_deno": False,
        # Tri-state consent for the remote JS-runtime speed path:
        #   None  -> not yet asked (prompt the user once)
        #   True  -> user opted into remote_components / fast downloads
        #   False -> user declined; downloads stay on safe defaults
        "js_runtime_consent": None,
        # Embed title/artist/date tags and cover art into downloads.
        "embed_metadata": True,
        "banner_dismissed_ytdlp": False,
        "window_maximized": False,
        # App self-update (packaged builds): check GitHub on launch, and the
        # version whose banner the user dismissed (Settings can still install it).
        "auto_check_updates": True,
        "skipped_update_version": None,
        # Set just before an update installs; the next launch checks it took.
        "pending_update_version": None,
    }

    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize configuration manager.

        Args:
            config_dir: Directory to store config file. Defaults to 'config' in app root.
        """
        if config_dir is None:
            # Project config/ from source; per-user app data when installed.
            from src.utils import paths
            self.config_dir = Path(paths.config_dir())
        else:
            self.config_dir = Path(config_dir)

        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "settings.json"
        self._config: Dict[str, Any] = {}
        # Reentrant: set()/update()/reset() acquire the lock and then call save(),
        # which acquires it again.
        self._lock = threading.RLock()
        self.load()

    def load(self) -> None:
        """Load configuration from file or create default"""
        with self._lock:
            if self.config_file.exists():
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        self._config = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    for key, value in self.DEFAULT_CONFIG.items():
                        if key not in self._config:
                            self._config[key] = value
                except (json.JSONDecodeError, IOError) as e:
                    logger.error(f"Error loading config: {e}. Using defaults.")
                    self._config = self.DEFAULT_CONFIG.copy()
                    self.save()
            else:
                self._config = self.DEFAULT_CONFIG.copy()
                self.save()

    def save(self) -> None:
        """
        Save configuration atomically.

        Writes to a temp file in the same directory and os.replace()s it over the
        target so a crash mid-write can never leave a half-written settings file.
        """
        with self._lock:
            data = json.dumps(self._config, indent=4, ensure_ascii=False)
            try:
                fd, tmp_path = tempfile.mkstemp(
                    dir=self.config_dir, prefix=".settings-", suffix=".tmp"
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(data)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, self.config_file)
                except BaseException:
                    # Don't leave the temp file behind on any failure.
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                    raise
            except OSError as e:
                logger.error(f"Error saving config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value.

        Args:
            key: Configuration key
            default: Default value if key doesn't exist

        Returns:
            Configuration value or default
        """
        with self._lock:
            return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value and save.

        Args:
            key: Configuration key
            value: Configuration value
        """
        with self._lock:
            self._config[key] = value
            self.save()

    def update(self, updates: Dict[str, Any]) -> None:
        """
        Update multiple configuration values at once.

        Args:
            updates: Dictionary of key-value pairs to update
        """
        with self._lock:
            self._config.update(updates)
            self.save()

    def reset(self) -> None:
        """Reset configuration to defaults"""
        with self._lock:
            self._config = self.DEFAULT_CONFIG.copy()
            self.save()

    def get_all(self) -> Dict[str, Any]:
        """Get all configuration as dictionary"""
        with self._lock:
            return self._config.copy()

