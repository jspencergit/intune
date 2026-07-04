; Inno Setup script — optional Windows installer (compile with Inno Setup 6+)
;   iscc installer\intune-viz.iss
;
; Prerequisite: run ..\package.ps1 -SkipBuild and stage files in ..\dist\Intune\

#define MyAppName "Intune Visualizer"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "Analog Intuition"
#define MyAppURL "https://analogintuition.com/intune/"
#define MyAppExeName "intune_viz.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\Intune
DefaultGroupName=Intune
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Intune-Visualizer-Setup-v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Intune\intune_viz.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\Intune\raylib.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\Intune\glfw3.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\Intune\README.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--simulate"
Name: "{group}\{#MyAppName} (Teensy COM3)"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--port COM3"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--simulate"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Parameters: "--simulate"; Flags: nowait postinstall skipifsilent