#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{CE2CB547-A101-45D0-A1B9-2A6AC29C8815}
AppName=Actor Workbench
AppVersion={#AppVersion}
AppPublisher=playbenni
AppPublisherURL=https://github.com/playbenni/ActorWorkbench
AppSupportURL=https://github.com/playbenni/ActorWorkbench/issues
AppUpdatesURL=https://github.com/playbenni/ActorWorkbench/releases
DefaultDirName={localappdata}\Programs\ActorWorkbench
DefaultGroupName=Actor Workbench
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=ActorWorkbench-{#AppVersion}-Setup-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ActorWorkbench.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
InfoBeforeFile=install-info.txt

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\ActorWorkbench\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\VALIDATION.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Actor Workbench"; Filename: "{app}\ActorWorkbench.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Actor Workbench"; Filename: "{app}\ActorWorkbench.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\ActorWorkbench.exe"; Description: "Launch Actor Workbench"; Flags: nowait postinstall skipifsilent
