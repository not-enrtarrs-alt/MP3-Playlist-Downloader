import shutil

import pytest
from mutagen.id3 import ID3

from mp3_playlist_downloader import paths, tagging
from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.youtube.download import DownloadCancelled, download_video
from mp3_playlist_downloader.youtube.errors import RateLimitedError


@pytest.fixture
def video():
    return {"video_id": "aaaaaaaaaaa", "title": "Artist - Song", "uploader": "Artist - Topic"}


def test_download_options_tags_progress_and_collision(video, silent_mp3, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    folder = tmp_path / "playlist"
    folder.mkdir()
    (folder / "Song.mp3").write_bytes(b"untouched")
    observed, updates = [], []
    class Fake:
        def __init__(self, options):
            observed.append(options)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            options = observed[0]
            assert download and url.endswith(video["video_id"])
            options["progress_hooks"][0]({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100, "speed": 1024, "eta": 5})
            shutil.copyfile(silent_mp3, options["outtmpl"].replace("%(ext)s", "mp3"))
            with open(options["outtmpl"].replace("%(ext)s", "jpg"), "wb") as thumbnail:
                thumbnail.write(b"\xff\xd8\xfffakejpeg")
    result = download_video(video, "Album", folder, Settings(cookies_mode="browser", cookies_browser="firefox"), progress=lambda *args: updates.append(args), downloader_factory=Fake)
    options = observed[0]
    assert options["format"] == "bestaudio/best" and options["cookiesfrombrowser"] == ("firefox",)
    assert options["postprocessors"] == [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}, {"key": "FFmpegThumbnailsConvertor", "format": "jpg"}]
    assert options["outtmpl"].endswith(".%(ext)s") and options["noplaylist"] and options["writethumbnail"]
    assert updates == [(50.0, 1024, 5)] and result.file_path.name == "Song (2).mp3"
    assert (folder / "Song.mp3").read_bytes() == b"untouched"
    tags = ID3(result.file_path)
    assert tags.version == (2, 3, 0) and str(tags["TIT2"]) == "Song" and str(tags["TALB"]) == "Album"
    assert tags.getall("APIC") and not list(folder.glob(".tmp-*"))


def test_download_cleans_temporary_files_after_rate_limit(video, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    class Fake:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            with open(self.options["outtmpl"].replace("%(ext)s", "part"), "wb") as partial:
                partial.write(b"partial")
            raise RuntimeError("HTTP Error 429 secret-cookie")
    with pytest.raises(RateLimitedError) as error:
        download_video(video, "Album", tmp_path, Settings(), downloader_factory=Fake)
    assert "secret-cookie" not in str(error.value)
    assert not list(tmp_path.glob(".tmp-*"))


def test_cancel_aborts_and_cleans_up(video, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    with pytest.raises(DownloadCancelled):
        download_video(video, "Album", tmp_path, Settings(), cancelled=lambda: True)
    assert not list(tmp_path.glob(".tmp-*"))


def test_wrapped_cancel_is_not_misclassified(video, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    state = {"cancelled": False}
    class Fake:
        def __init__(self, options):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            state["cancelled"] = True
            raise RuntimeError("wrapped upstream cancellation")
    with pytest.raises(DownloadCancelled):
        download_video(video, "Album", tmp_path, Settings(), downloader_factory=Fake, cancelled=lambda: state["cancelled"])


def test_tag_failure_keeps_audio(video, silent_mp3, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    def fail(*args):
        raise ValueError("sensitive path")
    monkeypatch.setattr(tagging, "tag_file", fail)
    class Fake:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            shutil.copyfile(silent_mp3, self.options["outtmpl"].replace("%(ext)s", "mp3"))
    result = download_video(video, "Album", tmp_path, Settings(), downloader_factory=Fake, cover_loader=lambda *args: None)
    assert result.file_path.is_file() and result.warning_kind == "tag"
    assert "sensitive" not in result.warning and not list(tmp_path.glob(".tmp-*"))


def test_publish_never_overwrites_file_created_during_race(tmp_path, monkeypatch):
    import os
    from mp3_playlist_downloader.youtube import download as downloader

    source = tmp_path / ".tmp-source.mp3"
    source.write_bytes(b"new audio")
    original = os.rename if os.name == "nt" else os.link
    created = []
    def competing(source, target):
        if not created:
            target.write_bytes(b"unrelated")
            created.append(target)
        return original(source, target)
    monkeypatch.setattr(downloader.os, "rename" if os.name == "nt" else "link", competing)
    published = downloader._publish_exclusive(source, tmp_path, "Song", [])
    assert created[0].read_bytes() == b"unrelated"
    assert published.name == "Song (2).mp3" and published.read_bytes() == b"new audio"


@pytest.mark.parametrize("succeeds", [True, False])
def test_auto_equalize_success_or_warning(video, silent_mp3, tmp_path, monkeypatch, succeeds):
    from mp3_playlist_downloader import equalizer
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    called = []
    def gain(path, settings):
        called.append(path)
        if not succeeds:
            raise equalizer.EqualizerMissing(equalizer.MISSING_MESSAGE)
    monkeypatch.setattr(equalizer, "apply", gain)
    class Fake:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            shutil.copyfile(silent_mp3, self.options["outtmpl"].replace("%(ext)s", "mp3"))
    result = download_video(video, "Album", tmp_path, Settings(auto_equalize=True), downloader_factory=Fake, cover_loader=lambda *args: None)
    assert len(called) == 1 and result.file_path.exists()
    assert result.equalized is succeeds
    assert result.warning_kind == (None if succeeds else "equalize")


def test_thumbnail_failure_after_completed_audio_keeps_mp3(video, silent_mp3, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    class Fake:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            shutil.copyfile(silent_mp3, self.options["outtmpl"].replace("%(ext)s", "mp3"))
            hook = self.options["postprocessor_hooks"][0]
            hook({"postprocessor": "ExtractAudio", "status": "finished"})
            hook({"postprocessor": "ThumbnailsConvertor", "status": "started"})
            raise RuntimeError("postprocessing failed with secret-cookie-path")
    result = download_video(video, "Album", tmp_path, Settings(), downloader_factory=Fake, cover_loader=lambda *args: None)
    assert result.file_path.is_file() and str(ID3(result.file_path)["TALB"]) == "Album"
    assert not list(tmp_path.glob(".tmp-*"))


def test_incomplete_audio_is_never_salvaged(video, silent_mp3, tmp_path, monkeypatch):
    from mp3_playlist_downloader.youtube.errors import YouTubeError
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    class Fake:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            shutil.copyfile(silent_mp3, self.options["outtmpl"].replace("%(ext)s", "mp3"))
            self.options["postprocessor_hooks"][0]({"postprocessor": "ExtractAudio", "status": "started"})
            raise RuntimeError("audio conversion failed")
    with pytest.raises(YouTubeError):
        download_video(video, "Album", tmp_path, Settings(), downloader_factory=Fake)
    assert not list(tmp_path.glob("*.mp3")) and not list(tmp_path.glob(".tmp-*"))


def test_real_ytdlp_hooks_salvage_thumbnail_failure_offline(video, silent_mp3, tmp_path, monkeypatch):
    import yt_dlp
    from PySide6.QtGui import QColor, QImage
    from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessorError, FFmpegThumbnailsConvertorPP

    class OfflineYoutubeDL(yt_dlp.YoutubeDL):
        def extract_info(self, url, download=True):
            audio = self.params["outtmpl"]["default"].replace("%(ext)s", "mp3") if isinstance(self.params["outtmpl"], dict) else self.params["outtmpl"].replace("%(ext)s", "mp3")
            thumbnail = audio[:-4] + ".png"
            shutil.copyfile(silent_mp3, audio)
            image = QImage(16, 16, QImage.Format.Format_RGB32)
            image.fill(QColor("blue"))
            assert image.save(thumbnail, "PNG")
            info = {"filepath": audio, "ext": "mp3", "vcodec": "none", "acodec": "mp3",
                    "thumbnails": [{"filepath": thumbnail}], "__files_to_move": {thumbnail: thumbnail}}
            for pp in self._pps["post_process"]:
                _, info = pp.run(info)
            return info

    def fail_thumbnail(_self, filename, _ext):
        from pathlib import Path
        Path(filename).with_suffix(".jpg").write_bytes(b"incomplete conversion")
        raise FFmpegPostProcessorError("thumbnail converter failed")
    def no_network(*args, **kwargs):
        raise AssertionError("fallback should use the local PNG")
    monkeypatch.setattr(FFmpegThumbnailsConvertorPP, "convert_thumbnail", fail_thumbnail)
    monkeypatch.setattr(tagging.requests, "get", no_network)
    result = download_video(video, "Album", tmp_path, Settings(), downloader_factory=OfflineYoutubeDL)
    tags = ID3(result.file_path)
    assert str(tags["TALB"]) == "Album" and tags.getall("APIC")
    assert not list(tmp_path.glob(".tmp-*"))


def test_thumbnail_error_path_with_429_does_not_mimic_rate_limit(video, silent_mp3, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    class Fake:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            shutil.copyfile(silent_mp3, self.options["outtmpl"].replace("%(ext)s", "mp3"))
            hook = self.options["postprocessor_hooks"][0]
            hook({"postprocessor": "ExtractAudio", "status": "finished"})
            hook({"postprocessor": "ThumbnailsConvertor", "status": "started"})
            raise RuntimeError(r"Postprocessing failed in C:\Music\429\thumbnail.png")
    result = download_video(video, "Album", tmp_path, Settings(), downloader_factory=Fake, cover_loader=lambda *args: None)
    assert result.file_path.is_file()


def test_explicit_rate_limit_still_pauses_even_if_thumbnail_started(video, silent_mp3, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    class Fake:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            shutil.copyfile(silent_mp3, self.options["outtmpl"].replace("%(ext)s", "mp3"))
            hook = self.options["postprocessor_hooks"][0]
            hook({"postprocessor": "ExtractAudio", "status": "finished"})
            hook({"postprocessor": "ThumbnailsConvertor", "status": "started"})
            raise RateLimitedError("rate limited")
    with pytest.raises(RateLimitedError):
        download_video(video, "Album", tmp_path, Settings(), downloader_factory=Fake)
    assert not list(tmp_path.glob("*.mp3")) and not list(tmp_path.glob(".tmp-*"))
