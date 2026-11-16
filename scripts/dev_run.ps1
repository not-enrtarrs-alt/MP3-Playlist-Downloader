$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Project virtual environment not found. Run python -m venv .venv and install -e ".[dev]" first.'
}
$env:MP3PD_DEBUG = '1'
& $python -m mp3_playlist_downloader @args
exit $LASTEXITCODE
