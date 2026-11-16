# Packaging

## Prerequisites

- Windows 10/11 and Python 3.11 or newer.
- Optional: Inno Setup 6 (`ISCC.exe`) for the installer. It was not installed in the development environment, so installer compilation and installation remain unverified.
- Optional bundled tools: place licensed binaries and their required DLLs in `tools\ffmpeg\` (including `ffmpeg.exe` and `ffprobe.exe`) and `tools\mp3gain\` (`mp3gain.exe`). These local directories are gitignored and are not shipped in the repository. Alternatively install the tools on PATH or configure their paths in Settings.

## Build

From PowerShell in the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1
```

The script creates or reuses `.venv`, installs missing project/dev dependencies, runs `pytest -q`, and stops if tests fail. It builds a windowed PyInstaller **onedir** at `dist\MP3 Playlist Downloader\`, collects Qt/yt-dlp data, and copies setup guides and optional tool folders. An existing onedir is never silently overwritten: move it elsewhere before rebuilding. PyInstaller work directories are unique and remain under ignored `build\` for inspection.

If `ISCC.exe` is available on PATH or in a standard Inno Setup 6 location, the script compiles `scripts\installer.iss` with a unique output name so previous installers are not overwritten; otherwise it prints a warning and leaves the onedir build. Install Inno Setup 6 and compile that script manually after the onedir exists. The installer is per-user under `%LOCALAPPDATA%\Programs\MP3 Playlist Downloader`, creates a Start Menu shortcut and an optional desktop shortcut, and includes an uninstaller. Uninstall does **not** delete `%APPDATA%\MP3 Playlist Downloader` or the user's output library.

An offline build works when all dependencies are already installed in `.venv`; otherwise package installation needs cached wheels or network access. To update yt-dlp for YouTube changes, update it in the venv and rebuild the package. yt-dlp is bundled, not updated in place by the installed app.

The windowed executable has no console. Run `doctor`, `demo --check`, and `version` from the source venv rather than expecting visible output from the installer executable. See `README.md` and `MANUAL_TEST.md` for source usage and installation checks.
