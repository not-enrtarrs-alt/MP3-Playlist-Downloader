import json
from pathlib import Path

import pytest

from mp3_playlist_downloader.youtube.parse import normalize_playlist_url, parse_flat_playlist, title_and_artist

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("url", [
    "https://youtube.com/playlist?list=PL123", "https://music.youtube.com/playlist?list=PL123",
    "https://youtu.be/abcdefghijk?list=PL123", "https://www.youtube.com/watch?v=abcdefghijk&list=PL123",
    "youtube.com/playlist?list=PL123",
])
def test_canonical_urls(url):
    assert normalize_playlist_url(url) == "https://www.youtube.com/playlist?list=PL123"


@pytest.mark.parametrize(("url", "message"), [
    ("https://youtube.com/watch?v=123", "single video"),
    ("https://youtube.com/watch?v=123&list=RD123", "endless mix"),
    ("https://youtube.com.evil.example/playlist?list=PL123", "valid YouTube"),
    ("https://youtube.com/playlist?list=PL%20bad", "valid YouTube"),
])
def test_url_rejection(url, message):
    with pytest.raises(ValueError, match=message):
        normalize_playlist_url(url)


def test_flat_parsing():
    parsed = parse_flat_playlist(json.loads((FIXTURES / "playlist_flat.json").read_text()))
    assert parsed.title == "Example Playlist" and len(parsed.videos) == 5
    assert parsed.videos[0].thumbnail_url == "large.jpg"
    assert parsed.videos[1].is_topic and parsed.videos[1].position == 1
    assert parsed.videos[1].thumbnail_url == "https://i.ytimg.com/vi/bbbbbbbbbbb/hqdefault.jpg"


def test_unavailable_and_duplicate(caplog):
    parsed = parse_flat_playlist(json.loads((FIXTURES / "playlist_unavailable.json").read_text()))
    assert parsed.title == "Playlist" and len(parsed.videos) == 2
    assert parsed.videos[0].title == "[Unavailable video]" and parsed.videos[0].unavailable
    assert parsed.videos[1].unavailable and parsed.videos[0].position == 2


def test_raw_title_preserved_and_malformed_duration_tolerated():
    result = parse_flat_playlist({"entries": [{"id": "aaaaaaaaaaa", "title": "  Original  ", "duration": float("nan")} ]})
    assert result.videos[0].title == "  Original  "
    assert result.videos[0].duration_seconds is None


@pytest.mark.parametrize(("title", "uploader", "expected"), [
    ("Artist - Song", "Artist - Topic", ("Song", "Artist")),
    ("A.C. - Song", "ac - topic", ("Song", "A.C.")),
    ("Other - Song", "Artist - Topic", ("Other - Song", "Artist")),
    ("Song", None, ("Song", "Unknown Artist")),
    ("Song", "Channel", ("Song", "Channel")),
])
def test_topic_title(title, uploader, expected):
    assert title_and_artist(title, uploader) == expected


@pytest.mark.parametrize(("title", "uploader", "expected_title", "expected_artist"), [
    ("Ava Max - Catch My Breath (Official Audio)", "Ava Max", "Catch My Breath", "Ava Max"),
    ("Ava Max - Blood, Sweat & Tears [Official Lyric Video]", "Ava Max", "Blood, Sweat & Tears", "Ava Max"),
    ("Charli xcx - 360 (official lyric video)", "Charli XCX", "360", "Charli XCX"),
    ("Dua Lipa - Dance The Night (From Barbie The Album) [Official Lyric Video]", "Dua Lipa", "Dance The Night", "Dua Lipa"),
    ("Dua Lipa - Dreams [Album Visual] (Official Audio)", "Dua Lipa", "Dreams", "Dua Lipa"),
    ("Dua Lipa - Falling Forever (Official Visualiser)", "Dua Lipa", "Falling Forever", "Dua Lipa"),
    ("Skrillex - Bangarang (Ft. Sirah) [Official Audio]", "Skrillex", "Bangarang", "Skrillex"),
    ("Ava Max ft. Gashi - Slippin' [Official Lyric Video]", "Ava Max", "Slippin'", "Ava Max"),
    ("Lil Nas X - Old Town Road (Official Video) ft. Billy Ray Cyrus", "Lil Nas X", "Old Town Road", "Lil Nas X"),
    ("Lil Nas X - MONTERO (Call Me By Your Name) (Official Video)", "Lil Nas X", "MONTERO (Call Me By Your Name)", "Lil Nas X"),
    ("Artist - The Official (Official Video)", "Artist", "The Official", "Artist"),
    ("Artist - Song (Remix) [Official Audio]", "Artist", "Song", "Artist"),
    ("Artist - Song (Guest Remix) [Official Audio]", "Artist", "Song", "Artist"),
    ("Artist - Song (Remastered) [Official Audio]", "Artist", "Song", "Artist"),
    ("Artist - Song (Live at Wembley) [Official Video]", "Artist", "Song", "Artist"),
    ("Artist - Song (Radio Edit) [Official Audio]", "Artist", "Song", "Artist"),
    ("Michael Jackson - They Don't Care About Us (Official Audio) Special Edition Album", "Michael Jackson", "They Don't Care About Us", "Michael Jackson"),
    ("SANDY MARTON - Camel by camel [Official]", "Sandy Marton", "Camel by camel", "Sandy Marton"),
    ("GIMS - Tout donner (pilule violette) (Audio officiel)", "GIMS", "Tout donner (pilule violette)", "GIMS"),
    ("StaySolidRocky- Party Girl (Official Music Video)", "StaySolidRocky", "Party Girl", "StaySolidRocky"),
    ("Artist – Song Official Lyric Video", "Artist", "Song", "Artist"),
    ("Artist - Song Official Video ft. Guest", "Artist", "Song", "Artist"),
    ("Artist - Song (Official Audio) Special Edition Album feat. Guest", "Artist", "Song", "Artist"),
    ("Artist: Song [OFFICIAL VIDEO]", "Artist", "Song", "Artist"),
    ("The Muffin Song (Official Music Video)", "Channel", "The Muffin Song", "Channel"),
    ("The Muffin Song - Official Music Video", "Channel", "The Muffin Song", "Channel"),
    ("Tout donner - Audio officiel", "Channel", "Tout donner", "Channel"),
    ("Song (Official Video - Visualizer)", "Channel", "Song", "Channel"),
    ("Artist feat. (Guest) - Song (Official Audio)", "Artist", "Song", "Artist"),
    ("Song (Official Audio)", None, "Song", "Unknown Artist"),
    ("A.C. - Song (Official Audio)", "ac - Topic", "Song", "ac"),
])
def test_official_title_cleanup_examples(title, uploader, expected_title, expected_artist):
    assert title_and_artist(title, uploader) == (expected_title, expected_artist)


@pytest.mark.parametrize(("title", "uploader"), [
    ("Ava Max - Catch My Breath (Official Audio)", "Other Channel"),
    ("Ava Max - Catch My Breath (Official Audio)", None),
    ("Kygo, Ava Max - Whatever (Official Video)", "Kygo"),
    ("Artist - Song (Official Audio)", "Other - Topic"),
    ("Artist - (Official Audio)", "Artist"),
    ("Ava Max - Jet Set (Lyrics)", "Ava Max"),
    ("Artist - Song (Unofficial Video)", "Artist"),
    ("What the Hell by @lollia_official ft. Friends", "Lollia"),
    ("Artist - Song (Official Audio", "Artist"),
    ("Artist - Song [Official Audio)]", "Artist"),
])
def test_official_cleanup_leaves_mismatch_or_nonofficial_titles(title, uploader):
    assert title_and_artist(title, uploader)[0] == title


def test_custom_title_overrides_automatic_cleanup_but_preserves_artist():
    assert title_and_artist("Artist - Song (Official Audio)", "Artist", "My name") == ("My name", "Artist")
    assert title_and_artist("Artist - Song", "Artist - Topic", "My name") == ("My name", "Artist")
