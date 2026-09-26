#ifndef AuroraLegacyBuild
  #error Explicit legacy build required; this is not the v4 installer
#endif
#define MyAppName "Project Aurora Legacy"
#ifndef MyAppVersion
  #error MyAppVersion must be supplied by build_installer.ps1
#endif
#ifndef MyAppWindowsVersion
  #error MyAppWindowsVersion must be supplied by build_installer.ps1
#endif
#define MyAppPublisher "Project Aurora"
#define MyAppExeName "Aurora.exe"

[Setup]
; Separate compatibility product identity; never upgrade a production install.
AppId={{3A2D7748-0BF4-4D85-ABAE-14B60E04538B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppWindowsVersion}
VersionInfoTextVersion={#MyAppVersion}
VersionInfoProductTextVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Aurora-Legacy
DefaultGroupName=Project Aurora Legacy
DisableProgramGroupPage=no
OutputDir=.
OutputBaseFilename=Aurora-v{#MyAppVersion}-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimp"; MessagesFile: "{#SourcePath}\Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Aurora-Core\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Project Aurora Legacy"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Project Aurora Legacy"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
