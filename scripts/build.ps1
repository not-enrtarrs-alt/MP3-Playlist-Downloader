$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$appName = 'MP3 Playlist Downloader'
$distRoot = Join-Path $root 'dist'
$appDist = Join-Path $distRoot $appName

if (Test-Path -LiteralPath $appDist) {
    throw 'The onedir output already exists. Move it elsewhere before building; it was not changed.'
}

Push-Location $root
try {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        & python -m venv (Join-Path $root '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the project virtual environment.' }
    }

    & $python (Join-Path $PSScriptRoot 'dependency_probe.py') $root
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing the project and development dependencies (network or cached wheels may be required)...'
        & $python -m pip install -e ($root + '[dev]')
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    } else {
        Write-Host 'Using already-installed project and development dependencies (offline).'
    }

    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; no build will be produced.' }

    $version = (& $python -c 'from mp3_playlist_downloader import __version__; print(__version__)').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $version) { throw 'Could not read the application version.' }
    $workRoot = Join-Path $root ('build\pyinstaller-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
    $arguments = @(
        '-m', 'PyInstaller', '--onedir', '--windowed',
        '--name', $appName, '--paths', (Join-Path $root 'src'),
        '--distpath', $distRoot, '--workpath', (Join-Path $workRoot 'work'), '--specpath', $workRoot,
        '--collect-data', 'PySide6', '--collect-all', 'yt_dlp',
        '--copy-metadata', 'PySide6', '--copy-metadata', 'yt-dlp'
    )
    $icon = Join-Path $root 'assets\app.ico'
    if (Test-Path -LiteralPath $icon -PathType Leaf) { $arguments += @('--icon', $icon) }
    $arguments += (Join-Path $PSScriptRoot 'launcher.py')
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed. Existing partial build files were left for inspection.' }

    $docTarget = Join-Path $appDist 'docs'
    New-Item -ItemType Directory -Path $docTarget -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root 'docs\SETUP_YOUTUBE.md') -Destination $docTarget
    Copy-Item -LiteralPath (Join-Path $root 'docs\SETUP_MP3GAIN.md') -Destination $docTarget
    Copy-Item -LiteralPath (Join-Path $root 'README.md') -Destination $appDist

    foreach ($tool in @('ffmpeg', 'mp3gain')) {
        $source = Join-Path $root "tools\$tool"
        if (Test-Path -LiteralPath $source -PathType Container) {
            $destination = Join-Path $appDist 'tools'
            New-Item -ItemType Directory -Path $destination -Force | Out-Null
            Copy-Item -LiteralPath $source -Destination (Join-Path $destination $tool) -Recurse
        } else {
            Write-Warning "$tool was not bundled; configure its path or install it separately."
        }
    }

    $candidates = @()
    $onPath = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($onPath) { $candidates += $onPath.Source }
    if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe') }
    if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe') }
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe') }
    $iscc = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if ($iscc) {
        $installerName = 'MP3-Playlist-Downloader-Setup-' + $version + '-' + [Guid]::NewGuid().ToString('N')
        $installerOutput = Join-Path (Join-Path $distRoot 'installer') ($installerName + '.exe')
        if (Test-Path -LiteralPath $installerOutput) { throw 'The installer destination already exists and was not changed.' }
        & $iscc ("/DMyAppVersion=$version") ("/F$installerName") (Join-Path $PSScriptRoot 'installer.iss')
        if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed; the onedir build remains available.' }
    } else {
        Write-Warning 'Inno Setup ISCC.exe was not found. Install Inno Setup 6 and compile scripts\installer.iss; the onedir build is available.'
    }
    Write-Host "Onedir build: $appDist"
    Write-Host 'Updating yt-dlp in a packaged app requires rebuilding.'
} finally {
    Pop-Location
}
