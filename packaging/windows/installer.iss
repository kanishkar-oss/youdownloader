; Inno Setup script for the YouDownloader Windows installer.
; Built by packaging/build.py, which passes AppVersion / SourceDir / OutputDir.
;
; Per-user install (no admin prompt) into %LOCALAPPDATA%\Programs\YouDownloader,
; so the in-app updater can run a new installer silently:
;   YouDownloader-<ver>-windows-setup.exe /SILENT /SP- /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS
; Settings, queue, logs and cookies live in %LOCALAPPDATA%\YouDownloader and
; survive updates and uninstalls.

#define AppName "YouDownloader"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\YouDownloader"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist\release"
#endif

[Setup]
; Never change AppId: it's how updates find the existing install.
AppId={{6F3C2B8E-9A41-4D7B-8E25-3C9A7F1D0B64}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
AppPublisherURL=https://github.com/kanishkar-oss/youdownloader
AppSupportURL=https://github.com/kanishkar-oss/youdownloader/issues
AppUpdatesURL=https://github.com/kanishkar-oss/youdownloader/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-{#AppVersion}-windows-setup
SetupIconFile=..\..\assets\youdownloader.ico
UninstallDisplayIcon={app}\{#AppName}.exe
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Clear the previous version's libraries so nothing stale is left behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
; Shown as a checkbox after a normal install; also runs after a silent update,
; which is how the app restarts itself.
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall
