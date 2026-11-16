import shutil

import pytest
from mutagen.id3 import ID3

from mp3_playlist_downloader import db, equalizer, library, services
from mp3_playlist_downloader.linking import LinkError
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
from mp3_playlist_downloader.settings import Settings


@pytest.fixture
def track(tmp_path):
    connection = db.connect(tmp_path / "app.db")
    db.initialize(connection)
    playlist = PlaylistMetadata("Album", (VideoMetadata("aaaaaaaaaaa", "Artist - Song", uploader="Artist - Topic"),))
    pid, _ = db.add_playlist(connection, "url", playlist, tmp_path / "music")
    folder = tmp_path / "music" / "Album"
    row = db.list_videos(connection, pid)[0]
    yield connection, pid, row["id"], folder, Settings(output_root=str(tmp_path / "music"))
    connection.close()


def test_external_link_copies_source_and_tags(track, tmp_path, silent_mp3):
    connection, pid, vid, folder, settings = track
    source = tmp_path / "Original.mp3"
    shutil.copyfile(silent_mp3, source)
    before = source.read_bytes()
    (folder / "Original.mp3").write_bytes(b"unrelated")
    result = services.link_file(connection, vid, source, settings, cover_loader=lambda *args: None)
    assert source.read_bytes() == before and result.file_path.name == "Original (2).mp3"
    assert (folder / "Original.mp3").read_bytes() == b"unrelated"
    row = db.list_videos(connection, pid)[0]
    assert row["downloaded"] == 1 and row["equalized"] == 0
    assert str(ID3(result.file_path)["TIT2"]) == "Song" and str(ID3(result.file_path)["TALB"]) == "Album"


def test_external_link_honors_existing_custom_title(track, tmp_path, silent_mp3):
    connection, pid, vid, folder, settings = track
    source = tmp_path / "original.mp3"
    shutil.copyfile(silent_mp3, source)
    before = source.read_bytes()
    with connection:
        connection.execute("UPDATE videos SET custom_title=? WHERE id=?", ("My title", vid))
    result = services.link_file(connection, vid, source, settings, cover_loader=lambda *args: None)
    assert result.file_path.name == "My title.mp3" and source.read_bytes() == before
    assert str(ID3(result.file_path)["TIT2"]) == "My title"


def test_local_extra_is_adopted_in_place(track, silent_mp3):
    connection, pid, vid, folder, settings = track
    source = folder / "extra.MP3"
    shutil.copyfile(silent_mp3, source)
    assert library.scan_folder(connection, pid).pending_count == 1
    result = services.link_file(connection, vid, source, settings, cover_loader=lambda *args: None)
    assert result.file_path == source and not library.list_extras(connection, pid)
    assert db.list_videos(connection, pid)[0]["file_path"] == str(source)


def test_link_replacement_recycles_old_after_copy(track, tmp_path, silent_mp3):
    connection, pid, vid, folder, settings = track
    old = folder / "old.mp3"
    shutil.copyfile(silent_mp3, old)
    source = tmp_path / "new.mp3"
    shutil.copyfile(silent_mp3, source)
    before = source.read_bytes()
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,equalized=1,file_path=?,file_size=? WHERE id=?", (str(old), old.stat().st_size, vid))
    recycled = tmp_path / "recycled.bin"
    result = services.link_file(connection, vid, source, settings, recycle=lambda path: shutil.move(path, recycled), cover_loader=lambda *args: None)
    assert recycled.is_file() and not old.exists() and source.read_bytes() == before
    assert result.file_path.exists() and not result.equalized
    assert db.list_videos(connection, pid)[0]["equalized"] == 0


def test_recycle_failure_keeps_existing_track_and_source(track, tmp_path, silent_mp3):
    connection, pid, vid, folder, settings = track
    old, source = folder / "old.mp3", tmp_path / "source.mp3"
    shutil.copyfile(silent_mp3, old)
    shutil.copyfile(silent_mp3, source)
    before = source.read_bytes()
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE id=?", (str(old), vid))
    def fail(path):
        raise OSError("private details")
    with pytest.raises(LinkError, match="Recycle Bin"):
        services.link_file(connection, vid, source, settings, recycle=fail, cover_loader=lambda *args: None)
    assert old.exists() and source.read_bytes() == before and not list(folder.glob(".tmp-*"))
    assert db.list_videos(connection, pid)[0]["file_path"] == str(old)


def test_same_track_retags_and_auto_equalize_failure_is_warning(track, silent_mp3, monkeypatch):
    connection, pid, vid, folder, settings = track
    path = folder / "current.mp3"
    shutil.copyfile(silent_mp3, path)
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,equalized=1,file_path=? WHERE id=?", (str(path), vid))
    settings.auto_equalize = True
    def fail(*args):
        raise equalizer.EqualizerMissing(equalizer.MISSING_MESSAGE)
    monkeypatch.setattr(equalizer, "apply", fail)
    result = services.link_file(connection, vid, path, settings, cover_loader=lambda *args: None)
    row = db.list_videos(connection, pid)[0]
    assert result.file_path == path and row["downloaded"] == 1 and row["equalized"] == 0
    assert row["error_kind"] == "equalize" and "mp3gain not found" in row["last_error"]


def test_invalid_source_never_changes_track(track, tmp_path):
    connection, pid, vid, folder, settings = track
    with pytest.raises(LinkError, match="readable MP3"):
        services.link_file(connection, vid, tmp_path / "nope.txt", settings)
    assert db.list_videos(connection, pid)[0]["downloaded"] == 0


def test_linked_file_inside_folder_is_copied_to_protect_external_hardlink(track, tmp_path, silent_mp3):
    import os
    connection, pid, vid, folder, settings = track
    external = tmp_path / "external.mp3"
    shutil.copyfile(silent_mp3, external)
    before = external.read_bytes()
    linked = folder / "linked.mp3"
    try:
        os.link(external, linked)
    except OSError:
        pytest.skip("Hard links are unavailable on this filesystem")
    result = services.link_file(connection, vid, linked, settings, cover_loader=lambda *args: None)
    assert result.file_path != linked and external.read_bytes() == before and linked.read_bytes() == before


def test_adopt_refuses_source_changed_during_cover_lookup(track, silent_mp3):
    connection, pid, vid, folder, settings = track
    source = folder / "extra.mp3"
    shutil.copyfile(silent_mp3, source)
    library.scan_folder(connection, pid)
    def changed(*args):
        source.write_bytes(b"new unrelated contents")
        return None
    with pytest.raises(LinkError, match="changed"):
        services.link_file(connection, vid, source, settings, cover_loader=changed)
    assert source.read_bytes() == b"new unrelated contents"
    assert db.list_videos(connection, pid)[0]["downloaded"] == 0
    assert len(library.list_extras(connection, pid)) == 1


def test_source_tracked_by_another_video_is_copied_not_adopted(track, silent_mp3):
    connection, pid, vid, folder, settings = track
    second_pid, _ = db.add_playlist(connection, "another-url", PlaylistMetadata("Other", (VideoMetadata("bbbbbbbbbbb", "Other"),)), folder.parent)
    other_video = db.list_videos(connection, second_pid)[0]["id"]
    source = folder / "other-track.mp3"
    shutil.copyfile(silent_mp3, source)
    before = source.read_bytes()
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE id=?", (str(source), other_video))
    result = services.link_file(connection, vid, source, settings, cover_loader=lambda *args: None)
    assert result.file_path != source and source.read_bytes() == before
    assert db.list_videos(connection, second_pid)[0]["file_path"] == str(source)


def test_album_retag_missing_file_never_creates_it(track):
    connection, pid, vid, folder, settings = track
    missing = folder / "missing.mp3"
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE id=?", (str(missing), vid))
        connection.execute("UPDATE playlists SET album_sync_pending=1 WHERE id=?", (pid,))
    result = services.sync_album(connection, pid)
    assert result.failed == 1 and not missing.exists()
    assert db.list_playlists(connection)[0]["album_sync_pending"] == 1
