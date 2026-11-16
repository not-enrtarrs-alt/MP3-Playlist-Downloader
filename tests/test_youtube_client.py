import pytest

from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.youtube.client import fetch_playlist
from mp3_playlist_downloader.youtube.errors import AudioConversionError, NetworkError, RateLimitedError, UnavailableError, YouTubeError, classify_error


@pytest.mark.parametrize(("raw", "kind"), [
    ("HTTP Error 429", RateLimitedError), ("Sign in to confirm you're not a bot", RateLimitedError),
    ("private video", UnavailableError), ("HTTP Error 503", NetworkError),
    ("connection reset", NetworkError), ("unexpected", YouTubeError),
    ("Postprocessing: ffmpeg failed secret-cookie-path", AudioConversionError),
])
def test_error_classification(raw, kind):
    assert isinstance(classify_error(Exception(raw)), kind)


def test_flat_fetch_options_and_cookies(caplog):
    calls = []
    class Fake:
        def __init__(self, options):
            calls.append(options)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            assert url == "https://www.youtube.com/playlist?list=PL123"
            assert not download
            return {"title": "Playlist", "entries": [{"id": "abcdefghijk", "title": "Song"}]}
    result = fetch_playlist("youtube.com/watch?v=x&list=PL123", Settings(cookies_mode="file", cookies_file="secret-cookie-path"), downloader_factory=Fake)
    assert result.videos[0].title == "Song"
    logger = calls[0].pop("logger")
    logger.error("cookiefile=C:\\secret-cookie-path cookie: supersecret")
    assert calls[0] == {"extract_flat": "in_playlist", "skip_download": True, "quiet": True, "no_warnings": True, "cookiefile": "secret-cookie-path"}
    assert "secret-cookie-path" not in caplog.text


def test_raw_error_never_escapes(caplog):
    class Fake:
        def __init__(self, options):
            raise ValueError("secret-cookie-path and token=supersecret HTTP Error 429")
    with pytest.raises(RateLimitedError) as error:
        fetch_playlist("https://youtube.com/playlist?list=PL123", Settings(), downloader_factory=Fake)
    assert "secret" not in str(error.value) + caplog.text


def test_conversion_error_is_specific_and_does_not_expose_raw_details():
    error = classify_error(Exception("ffmpeg failed with secret-cookie-path and token=secret"))
    assert isinstance(error, AudioConversionError)
    assert "ffmpeg" in str(error) and "secret" not in str(error)
