#define MyAppName "Project Aurora"
#define MyAppVersion "3.7.2"
#define MyAppPublisher "Project Aurora"
#define MyAppExeName "Aurora.exe"

[Setup]
AppId={{B8E983B4-31F8-43A4-8C22-A8F2F68A28F7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Aurora
DefaultGroupName=Project Aurora
DisableProgramGroupPage=no
OutputDir=.
OutputBaseFilename=Aurora-v3.7.2-Setup
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
Source: "..\dist\Aurora\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Project Aurora"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Project Aurora"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
