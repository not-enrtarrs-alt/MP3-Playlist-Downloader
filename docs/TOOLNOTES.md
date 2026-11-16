# Environment discovery

- Windows NT 10.0.26200.0; Python 3.11.4, system installation; no project venv at discovery.
- Installed system packages: yt-dlp 2026.7.4, mutagen 1.47.0, requests 2.31.0. Missing: PySide6, send2trash, pytest, pytest-qt, pytest-mock, pyinstaller.
- PATH: ffmpeg and ffprobe version N-55702-g920046a. mp3gain absent from PATH and `tools/mp3gain/mp3gain.exe`; `/ ?` help and `/r /k /s s` flags not verified. Do not assume verified until an actual binary is available.
- ISCC.exe absent from PATH and standard Program Files / local per-user Inno Setup 6 locations.
- APPDATA writable; default output root does not yet exist, nearest existing ancestor writable. Actual root creation will be tested by settings validation.
- YouTube HEAD request returned HTTP 200; runtime and tests must not depend on network.
- `main_fixed.py` exists; initial SHA-256 `D7D1A9A64F2492CDB3088625918CA4AB468BD8BF5464698B5E0D871C62F5CACA`. No earlier hash was available, so previous changes cannot be determined. Do not modify.
- `rl-analyzer-prompt.txt` initial SHA-256 `B1EDB6C4203EBE7AB81324FFAFECCDDEAB20FE70F69788061A87621A3975E6E4`; do not modify.
- Project `.venv` created and installed with editable project plus dev extras: PySide6 6.12.0, yt-dlp 2026.10.26, mutagen 1.48.1, send2trash 2.1.0, requests 2.34.2, pytest 9.2.0, pytest-qt 4.5.0, pytest-mock 3.17.0, pyinstaller 6.22.3.
- M0 acceptance: offline doctor returned exit 0 with no errors, both ffmpeg tools found and optional-cookie/mp3gain warnings; Qt offscreen startup, database creation and exit passed; full test suite 36 passed.
- Both reference hashes match the discovery baseline at M0 checkpoint; earlier history remains unknown.
- M1 session rediscovery: Windows build 26200, Python 3.11.4 in `.venv`; dependency versions unchanged from the M0 venv listing. ffmpeg/ffprobe N-55702-g920046a are on PATH; mp3gain and ISCC remain absent from PATH and checked standard locations; mp3gain flags remain unverified. APPDATA and the nearest existing output-root ancestor are writable; output root does not yet exist. YouTube HEAD returned 200. Both reference hashes match the initial baseline. Baseline: 36 tests passed.
- M1 acceptance: full offline suite 76 passed; reference hashes remain unchanged. No interactive real YouTube fetch or Windows visible-desktop test was performed.
- M2 session rediscovery: Windows build 26200, Python 3.11.4 in `.venv`; package versions remain as listed above. ffmpeg and ffprobe N-55702-g920046a on PATH; mp3gain and ISCC absent in PATH and checked standard locations; mp3gain flags remain unverified. APPDATA and the nearest existing output-root ancestor are writable; default output root does not exist. YouTube HEAD returned 200. Both reference hashes still match the initial baseline. Baseline: 76 tests passed.
- This old ffmpeg rejects `-hide_banner`; the offline silent MP3 fixture generator omits that flag and successfully generated a real MP3 for ID3 tests.
- This ffmpeg also failed to recognize PNG bytes under an `.input` extension; using a detected `.png` extension succeeded. The cover converter identifies PNG/WebP/GIF signatures before invoking ffmpeg.
- M2 acceptance: 116 offline tests passed; `demo --check` returned 0 with 2 green, 1 blue, 1 red, and 1 yellow. Reference hashes still match the initial baseline. Real YouTube, real Recycle Bin and real mp3gain were not exercised.
- M3 session rediscovery: Windows build 26200, Python 3.11.4 in `.venv`; package versions match the M2 venv listing. ffmpeg/ffprobe N-55702-g920046a remain on PATH; mp3gain and ISCC remain absent from PATH and checked standard locations. mp3gain help and flags cannot be verified here. APPDATA and nearest existing output-root ancestor are writable; default output root is absent. YouTube HEAD returned 200. Both reference hashes match the baseline. Baseline: 116 tests passed.
- M3 acceptance: 143 offline tests passed; `demo --check` and isolated `doctor --json` returned 0. Doctor warned that mp3gain and cookies were absent. Reference hashes remain unchanged. Actual mp3gain help, flags and audio effects remain unverified.
- M4 session rediscovery: Windows build 26200, Python 3.11.4 in `.venv`; package versions match the M3 venv listing. ffmpeg/ffprobe N-55702-g920046a remain on PATH; mp3gain and ISCC absent from PATH and checked standard locations, so mp3gain flags remain unverified. APPDATA and the nearest existing output-root ancestor are writable; default output root is absent. YouTube HEAD returned 200. Both reference hashes match the baseline. Baseline: 143 tests passed.
- M4 acceptance: 177 offline tests passed; `demo --check` and isolated `doctor --json` returned 0. Both reference hashes match the initial baseline. Real YouTube downloads, cookies, mp3gain, Recycle Bin, and visible-desktop behavior remain untested.
- M5 session rediscovery: Windows build 26200, Python 3.11.4 in `.venv`; dependency versions match the M4 venv listing. ffmpeg/ffprobe N-55702-g920046a on PATH; mp3gain and ISCC absent from PATH and checked standard locations. mp3gain flags remain unverified. APPDATA and nearest existing output-root ancestor are writable; default output root is absent. YouTube HEAD returned 200. Both reference hashes match the baseline. Baseline: 177 tests passed.
- M5 offline build (`PIP_NO_INDEX=1`) reused installed dependencies, passed 183 tests and produced a PyInstaller onedir. Inno Setup is absent, so no installer was compiled. No ffmpeg/mp3gain binaries were bundled. PyInstaller reported optional Qt SQL-driver DLLs and optional yt-dlp dependencies missing; SQLite uses Python's sqlite3, not those Qt drivers.
- Frozen onedir smoke test: windowed `version` exited 0; the GUI created an isolated database, opened a Windows main window, and closed normally with exit 0. The initial onedir contained approximately 4,895 files / 666.6 MB; package size may vary by PySide6 version.
- Final onedir rebuilt offline after doctor/demo/documentation changes; build ran 188 passing tests. The earlier onedir was preserved under a unique sibling directory. No tools were bundled and ISCC remained unavailable.
- Final redaction-hardened onedir rebuilt offline with 189 passing tests. Frozen `version`, `doctor --json`, and `demo --check` exited 0; the frozen GUI created an isolated database and closed normally. The earlier builds remain preserved. No installer was compiled because ISCC is absent.
- M6 session rediscovery: Windows build 26200, Python 3.11.4 in `.venv`; dependency versions match M5. ffmpeg/ffprobe N-55702-g920046a remain on PATH; mp3gain and ISCC are absent from PATH and checked standard locations here. APPDATA and the nearest existing output-root ancestor are writable; default output root is absent. YouTube HEAD returned 200. Both reference hashes match the baseline. Offline baseline: 189 tests passed.
- M6: The user's existing settings point to a working mp3gain CLI even though it is absent from PATH and `tools/`. Its `/ ?` help exited 0, identifies version 1.5.2, and verifies `/r` (track gain), `/k` (prevent clipping), and `/s s` (do not read or write gain tags). The configured ffmpeg is N-55702-g920046a. Paths and cookie contents were not recorded.
- M6: Offline yt-dlp audio extraction succeeded with the configured ffmpeg, while its thumbnail converter failed on a generated PNG. This reproduces a plausible cause of the user's download symptom but is not proof of their individual failed downloads.
- M6: On a disposable synthetic MP3, the configured mp3gain 1.5.2 command succeeded, changed audio bytes, preserved ID3 title/album/cover, and did not create an APE tag. A separate offline real yt-dlp/ffmpeg pipeline reproduced the thumbnail failure and successfully retained a tagged MP3 with JPEG cover and no temporary leftovers after the fix.
- M6: Rebuilt the updated onedir offline after preserving the previous build separately; 206 tests passed during the build. ISCC remains unavailable in the checked locations, so no updated installer was compiled.
- M6: The rebuilt Windows GUI opened with explicitly selected light mode; a capture of the isolated empty window showed readable dark text on light surfaces. Frozen `version`, `doctor --json` and `demo --check` exited 0. Reference hashes remain unchanged. The real YouTube download was not repeated; the user must retest the updated build.
- Official-title cleanup: the user's supplied example list informed offline parsing tests. The first updated onedir build passed 245 tests; a later small version-label refinement passed 64 focused tests. Real YouTube download acceptance remains pending.
- Official-title cleanup final onedir rebuilt offline with 249 passing tests; earlier onedir outputs were preserved. ISCC remains unavailable, so no new installer was compiled.
- Official-title cleanup frozen smoke: the updated GUI created an isolated database and closed normally; frozen `version`, `doctor --json`, and `demo --check` exited 0. Both read-only reference hashes still match the baseline.
- Title-cleanup session rediscovery: Windows build 26200, Python 3.11.4 in `.venv`; dependency versions match M6. ffmpeg/ffprobe N-55702-g920046a remain on PATH; mp3gain and ISCC remain absent from PATH and checked standard locations. APPDATA and the nearest existing output-root ancestor are writable; default output root is absent. YouTube HEAD returned 200. Both reference hashes match the baseline. Offline baseline: 206 tests passed.
- Manual-rename session rediscovery: Windows build 26200, Python 3.11.4 in `.venv`; package versions match the prior session. ffmpeg/ffprobe N-55702-g920046a are on PATH; mp3gain and ISCC are absent from PATH and checked standard locations (the previously configured mp3gain 1.5.2 was verified separately). APPDATA and the nearest existing output-root ancestor are writable; default output root is absent. YouTube HEAD returned 200. Both reference hashes match the baseline. Offline baseline: 249 tests passed.
- A local `mp3gain.exe` at the repository root and an existing installer under ignored `dist/installer/` were discovered after the initial PATH check. They are user work and were not modified; source doctor can discover the root executable via the current working directory.
- Manual rename acceptance: the offline onedir build passed 282 tests, then the final suite passed 284 tests after two additional safeguards. A frozen GUI migrated a synthetic schema-1 DB to schema 2 while preserving its raw title and queued state, then exited 0. Reference files, local mp3gain and the existing installer matched their pre-build hashes. The user will rebuild the installer.

### Configured mp3gain 1.5.2 `/ ?` help (local executable path redacted)

```text
[local path] version 1.5.2
copyright(c) 2001-2009 by Glen Sawyer
uses mpglib, which can be found at http://www.mpg123.de
Usage: [local path] [options] <infile> [<infile 2> ...]
options:
  /v - show version number
  /g <i> - apply gain i without doing any analysis
  /l 0 <i> - apply gain i to channel 0 (left channel) without doing any analysis (ONLY works for STEREO files, not Joint Stereo)
  /l 1 <i> - apply gain i to channel 1 (right channel) without doing any analysis (ONLY works for STEREO files, not Joint Stereo)
  /e - skip Album analysis, even if multiple files listed
  /r - apply Track gain automatically (all files set to equal loudness)
  /k - automatically lower Track/Album gain to not clip audio
  /a - apply Album gain automatically (files are all from the same album: a single gain change is applied to all files, so their loudness relative to each other remains unchanged, but the average album loudness is normalized)
  /m <i> - modify suggested MP3 gain by integer i
  /d <n> - modify suggested dB gain by floating-point n
  /c - ignore clipping warning when applying gain
  /o - output is a database-friendly tab-delimited list
  /t - writes modified data to temp file, then deletes original instead of modifying bytes in original file
  /q - Quiet mode: no status messages
  /p - Preserve original file timestamp
  /x - Only find max. amplitude of file
  /f - Assume input file is an MPEG 2 Layer III file (i.e. don't check for mis-named Layer I or Layer II files)
  /? or /h - show this message
  /s c - only check stored tag info (no other processing)
  /s d - delete stored tag info (no other processing)
  /s s - skip (ignore) stored tag info (do not read or write tags)
  /s r - force re-calculation (do not read tag info)
  /s i - use ID3v2 tag for MP3 gain info
  /s a - use APE tag for MP3 gain info (default)
  /u - undo changes made (based on stored tag info)
  /w - "wrap" gain change if gain+change > 255 or gain+change < 0 (use "/? wrap" switch for a complete explanation)
If you specify /r and /a, only the second one will work
If you do not specify /c, the program will stop and ask before applying gain change to a file that might clip
```
