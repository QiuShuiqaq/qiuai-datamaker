#define MyAppName "QiuAi Datamaker"
#define MyAppExeName "QiuAiDatamaker.exe"
#define MyAppVersion "1.0.4"
#define MyBuildDir "..\package\QiuAiDatamaker"

[Setup]
AppId={{F0C7874D-3B24-4F87-A343-DC4F2D6C1F44}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\QiuAi Datamaker
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\package
OutputBaseFilename=QiuAiDatamaker-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=icon\Q1.ico
UninstallDisplayIcon={app}\QiuAiDatamaker.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "{#MyBuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
