"""Isolated, offline demo data and a five-state visual seed."""

from __future__ import annotations

import os
import base64
import shutil
import tempfile
import zlib
from pathlib import Path

from . import db, library, settings, tagging
from .models import PlaylistMetadata, VideoMetadata

# A locally generated 0.3-second silent MP3, compressed so offline demo works
# without external tools. Its equalization flags are simulated, not real gain.
_SILENCE = "eNrzdDFmYQAB5ZDgYFcgzc/AwOyTWJZmaqpnaKJnaGDIgAD/fzswEAKeeWn5QIodiHkZGFj/MehDgCMUBEFBMgSUQkEbFEyHgJVQsAsKTkPAXSh4BwX/IQCre1UQrhZIYeD/wMCQCeRwAJ2lwMDACERLgFwg06SBgYHFx9HX1VjP0lLPNBQ7IKggNBRkjxIBe0IJASLtcaGTPWl0sqeDTvasopM9Zyi1hwgAsudu/6g9o/bQxx4AzAi54A=="


def seed(root: Path) -> dict[str, int]:
    """Seed four synthetic tracks plus one extra in the overridden data directory."""
    root.mkdir(parents=True, exist_ok=True)
    silent = root / "silence.mp3"
    silent.write_bytes(zlib.decompress(base64.b64decode(_SILENCE)))
    output_root = root / "library"
    settings.save(settings.Settings(output_root=str(output_root)))
    connection = db.connect()
    try:
        db.initialize(connection)
        videos = tuple(VideoMetadata(f"demo{i:07}", f"Demo track {i}", uploader="Demo Artist", duration_seconds=3, position=i - 1) for i in range(1, 5))
        playlist_id, _ = db.add_playlist(connection, "https://www.youtube.com/playlist?list=PL_DEMO_OFFLINE", PlaylistMetadata("Offline demo", videos), output_root)
        folder = output_root / "Offline demo"
        with connection:
            for index, video in enumerate(videos[:3], start=1):
                path = folder / f"Demo track {index}.mp3"
                shutil.copyfile(silent, path)
                tagging.tag_file(path, video.title, video.uploader, "Offline demo")
                connection.execute("UPDATE videos SET downloaded=1,equalized=?,file_path=?,file_size=?,updated_at=? WHERE playlist_id=? AND video_id=?", (int(index <= 2), str(path), path.stat().st_size, db.utc_now(), playlist_id, video.video_id))
        shutil.copyfile(silent, folder / "Extra file.mp3")
        scan = library.scan_folder(connection, playlist_id)
        for extra_id in scan.new_extra_ids:
            library.keep_extra(connection, extra_id)
        tracks = db.list_videos(connection, playlist_id)
        return {
            "green": sum(bool(track["downloaded"] and track["equalized"]) for track in tracks),
            "blue": sum(bool(track["downloaded"] and not track["equalized"]) for track in tracks),
            "red": sum(not track["downloaded"] for track in tracks),
            "yellow": len(library.list_extras(connection, playlist_id)),
        }
    finally:
        connection.close()


def run(check: bool = False) -> int:
    """Use a temporary data directory; restore the caller's environment on exit."""
    previous = os.environ.get("MP3PD_DATA_DIR")
    try:
        with tempfile.TemporaryDirectory(prefix="mp3pd-demo-") as directory:
            root = Path(directory)
            os.environ["MP3PD_DATA_DIR"] = str(root / "data")
            try:
                summary = seed(root)
            except (RuntimeError, OSError):
                print("Demo could not be created. Ensure temporary storage is writable.")
                return 2
            if check:
                print("Offline demo: " + ", ".join(f"{value} {key}" for key, value in summary.items()))
                return 0 if summary == {"green": 2, "blue": 1, "red": 1, "yellow": 1} else 2
            from .app import run as run_gui
            return run_gui()
    finally:
        if previous is None:
            os.environ.pop("MP3PD_DATA_DIR", None)
        else:
            os.environ["MP3PD_DATA_DIR"] = previous
