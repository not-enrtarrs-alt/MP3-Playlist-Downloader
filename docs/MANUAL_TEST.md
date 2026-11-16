✓ = passed, X = failed, ? = could not test

# Manual test plan

Use a small playlist you are authorized to access and **disposable copies** of MP3 files. Never use personal originals for destructive or irreversible tests. Real network, mp3gain and installer tests have not been performed in this environment.

## Setup and playlist

- [✓] Run source-venv `doctor`: it reports writable data/output paths, SQLite schema and ffmpeg/ffprobe; missing mp3gain or cookies are warnings.
- [✓] Run `demo --check`: it exits 0 with 2 green, 1 blue, 1 red and 1 yellow. Open `demo` and verify those states; demo data is temporary and gain states are simulated.
- [✓] Add a small valid playlist: its title and ordered tracks appear. Invalid single-video and Mix URLs are rejected. Adding the same playlist again selects the existing one.
- [✓] Switch away and back: cached rows appear immediately without a network fetch. Change the playlist on YouTube and press **Refresh**: new videos appear and removed videos remain marked removed. A title change shows the album update link without moving the folder.

## Downloads and metadata

- [X] Download 1–2 missing tracks: one runs at a time, progress updates, files appear in the playlist folder, and rows turn blue. **Testing note: temp files (cover and song) seem to download but get removed right after**
- [✓] Inspect MP3 tags/cover with an ID3-aware tool: title, artist and playlist album are correct, cover is the video thumbnail, and the ID3 version is 2.3. For a Topic track verify the cleaned artist/title.
- [✓] With an unrelated MP3 using the same title, download another track: the unrelated file remains unchanged and the new file gets a numbered suffix.
- [✓] Enable overwrite and confirm: the old tracked file reaches the Recycle Bin only after the replacement is ready. Cancel the confirmation and verify no files change. Re-download a track via its context menu.
- [✓] Rename a playlist on YouTube and refresh; use **Album tags out of date — Update**. The album changes on downloaded files, other tag frames remain, and the pending link clears only on full success. **Testing note: although the metadata gets updated, the visual progress bar never reaches 100% (I test with 2 files and got stuck at 50%)**

## Equalization and local files

- [✓] Without mp3gain, verify equalization is disabled with instructions and no track turns green. Configure a verified mp3gain CLI; on a **copy**, equalize selected blue tracks and verify successful rows turn green. Gain changes are irreversible.
- [✓] Test automatic equalization only on disposable audio. It is off by default; a failed gain operation must leave the downloaded file and show an unequalized state.
- [✓] Use **Point to MP3 file…** with an external file: the source remains unchanged and a tagged copy appears in the playlist folder. Select an unlinked extra already in that folder: it is adopted in place. Confirm replacement of an existing track.
- [✓] Drop two extra MP3s into a playlist folder and select the playlist. The additional-files dialog opens with nothing checked; choose Keep for one and Delete for the other. Verify the kept file stays yellow and the deleted file is in the Recycle Bin. **Decide later** leaves pending files untouched.
- [✓] Delete selected tracked/extra files after confirmation: verify the files go to the Recycle Bin and track state resets. Simulate a Recycle Bin failure if feasible: the associated DB row must not reset.

## Resume, settings and installer

- [✓] Cancel a batch, close and reopen: pending rows remain queued and require a manual **Resume**. If a real rate limit occurs, verify a countdown, **Resume now**, **Dismiss**, and no more than three immediate failed automatic retries. Do not deliberately stress YouTube to trigger a rate limit.
- [✓] Change output root, theme and cookies settings, save and reopen: values persist. An existing playlist retains its original folder; a newly added playlist uses the new root. Invalid paths remain inline. Only the cookie file's basename is displayed; cookie contents do not appear in logs.
- [✓] In **Tools**, detect ffmpeg and test `mp3gain /?`; verify the actual mp3gain switches before using it. Test cookies only when network access is intended.
- [✓] On a machine with Inno Setup, build the installer, install without elevation, launch via Start Menu, and optionally create a desktop shortcut. Uninstall and reinstall: `%APPDATA%\MP3 Playlist Downloader` and the output library remain intact. This installer test is currently unverified.
