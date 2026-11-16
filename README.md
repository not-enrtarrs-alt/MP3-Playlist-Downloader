# MP3 Playlist Downloader

Windows desktop playlist-to-MP3 library manager. It downloads one video at a time, tags each MP3 with the playlist album and thumbnail, tracks progress in SQLite, and optionally applies permanent mp3gain track gain. No scheduler or background service is used. A Windows onedir build has been smoke-tested; the per-user installer script requires Inno Setup and has not yet been compiled here.

```text
Playlists            Playlist tracks                         Legend
  Favorites          [Equalize] [Select] [Download] [Delete]  Green: equalized
  Discoveries        1  Song title             Downloaded    Blue: downloaded
                     2  Another title          Not downloaded Red: missing
+ Add playlist       Extra.mp3                 Extra file     Yellow: extra
Progress / Cancel                                            Grey: unavailable
```

## Development quickstart

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m mp3_playlist_downloader doctor
.\.venv\Scripts\python.exe -m mp3_playlist_downloader demo --check
.\.venv\Scripts\python.exe -m mp3_playlist_downloader
.\.venv\Scripts\python.exe -m pytest -q
```

Install ffmpeg and ffprobe on PATH or configure ffmpeg under **Settings → Tools**. mp3gain is optional. In a built onedir, launch `MP3 Playlist Downloader.exe` from Explorer; an installer can be built as described below.

Use **+ Add playlist** to fetch a playlist, then select it in the sidebar to view cached tracks without a network request. **Refresh** is manual. **Download missing** runs one download at a time and saves queue progress. Removing a playlist removes its database records but leaves files untouched. Unknown MP3s are shown as extra files and are never automatically deleted. Playlist fetching and real downloads require network; tests use offline fakes. Configure cookies, output, tools, and theme in **Settings**.

After a rate limit the queue pauses and shows a countdown; it can resume automatically up to three times while the app remains open, or manually with **Resume now**. On a later launch pending downloads always require a manual resume. Right-click a track to link a local MP3 or re-download it. Playlist title changes can be applied to album tags using the displayed update link.

Right-click **Rename track…** to choose a custom title. It remains in effect after playlist refreshes and future downloads. For a downloaded track the app updates the MP3 title tag and filename while preserving artist, album, cover and equalization state; filename collisions receive a numbered suffix. The original is kept safely until the new file and database update succeed, then sent to the Recycle Bin. If recycling fails, the original remains as an additional file for review. SQLite schema 1 is migrated to schema 2 without deleting existing data.

For titles containing an official/officiel marker, recognizable official labels, featured credits, album/source references and version annotations are stripped. A credited artist prefix is removed only when its primary artist matches the uploader; mismatched or ambiguous titles stay unchanged. The cleaned title is shown in the table and used for new download filenames and title tags. Manual links retain their chosen source-derived or adopted filename. Raw YouTube titles remain in SQLite.

`demo --check` creates a temporary offline library using a tiny silent fixture, reports five example states, and leaves real data untouched. Equalized states in the demo are simulated. Actual mp3gain permanently changes audio gain and must be installed separately; its CLI flags were verified against version 1.5.2, but other builds may differ.

## Colors and actions

| Color | State |
|---|---|
| Green | Downloaded and equalized |
| Blue | Downloaded, not equalized |
| Red | Not downloaded or failed |
| Yellow | Additional file, pending or kept |
| Grey | Unavailable or removed without a local file |

Select tracks with the checkboxes or **Select all**. **Equalize selected** is opt-in; automatic equalization is off by default. Gain changes are irreversible: test on a copy first. **Delete selected** and explicit extra-file deletes use the Recycle Bin, not permanent deletion. Unknown files are never automatically deleted. **Point to MP3 file…** copies external files and adopts an unlinked local extra in place. Existing tracks are skipped by default; overwrite requires confirmation.

## Data and privacy

```text
%APPDATA%\MP3 Playlist Downloader\app.db
%APPDATA%\MP3 Playlist Downloader\settings.json
%APPDATA%\MP3 Playlist Downloader\logs\app.log
%USERPROFILE%\Music\MP3 Playlist Downloader\<playlist>\<track>.mp3
```

The output root is configurable; changing it affects newly added playlists only. `MP3PD_DATA_DIR` overrides application data for tests/development. YouTube may rate-limit unauthenticated downloads; private or age-restricted playlists may need cookies. Cookies are sensitive and stay on the machine: do not share them or paste them into logs. See [YouTube setup](docs/SETUP_YOUTUBE.md) and [mp3gain setup](docs/SETUP_MP3GAIN.md).

## Build and troubleshooting

Run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1` to test and create a PyInstaller onedir. If Inno Setup 6 is present, it also compiles a per-user installer. Existing onedir outputs are not overwritten. See [packaging](docs/PACKAGING.md) and the [manual checklist](docs/MANUAL_TEST.md).

- **ffmpeg missing:** install it, add it to PATH, place it in `tools\ffmpeg\`, or choose its executable in Settings.
- **mp3gain missing:** configure/install it or leave equalization off; downloaded MP3s remain usable.
- **Bot check/rate limit:** pause, retry later, and consider cookies. Keep yt-dlp current; a bundled application must be rebuilt to update it.
- **Files or settings unavailable:** check folder permissions and `logs\app.log`. A failed recycle operation leaves the tracked DB state unchanged.

The real YouTube, mp3gain and Windows installer workflows still require a manual smoke test in an environment with those prerequisites. See [the requirement map](docs/SPEC.md) for known limitations.
