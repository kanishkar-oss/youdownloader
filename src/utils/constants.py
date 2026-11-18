"""Constants for YouDownloader"""
# Animation constants
ANIMATION_INTERPOLATION_FACTOR = 0.15
ANIMATION_FPS = 60
ANIMATION_INTERVAL_MS = 1000 // ANIMATION_FPS  # ~16ms

# Download constants
DEFAULT_CONCURRENT_FRAGMENTS = 16  # Aggressive parallelization for max speed
MAX_CONCURRENT_FRAGMENTS = 16
DEFAULT_HTTP_CHUNK_SIZE = 20971520  # 20MB for better throughput
DEFAULT_SOCKET_TIMEOUT = 30
DEFAULT_RETRIES = 3
ADAPTIVE_CHUNK_SIZE = True
CONNECTION_POOL_SIZE = 10
SPEED_MONITORING_INTERVAL = 1.0  # seconds

# yt-dlp "remote components" let it fetch the JS challenge solver that defeats
# YouTube's n-parameter throttling. This downloads and runs code from GitHub at
# download time, so it is only enabled after explicit user consent (see
# Config["js_runtime_consent"]). Centralized here so the source can be pinned to
# an audited revision — yt-dlp accepts an "ejs:github@<commit-sha>" form; pin it
# to a reviewed SHA before shipping to lock the fetched code to a known version.
REMOTE_COMPONENTS_SPEC = "ejs:github"

# UI constants
LOGO_MAX_SIZE = (200, 120)
DEFAULT_WINDOW_WIDTH = 650
DEFAULT_WINDOW_HEIGHT = 600

# File constants
MAX_FILENAME_LENGTH = 200
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5

# Format constants
DEFAULT_VIDEO_QUALITY = "1080p"
DEFAULT_AUDIO_QUALITY = "Best (320kbps)"
DEFAULT_FORMAT = "Video (MP4)"

# Theme constants
DEFAULT_THEME = "dark"

# Font constants
FONT_FAMILY = ("Inter", "Segoe UI", "system")
FONT_PRIMARY = FONT_FAMILY[0]  # Primary font (first in fallback chain)
FONT_SIZES = {
    "title": 28,
    "heading": 16,
    "body": 13,
    "small": 11
}

