#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef MyDistDir
  #define MyDistDir "..\dist\MP3 Playlist Downloader"
#endif
#define MyAppName "MP3 Playlist Downloader"
#define MyAppExe "MP3 Playlist Downloader.exe"

[Setup]
AppId={{8B78C742-FB54-4C3A-A3B4-39A7D54CF21C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=MP3 Playlist Downloader
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=MP3-Playlist-Downloader-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExe}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
