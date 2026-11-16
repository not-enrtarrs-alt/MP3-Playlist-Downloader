"""Manual rename operations preserve user files and ID3 frames."""

import base64
import shutil
import zlib

import pytest
from mutagen.id3 import ID3, TXXX

from mp3_playlist_downloader import db, demo, library, services, tagging
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
from mp3_playlist_downloader.renaming import RenameCancelled, RenameError
from mp3_playlist_downloader.ui.track_model import TrackModel


@pytest.fixture
def track(tmp_path):
    connection = db.connect(tmp_path / "app.db")
    db.initialize(connection)
    metadata = PlaylistMetadata("Album", (VideoMetadata("aaaaaaaaaaa", "Artist - Song (Official Audio)", uploader="Artist"),))
    pid, _ = db.add_playlist(connection, "url", metadata, tmp_path / "music")
    folder = tmp_path / "music" / "Album"
    vid = db.list_videos(connection, pid)[0]["id"]
    yield connection, pid, vid, folder, tmp_path
    connection.close()


def make_downloaded(track, name="Original.mp3"):
    connection, pid, vid, folder, _ = track
    path = folder / name
    path.write_bytes(zlib.decompress(base64.b64decode(demo._SILENCE)))
    tagging.tag_file(path, "Song", "Artist", "Album", b"\xff\xd8\xffcover")
    tags = ID3(path)
    tags.add(TXXX(encoding=3, desc="Custom", text="keep"))
    tags.save(path, v2_version=3)
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,equalized=1,file_path=?,file_size=? WHERE id=?", (str(path), path.stat().st_size, vid))
    return path


def test_missing_track_override_survives_refresh(track):
    connection, pid, vid, folder, _ = track
    result = services.rename_track(connection, vid, "  My title  ")
    assert result.title == "My title" and result.file_path is None
    db.refresh_playlist(connection, pid, PlaylistMetadata("Album", (VideoMetadata("aaaaaaaaaaa", "New raw title", uploader="Artist"),)))
    row = db.list_videos(connection, pid)[0]
    assert row["title"] == "New raw title" and row["custom_title"] == "My title"
    model = TrackModel()
    model.set_rows([row])
    assert model.index(0, 2).data() == "My title" and not list(folder.iterdir())


def test_downloaded_rename_preserves_metadata_and_equalization(track):
    connection, pid, vid, folder, root = track
    original = make_downloaded(track)
    original_bytes = original.read_bytes()
    recycled = root / "recycled.mp3"
    result = services.rename_track(connection, vid, "My title", recycle=lambda path: shutil.move(path, recycled))
    assert result.file_path == folder / "My title.mp3" and result.warning is None
    assert not original.exists() and recycled.read_bytes() == original_bytes
    row = db.list_videos(connection, pid)[0]
    assert row["title"] == "Artist - Song (Official Audio)" and row["custom_title"] == "My title"
    assert row["file_path"] == str(result.file_path) and row["equalized"] == row["downloaded"] == 1
    tags = ID3(result.file_path)
    assert tags.version == (2, 3, 0) and str(tags["TIT2"]) == "My title"
    assert str(tags["TPE1"]) == "Artist" and str(tags["TALB"]) == "Album"
    assert tags.getall("APIC")[0].data == b"\xff\xd8\xffcover" and tags.getall("TXXX")[0].text == ["keep"]
    assert not list(folder.glob(".tmp-*"))


def test_rename_never_overwrites_unrelated_collision(track):
    connection, pid, vid, folder, root = track
    make_downloaded(track)
    unrelated = folder / "My title.mp3"
    unrelated.write_bytes(b"user file")
    result = services.rename_track(connection, vid, "My title", recycle=lambda path: shutil.move(path, root / "recycled.mp3"))
    assert unrelated.read_bytes() == b"user file" and result.file_path.name == "My title (2).mp3"


def test_tag_failure_leaves_original_and_database_untouched(track, monkeypatch):
    connection, pid, vid, folder, _ = track
    original = make_downloaded(track)
    before = original.read_bytes()
    def fail(*args):
        raise OSError("private path")
    monkeypatch.setattr(tagging, "retag_title", fail)
    calls = []
    with pytest.raises(RenameError, match="original is unchanged"):
        services.rename_track(connection, vid, "New", recycle=calls.append)
    row = db.list_videos(connection, pid)[0]
    assert original.read_bytes() == before and row["custom_title"] is None and row["file_path"] == str(original)
    assert not calls and not list(folder.glob(".tmp-*"))


def test_recycle_failure_keeps_original_as_reviewable_extra(track):
    connection, pid, vid, folder, _ = track
    original = make_downloaded(track)
    before = original.read_bytes()
    def fail(path):
        raise OSError("recycle failure")
    result = services.rename_track(connection, vid, "New", recycle=fail)
    assert result.warning and result.file_path.is_file() and not original.exists()
    extras = library.scan_folder(connection, pid)
    assert len(extras.new_extra_ids) == 1
    extra = library.list_extras(connection, pid)[0]
    from pathlib import Path
    assert Path(extra["file_path"]).read_bytes() == before


@pytest.mark.parametrize("same_filename", [False, True])
def test_db_failure_restores_original_and_preserves_copy(track, same_filename):
    connection, pid, vid, folder, _ = track
    original = make_downloaded(track)
    before = original.read_bytes()
    connection.execute("CREATE TRIGGER deny_rename BEFORE UPDATE OF custom_title ON videos BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    connection.commit()
    with pytest.raises(RenameError):
        services.rename_track(connection, vid, "Original" if same_filename else "New", recycle=lambda path: None)
    row = db.list_videos(connection, pid)[0]
    assert original.read_bytes() == before and row["file_path"] == str(original) and row["custom_title"] is None
    assert not list(folder.glob(".tmp-*"))
    assert len(library.scan_folder(connection, pid).new_extra_ids) == 1


def test_changed_original_and_cancel_leave_source_untouched(track, monkeypatch):
    connection, pid, vid, folder, _ = track
    original = make_downloaded(track)
    real_tag = tagging.retag_title
    def change(path, title):
        real_tag(path, title)
        original.write_bytes(b"external change")
    monkeypatch.setattr(tagging, "retag_title", change)
    with pytest.raises(RenameError, match="changed"):
        services.rename_track(connection, vid, "New")
    assert original.read_bytes() == b"external change" and db.list_videos(connection, pid)[0]["custom_title"] is None
    assert not list(folder.glob(".tmp-*"))


def test_cancel_after_staging_does_not_change_original(track, monkeypatch):
    connection, pid, vid, folder, _ = track
    original = make_downloaded(track)
    before = original.read_bytes()
    real_tag, state = tagging.retag_title, {"cancel": False}
    def cancel_after_tag(path, title):
        real_tag(path, title)
        state["cancel"] = True
    monkeypatch.setattr(tagging, "retag_title", cancel_after_tag)
    with pytest.raises(RenameCancelled):
        services.rename_track(connection, vid, "New", cancelled=lambda: state["cancel"])
    assert original.read_bytes() == before and db.list_videos(connection, pid)[0]["custom_title"] is None
    assert not list(folder.glob(".tmp-*"))


def test_rollback_does_not_overwrite_new_file_at_original_path(track, monkeypatch):
    from mp3_playlist_downloader import renaming
    connection, pid, vid, folder, _ = track
    original = make_downloaded(track)
    before = original.read_bytes()
    def publish_failure(*args, **kwargs):
        original.write_bytes(b"new unrelated file")
        raise OSError("publication failed")
    monkeypatch.setattr(renaming, "_publish_exclusive", publish_failure)
    with pytest.raises(RenameError, match="original remains"):
        services.rename_track(connection, vid, "New")
    row = db.list_videos(connection, pid)[0]
    from pathlib import Path
    assert original.read_bytes() == b"new unrelated file"
    assert Path(row["file_path"]).read_bytes() == before
    assert row["file_path"] != str(original) and row["custom_title"] is None
    assert not list(folder.glob(".tmp-*"))


@pytest.mark.parametrize("title", ["", "  ", "bad\nname", "bad\x00name"])
def test_invalid_titles_do_not_change_db(track, title):
    connection, pid, vid, folder, _ = track
    with pytest.raises(RenameError, match="non-empty"):
        services.rename_track(connection, vid, title)
    assert db.list_videos(connection, pid)[0]["custom_title"] is None


def test_custom_title_survives_refresh_and_future_download(track, monkeypatch):
    from mp3_playlist_downloader import paths, queue
    from mp3_playlist_downloader.settings import Settings
    from mp3_playlist_downloader.youtube import download as downloader

    connection, pid, vid, folder, root = track
    services.rename_track(connection, vid, "My saved title")
    db.refresh_playlist(connection, pid, PlaylistMetadata("Album", (VideoMetadata("aaaaaaaaaaa", "Changed YouTube title", uploader="Artist"),)))
    fixture = root / "fixture.mp3"
    fixture.write_bytes(zlib.decompress(base64.b64decode(demo._SILENCE)))
    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            shutil.copyfile(fixture, self.options["outtmpl"].replace("%(ext)s", "mp3"))
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(tagging, "load_cover", lambda *args: None)
    settings = Settings()
    assert queue.enqueue_missing(connection, pid, settings) == 1
    assert queue.run_queue(connection, settings).downloaded == 1
    row = db.list_videos(connection, pid)[0]
    assert row["title"] == "Changed YouTube title" and row["custom_title"] == "My saved title"
    assert row["file_path"] == str(folder / "My saved title.mp3")
    assert str(ID3(row["file_path"])["TIT2"]) == "My saved title"


def test_custom_title_survives_redownload_of_renamed_file(track, monkeypatch):
    from mp3_playlist_downloader import paths, queue
    from mp3_playlist_downloader.settings import Settings
    from mp3_playlist_downloader.youtube import download as downloader

    connection, pid, vid, folder, root = track
    make_downloaded(track)
    result = services.rename_track(connection, vid, "My title", recycle=lambda path: shutil.move(path, root / "first-recycle.mp3"))
    fixture = root / "fixture.mp3"
    fixture.write_bytes(zlib.decompress(base64.b64decode(demo._SILENCE)))
    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            shutil.copyfile(fixture, self.options["outtmpl"].replace("%(ext)s", "mp3"))
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(downloader, "send2trash", lambda path: shutil.move(path, root / "second-recycle.mp3"))
    monkeypatch.setattr(tagging, "load_cover", lambda *args: None)
    settings = Settings()
    assert queue.enqueue_video(connection, vid, settings)
    assert queue.run_queue(connection, settings).downloaded == 1
    row = db.list_videos(connection, pid)[0]
    assert row["custom_title"] == "My title" and row["file_path"] == str(result.file_path)
    assert str(ID3(result.file_path)["TIT2"]) == "My title"


def test_title_tag_can_keep_characters_sanitized_from_filename(track):
    connection, pid, vid, folder, root = track
    make_downloaded(track)
    result = services.rename_track(connection, vid, "Name: Part 2", recycle=lambda path: shutil.move(path, root / "recycled.mp3"))
    assert result.file_path.name == "Name_ Part 2.mp3"
    assert str(ID3(result.file_path)["TIT2"]) == "Name: Part 2"


def test_case_only_filename_rename(track):
    connection, pid, vid, folder, root = track
    make_downloaded(track, "Original.mp3")
    result = services.rename_track(connection, vid, "original", recycle=lambda path: shutil.move(path, root / "recycled.mp3"))
    assert result.file_path.name == "original.mp3" and result.file_path.is_file()


def test_replaced_temporary_path_is_not_deleted(track, monkeypatch):
    connection, pid, vid, folder, _ = track
    original = make_downloaded(track)
    before = original.read_bytes()
    replacements = []
    def replace_temp(path, title):
        path.unlink()
        path.write_bytes(b"unrelated replacement")
        replacements.append(path)
    monkeypatch.setattr(tagging, "retag_title", replace_temp)
    with pytest.raises(RenameError, match="temporary rename file changed"):
        services.rename_track(connection, vid, "New")
    assert replacements[0].read_bytes() == b"unrelated replacement"
    assert original.read_bytes() == before and db.list_videos(connection, pid)[0]["custom_title"] is None


def test_rename_refuses_path_shared_by_another_video(track):
    connection, pid, vid, folder, root = track
    original = make_downloaded(track)
    before = original.read_bytes()
    other_pid, _ = db.add_playlist(connection, "other", PlaylistMetadata("Other", (VideoMetadata("bbbbbbbbbbb", "Other"),)), root / "music")
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE playlist_id=?", (str(original), other_pid))
    with pytest.raises(RenameError, match="shared"):
        services.rename_track(connection, vid, "New")
    assert original.read_bytes() == before
    assert db.list_videos(connection, pid)[0]["custom_title"] is None
    assert db.list_videos(connection, other_pid)[0]["file_path"] == str(original)


def test_reserved_windows_name_is_sanitized_for_disk_only(track):
    connection, pid, vid, folder, root = track
    make_downloaded(track)
    result = services.rename_track(connection, vid, "CON", recycle=lambda path: shutil.move(path, root / "recycled.mp3"))
    assert result.file_path.name == "_CON.mp3"
    assert str(ID3(result.file_path)["TIT2"]) == "CON"


def test_stored_path_with_alternate_separators_is_matched_exactly(track):
    connection, pid, vid, folder, root = track
    original = make_downloaded(track)
    stored = str(original).replace("\\", "/")
    with connection:
        connection.execute("UPDATE videos SET file_path=? WHERE id=?", (stored, vid))
    result = services.rename_track(connection, vid, "My title", recycle=lambda path: shutil.move(path, root / "recycled.mp3"))
    assert result.file_path.is_file()
    assert db.list_videos(connection, pid)[0]["custom_title"] == "My title"


def test_same_video_in_another_playlist_has_independent_override(track):
    connection, pid, vid, folder, root = track
    other_pid, _ = db.add_playlist(connection, "other", PlaylistMetadata("Other", (VideoMetadata("aaaaaaaaaaa", "Same video"),)), root / "music")
    services.rename_track(connection, vid, "Custom in first playlist")
    assert db.list_videos(connection, pid)[0]["custom_title"] == "Custom in first playlist"
    assert db.list_videos(connection, other_pid)[0]["custom_title"] is None


def test_current_download_cannot_be_renamed(track):
    connection, pid, vid, folder, _ = track
    with connection:
        connection.execute("UPDATE videos SET download_state='downloading' WHERE id=?", (vid,))
    with pytest.raises(RenameError, match="being downloaded"):
        services.rename_track(connection, vid, "New")
    assert db.list_videos(connection, pid)[0]["custom_title"] is None
