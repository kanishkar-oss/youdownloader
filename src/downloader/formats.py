"""Format and quality handling for downloads.

A *format mode* is the user-facing output choice and is what gets persisted in
settings.json / queue.json. The strings are stable identifiers — existing saved
values ("Video (MP4)", "Audio (MP3)") keep working.
"""
from typing import Any, Dict, List, Optional, Tuple

# Format-mode identifiers.
VIDEO_MP4 = "Video (MP4)"
VIDEO_MOV = "Video (MOV)"
AUDIO_MP3 = "Audio (MP3)"
AUDIO_M4A = "Audio (M4A)"
AUDIO_WAV = "Audio (WAV)"

# Standard resolution tiers as (short side, long side). A format belongs to the
# highest tier whose short OR long side it reaches, so letterboxed 1920x960,
# 4:3 1440x1080 and vertical 1080x1920 are all "1080p" — the way YouTube labels them.
_TIERS = (
    (2160, 3840), (1440, 2560), (1080, 1920), (720, 1280),
    (480, 854), (360, 640), (240, 426), (144, 256),
)


class FormatManager:
    """Manages video/audio format configurations"""

    # mode -> kind ("video"/"audio"), output extension, short UI label
    MODES: Dict[str, Dict[str, str]] = {
        VIDEO_MP4: {"kind": "video", "ext": "mp4", "label": "MP4"},
        VIDEO_MOV: {"kind": "video", "ext": "mov", "label": "MOV"},
        AUDIO_MP3: {"kind": "audio", "ext": "mp3", "label": "MP3"},
        AUDIO_M4A: {"kind": "audio", "ext": "m4a", "label": "M4A"},
        AUDIO_WAV: {"kind": "audio", "ext": "wav", "label": "WAV"},
    }
    DEFAULT_MODE = VIDEO_MP4

    # Video quality preset -> target height (None = best available).
    VIDEO_QUALITIES: Dict[str, Optional[int]] = {
        "Native (Max Quality)": None,
        "4K (2160p)": 2160,
        "1440p": 1440,
        "1080p": 1080,
        "720p": 720,
        "480p": 480,
    }

    # MP3 preset -> LAME bitrate (kbps) passed to FFmpegExtractAudio.
    MP3_QUALITIES: Dict[str, str] = {
        "Best (320kbps)": "320",
        "Standard (128kbps)": "128",
    }

    # M4A: YouTube's own AAC stream, saved without re-encoding (no quality loss).
    M4A_QUALITIES: Dict[str, None] = {
        "Original quality (no re-encode)": None,
    }

    # WAV preset -> (PCM codec, sample rate or None to keep the source rate).
    WAV_QUALITIES: Dict[str, Tuple[str, Optional[int]]] = {
        "16-bit / 44.1 kHz (CD)": ("pcm_s16le", 44100),
        "16-bit / original rate": ("pcm_s16le", None),
        "24-bit / 48 kHz (studio)": ("pcm_s24le", 48000),
    }

    # Legacy quality names from older settings/queue files.
    _LEGACY_QUALITY = {
        "High (1080p+)": "1080p",
        "Medium (720p)": "720p",
        "Low (480p)": "480p",
    }

    # ----- modes ---------------------------------------------------------

    @classmethod
    def normalize_mode(cls, format_mode: Optional[str]) -> str:
        """Return a known format mode, falling back to the default."""
        return format_mode if format_mode in cls.MODES else cls.DEFAULT_MODE

    @classmethod
    def is_video(cls, format_mode: str) -> bool:
        return cls.MODES[cls.normalize_mode(format_mode)]["kind"] == "video"

    @classmethod
    def extension(cls, format_mode: str) -> str:
        return cls.MODES[cls.normalize_mode(format_mode)]["ext"]

    @classmethod
    def label(cls, format_mode: str) -> str:
        """Short label for the UI, e.g. "MOV"."""
        return cls.MODES[cls.normalize_mode(format_mode)]["label"]

    @classmethod
    def labels(cls) -> List[str]:
        return [m["label"] for m in cls.MODES.values()]

    @classmethod
    def mode_from_label(cls, label: str) -> str:
        for mode, meta in cls.MODES.items():
            if meta["label"] == label:
                return mode
        return cls.DEFAULT_MODE

    @classmethod
    def needs_ffmpeg(cls, format_mode: str) -> bool:
        """MOV conversion and MP3/M4A/WAV extraction can't work without FFmpeg."""
        return cls.normalize_mode(format_mode) != VIDEO_MP4

    # ----- qualities -----------------------------------------------------

    @classmethod
    def get_quality_options(cls, format_mode: str) -> list:
        mode = cls.normalize_mode(format_mode)
        if cls.is_video(mode):
            return list(cls.VIDEO_QUALITIES)
        if mode == AUDIO_WAV:
            return list(cls.WAV_QUALITIES)
        if mode == AUDIO_M4A:
            return list(cls.M4A_QUALITIES)
        return list(cls.MP3_QUALITIES)

    @classmethod
    def normalize_quality(cls, format_mode: str, quality: Optional[str]) -> str:
        """Map legacy names and make sure the quality is valid for the mode."""
        quality = cls._LEGACY_QUALITY.get(quality, quality)
        options = cls.get_quality_options(format_mode)
        if quality in options:
            return quality
        if cls.is_video(format_mode) and "1080p" in options:
            return "1080p"
        return options[0]

    @classmethod
    def get_quality_height(cls, quality: str) -> Optional[int]:
        """Target height for a video preset (None = best available)."""
        quality = cls._LEGACY_QUALITY.get(quality, quality)
        return cls.VIDEO_QUALITIES.get(quality, 1080)

    @classmethod
    def get_audio_quality_value(cls, quality: str) -> str:
        """MP3 bitrate (kbps) for the preset."""
        return cls.MP3_QUALITIES.get(quality, "320")

    @classmethod
    def get_wav_spec(cls, quality: str) -> Tuple[str, Optional[int]]:
        return cls.WAV_QUALITIES.get(quality, next(iter(cls.WAV_QUALITIES.values())))

    # ----- yt-dlp selection ---------------------------------------------

    @classmethod
    def get_selection(cls, format_mode: str, quality: str) -> Dict[str, Any]:
        """
        yt-dlp 'format' + 'format_sort' options for a mode/quality.

        Resolution limits are expressed as a sort preference ("res:1080") rather
        than a hard filter, so a video that lacks the exact height still
        downloads (nearest smaller, else smallest larger) instead of failing
        with "Requested format is not available". 'res' is the smaller
        dimension, so vertical and letterboxed videos are handled correctly.
        """
        mode = cls.normalize_mode(format_mode)
        if mode == AUDIO_M4A:
            # The AAC (m4a) stream, so it's copied as-is; anything else is
            # converted to AAC only if a video has no AAC audio at all.
            return {"format": "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio/best"}
        if not cls.is_video(mode):
            # Best audio stream; MP3/WAV are transcoded from it anyway.
            return {"format": "bestaudio/best"}

        height = cls.get_quality_height(quality)
        res = f"res:{height}" if height else "res"
        if mode == VIDEO_MOV:
            # Prefer SDR, then H.264 + AAC at the chosen resolution, so the .mov
            # is a fast, lossless remux QuickTime / Final Cut / Premiere can open.
            # (HDR-only videos get tone-mapped during conversion.)
            sort = [res, "hdr:sdr", "+codec:avc:m4a"]
        else:
            sort = [res, "br"]
        return {"format": "bestvideo*+bestaudio/best", "format_sort": sort}

    @classmethod
    def get_fastest_format(cls, format_mode: str, quality: str) -> str:
        """Back-compat shim: the yt-dlp format string for a mode/quality."""
        return cls.get_selection(format_mode, quality)["format"]

    # ----- availability --------------------------------------------------

    @staticmethod
    def resolution_tier(width: Optional[int], height: Optional[int]) -> Optional[int]:
        """Classify a format's dimensions into a standard tier (e.g. 1920x960 -> 1080)."""
        w, h = width or 0, height or 0
        if not w and not h:
            return None
        short = min(w, h) if (w and h) else (h or w)
        long = max(w, h)
        for tier_short, tier_long in _TIERS:
            if short >= tier_short or long >= tier_long:
                return tier_short
        return short

    @staticmethod
    def _tier_label(tier: int) -> str:
        return "4K (2160p)" if tier >= 2160 else f"{tier}p"

    @classmethod
    def get_available_resolutions(cls, formats: List[Dict]) -> List[Tuple[int, str]]:
        """Available video tiers as (tier, label), highest first."""
        tiers = set()
        for fmt in formats:
            if fmt.get("vcodec") == "none":
                continue  # audio-only
            tier = cls.resolution_tier(fmt.get("width"), fmt.get("height"))
            if tier:
                tiers.add(tier)
        return [(t, cls._tier_label(t)) for t in sorted(tiers, reverse=True)]

    @classmethod
    def get_best_available_resolution(
        cls, formats: List[Dict], requested_quality: str
    ) -> Tuple[Optional[int], Optional[str], bool]:
        """
        Best available tier for a requested preset.

        Returns (tier, label, is_exact). "Native" is always exact.
        """
        available = cls.get_available_resolutions(formats)
        if not available:
            return None, None, False

        target = cls.get_quality_height(requested_quality)
        if target is None:
            tier, label = available[0]
            return tier, label, True

        for tier, label in available:
            if tier == target:
                return tier, label, True
        # Highest tier at or below the target, else the lowest one above it.
        below = [(t, l) for t, l in available if t <= target]
        tier, label = below[0] if below else available[-1]
        return tier, label, False
