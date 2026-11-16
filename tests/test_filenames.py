import pytest

from mp3_playlist_downloader.paths import sanitize_filename


@pytest.mark.parametrize(("source", "expected"), [
    ('a<>:"/\\|?*\x01b', 'a__________b'),
    ('hello.  ', 'hello'), (' . ', 'Untitled'), ('CON', '_CON'),
    ('nul.txt', '_nul.txt'), ('COM1', '_COM1'), ('LPT9', '_LPT9'),
    ('音楽 🎵', '音楽 🎵'),
])
def test_sanitize(source, expected):
    assert sanitize_filename(source) == expected


def test_length_limit():
    assert len(sanitize_filename("a" * 200)) == 120
