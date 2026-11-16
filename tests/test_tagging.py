import shutil

from mutagen.id3 import ID3, APIC, TIT2
from PySide6.QtGui import QColor, QImage

from mp3_playlist_downloader.tagging import load_cover, retag_album, retag_title, tag_file


def test_id3_v23_topic_album_and_apic_replacement(silent_mp3, tmp_path):
    path = tmp_path / "song.mp3"
    shutil.copyfile(silent_mp3, path)
    image_path = tmp_path / "cover.jpg"
    image = QImage(2, 2, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(image_path), "JPEG")
    cover = image_path.read_bytes()
    tag_file(path, "Artist - Song", "Artist - Topic", "Album", cover)
    tags = ID3(path)
    assert tags.version == (2, 3, 0)
    assert str(tags["TIT2"]) == "Song" and str(tags["TPE1"]) == "Artist"
    assert str(tags["TALB"]) == "Album"
    assert tags.getall("APIC")[0].data == cover and tags.getall("APIC")[0].mime == "image/jpeg"
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Other", data=b"old"))
    tags.add(TIT2(encoding=3, text="Old"))
    tags.save(path, v2_version=3)
    tag_file(path, "New", None, "Album 2", cover)
    tags = ID3(path)
    assert len(tags.getall("APIC")) == 1 and str(tags["TIT2"]) == "New"
    assert str(tags["TPE1"]) == "Unknown Artist" and str(tags["TALB"]) == "Album 2"
    retag_album(path, "Renamed")
    tags = ID3(path)
    assert str(tags["TALB"]) == "Renamed" and str(tags["TIT2"]) == "New" and tags.getall("APIC")[0].data == cover


def test_cover_local_or_fallback_offline(tmp_path):
    path = tmp_path / "cover.jpg"
    jpeg = b"\xff\xd8\xffexample"
    path.write_bytes(jpeg)
    def forbidden(*args, **kwargs):
        raise AssertionError("local cover should not use network")
    assert load_cover("aaaaaaaaaaa", path, http_get=forbidden) == jpeg
    calls = []
    class Response:
        def __init__(self, content):
            self.content = content
        def raise_for_status(self):
            pass
    def get(url, timeout):
        calls.append((url, timeout))
        return Response(b"not jpeg" if len(calls) == 1 else jpeg)
    assert load_cover("aaaaaaaaaaa", http_get=get) == jpeg
    assert len(calls) == 2 and all(timeout == 10 for _, timeout in calls)


def test_missing_cover_is_tolerated(silent_mp3, tmp_path):
    import requests
    path = tmp_path / "song.mp3"
    shutil.copyfile(silent_mp3, path)
    def get(*args, **kwargs):
        raise requests.Timeout()
    assert load_cover("aaaaaaaaaaa", http_get=get) is None
    tag_file(path, "Song", "Channel", "Album")
    assert not ID3(path).getall("APIC")


def test_png_thumbnail_converts_to_jpeg_without_network(tmp_path):
    import pytest
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is required for thumbnail conversion")
    image_path = tmp_path / "cover.png"
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(QColor("blue"))
    assert image.save(str(image_path), "PNG")
    def forbidden(*args, **kwargs):
        raise AssertionError("local PNG conversion should not use network")
    result = load_cover("aaaaaaaaaaa", image_path, ffmpeg, http_get=forbidden)
    assert result and result.startswith(b"\xff\xd8\xff")


def test_official_title_cleans_metadata_without_losing_artist(silent_mp3, tmp_path):
    path = tmp_path / "song.mp3"
    shutil.copyfile(silent_mp3, path)
    tag_file(path, "Skrillex - Bangarang (Ft. Sirah) [Official Audio]", "Skrillex", "Album")
    tags = ID3(path)
    assert str(tags["TIT2"]) == "Bangarang" and str(tags["TPE1"]) == "Skrillex"


def test_tag_file_honors_custom_title(silent_mp3, tmp_path):
    path = tmp_path / "song.mp3"
    shutil.copyfile(silent_mp3, path)
    tag_file(path, "Artist - Song (Official Audio)", "Artist", "Album", None, "My title")
    tags = ID3(path)
    assert str(tags["TIT2"]) == "My title" and str(tags["TPE1"]) == "Artist"


def test_retag_title_preserves_other_frames_and_does_not_create_missing(silent_mp3, tmp_path):
    import pytest
    from mutagen.id3 import TXXX
    path = tmp_path / "song.mp3"
    shutil.copyfile(silent_mp3, path)
    cover = b"\xff\xd8\xfftest-cover"
    tag_file(path, "Original", "Artist", "Album", cover)
    tags = ID3(path)
    tags.add(TXXX(encoding=3, desc="Custom", text="keep"))
    tags.save(path, v2_version=3)
    retag_title(path, "Renamed")
    tags = ID3(path)
    assert tags.version == (2, 3, 0) and str(tags["TIT2"]) == "Renamed"
    assert str(tags["TPE1"]) == "Artist" and str(tags["TALB"]) == "Album"
    assert tags.getall("APIC")[0].data == cover and tags.getall("TXXX")[0].text == ["keep"]
    with pytest.raises(FileNotFoundError):
        retag_title(tmp_path / "missing.mp3", "Name")
    assert not (tmp_path / "missing.mp3").exists()
