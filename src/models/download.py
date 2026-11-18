"""Download data models"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class DownloadStatus(Enum):
    """Download status enumeration"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class DownloadItem:
    """Represents a download item in the queue"""
    url: str
    title: Optional[str] = None
    format: str = "Video (MP4)"
    quality: str = "1080p"
    output_path: str = ""
    status: DownloadStatus = DownloadStatus.PENDING
    progress: float = 0.0
    file_size: Optional[int] = None
    downloaded_bytes: int = 0
    speed: float = 0.0
    eta: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    file_path: Optional[str] = None
    # Optional clip range in seconds (None = whole video / until the end).
    clip_start: Optional[float] = None
    clip_end: Optional[float] = None
    # User-chosen file name (no extension); None = use the video title.
    custom_name: Optional[str] = None
    # Transient UI hint ("Downloading", "Processing", "Converting…"); not persisted.
    stage: Optional[str] = field(default=None, compare=False)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return {
            "url": self.url,
            "title": self.title,
            "format": self.format,
            "quality": self.quality,
            "output_path": self.output_path,
            "status": self.status.value,
            "progress": self.progress,
            "file_size": self.file_size,
            "downloaded_bytes": self.downloaded_bytes,
            "speed": self.speed,
            "eta": self.eta,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "file_path": self.file_path,
            "clip_start": self.clip_start,
            "clip_end": self.clip_end,
            "custom_name": self.custom_name,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'DownloadItem':
        """Create from dictionary"""
        item = cls(
            url=data["url"],
            title=data.get("title"),
            format=data.get("format", "Video (MP4)"),
            quality=data.get("quality", "1080p"),
            output_path=data.get("output_path", ""),
            status=DownloadStatus(data.get("status", "pending")),
            progress=data.get("progress", 0.0),
            file_size=data.get("file_size"),
            downloaded_bytes=data.get("downloaded_bytes", 0),
            speed=data.get("speed", 0.0),
            eta=data.get("eta"),
            error_message=data.get("error_message"),
            file_path=data.get("file_path"),
            clip_start=data.get("clip_start"),
            clip_end=data.get("clip_end"),
            custom_name=data.get("custom_name"),
        )
        if "created_at" in data and data["created_at"]:
            item.created_at = datetime.fromisoformat(data["created_at"])
        if "completed_at" in data and data["completed_at"]:
            item.completed_at = datetime.fromisoformat(data["completed_at"])
        return item



