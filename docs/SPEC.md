# Condensed specification

Windows PySide6 playlist-to-MP3 application using yt-dlp's Python API, ffmpeg, SQLite tracking, optional mp3gain and ID3v2.3 metadata. Persist queue state, avoid unrelated file overwrite, recycle user files rather than permanently deleting, never automatically refresh, and operate safely without mp3gain or network. `mp3-playlist-downloader-prompt.txt` is the full authoritative specification.

## Requirement map

| Area | Implementation |
|---|---|
| Per-user paths, settings, validation and atomic JSON | `paths.py`, `settings.py`; `MP3PD_DATA_DIR` isolates tests/demo. Existing playlist folder paths never follow later root changes. |
| SQLite schema, WAL, foreign keys, per-thread connections, refresh transactions | `db.py`; schema 1 migrates transactionally to schema 2 for per-video custom titles. Downloaded and equalized state belong to each playlist/video pair, not a filename. |
| Playlist URL validation, flat parsing, topic and official-title cleanup, duplicates | `youtube/parse.py`, `youtube/client.py`, `models.py`; official titles remove recognized labels/credits only when a credited primary artist matches the uploader. `services.py` performs explicit add/refresh. Selection uses cached DB rows only. |
| Sequential yt-dlp/ffmpeg MP3 conversion, thumbnails, tags, cleanup | `youtube/download.py`, `tagging.py`, `queue.py`; tagging failure preserves downloaded audio with a warning. |
| Collision safety, scans, extra files and explicit Recycle Bin deletes | `library.py`, `ui/library_controller.py`, `ui/extra_files_dialog.py`; no unknown file is automatically deleted. |
| Queue persistence, retry, rate limits, cancellation and restart | `queue.py`, `ui/queue_controller.py`; launch requires manual resume, automatic retries are capped at three. |
| mp3gain discovery, track gain, opt-in automatic/selected equalization | `equalizer.py`, `services.py`, `ui/equalizer_controller.py`; failed or missing equalization never marks a row equalized. |
| Manual link, rename, overwrite, re-download and album retag | `linking.py`, `renaming.py`, `youtube/download.py`, `services.py`, `ui/edit_controller.py`; custom titles persist across refreshes/downloads and old files are preserved or recycled safely. |
| Qt main window, checkboxes, colors, toolbar, settings, worker threads | `ui/`; text accompanies status colors and workers create their own SQLite connections. |
| Single-instance lock, logs and safe diagnostic CLI | `app.py`, `logging_setup.py`, `cli.py`, `demo.py`; `doctor`, `demo --check` and `version` are source-venv commands. |
| Onedir packaging and per-user installer | `scripts/build.ps1`, `scripts/installer.iss`; installer never removes the app-data folder. |
| Offline coverage and manually verified workflows | `tests/`, `docs/MANUAL_TEST.md`; network, cookies, mp3gain and Recycle Bin calls are faked in automated tests. |

## Documented limitations

- The user reports successful playlist, cookies, local-file, Recycle Bin, gain and installer checks, but an actual YouTube download failed. An offline thumbnail-conversion failure was reproduced and fixed; the real download still needs a user retest. YouTube can change, rate-limit or require current yt-dlp and cookies.
- `/r /k /s s` was verified against the user's configured mp3gain 1.5.2 on disposable synthetic audio; verify other builds with `/?`. Gain changes are irreversible, and a failed invocation may already have altered the file.
- The user reports an installer check passed; Inno Setup remains absent from this environment's PATH and standard locations, so this agent has not independently compiled or installed the script. The PyInstaller onedir was built and its GUI smoke-tested.
- ID3v2.3 has no UTF-8 text encoding; mutagen serializes text in a v2.3-compatible encoding. Demo equalized states are simulated.
- The GUI uses paired Qt palettes and targeted light/dark styling; error dialogs and inline errors show sanitized concise messages rather than a universal details expander.
- Cancelling a blocking yt-dlp playlist fetch discards its eventual result but cannot interrupt the underlying request. Removed/unavailable tracks cannot be manually re-downloaded until a refresh restores them.
- An explicitly adopted extra is tagged in place before an old-file recycle attempt. If recycling fails, the old tracked file and DB row stay unchanged, but the selected extra's tags may have changed. Symlinks and multiply hard-linked sources are copied to protect external files.
- Manual rename stages a tagged copy and preserves the original until SQLite is updated. If recycling the original backup fails, it remains as an additional MP3 for the user to review. Earlier application versions reject the newer schema rather than modifying it.
- Official-title cleanup deliberately leaves mismatched artists, malformed brackets and unrecognized title parentheticals unchanged rather than guessing. Manual links retain their source-derived or adopted filenames; no existing file is renamed by this feature.
- The installed ffmpeg is old; fixture generation and PNG conversion were verified, but actual YouTube postprocessing compatibility has not been exercised.
