"""Offline end-to-end checks for official-title cleanup."""

import base64
import shutil
import zlib

from mutagen.id3 import ID3

from mp3_playlist_downloader import db, demo, paths, queue, tagging
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.ui.track_model import TrackModel
from mp3_playlist_downloader.youtube import download as downloader


def test_display_tags_filenames_and_db_keep_raw_titles(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    monkeypatch.setattr(tagging, "load_cover", lambda *args: None)
    fixture = tmp_path / "silent.mp3"
    fixture.write_bytes(zlib.decompress(base64.b64decode(demo._SILENCE)))
    titles = ("Ava Max - Catch My Breath (Official Audio)", "Ava Max - Catch My Breath [Official Lyric Video]")
    entries = tuple(VideoMetadata(f"video{i:06}", title, uploader="Ava Max", position=i) for i, title in enumerate(titles))
    connection = db.connect(tmp_path / "app.db")
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "url", PlaylistMetadata("Album", entries), tmp_path / "music")

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            shutil.copyfile(fixture, self.options["outtmpl"].replace("%(ext)s", "mp3"))

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    config = Settings()
    assert queue.enqueue_missing(connection, pid, config) == 2
    assert queue.run_queue(connection, config).downloaded == 2
    rows = db.list_videos(connection, pid)
    assert [row["title"] for row in rows] == list(titles)
    assert [row["file_path"].split("\\")[-1].split("/")[-1] for row in rows] == ["Catch My Breath.mp3", "Catch My Breath (2).mp3"]
    for row in rows:
        tags = ID3(row["file_path"])
        assert str(tags["TIT2"]) == "Catch My Breath"
        assert str(tags["TPE1"]) == "Ava Max"
        assert str(tags["TALB"]) == "Album"
    model = TrackModel()
    model.set_rows(rows)
    assert [model.index(index, 2).data() for index in range(2)] == ["Catch My Breath", "Catch My Breath"]
    connection.close()
