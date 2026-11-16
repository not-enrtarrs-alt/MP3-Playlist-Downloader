"""Shared immutable representations of fetched playlist metadata."""

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoMetadata:
    video_id: str
    title: str
    uploader: str | None = None
    duration_seconds: int | None = None
    thumbnail_url: str | None = None
    position: int = 0
    unavailable: bool = False
    is_topic: bool = False


@dataclass(frozen=True)
class PlaylistMetadata:
    title: str
    videos: tuple[VideoMetadata, ...]
