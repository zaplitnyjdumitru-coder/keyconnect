; Установщик KeyConnect для Windows (Inno Setup 6).
; Ставится без прав администратора в %LOCALAPPDATA%\Programs\KeyConnect, как Hiddify.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8C1F5B2E-4D1A-4B7E-9F3A-2E6C1D7A9B10}
AppName=KeyConnect
AppVersion={#AppVersion}
AppPublisher=KeyConnect
DefaultDirName={localappdata}\Programs\KeyConnect
DefaultGroupName=KeyConnect
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=KeyConnect-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\KeyConnect.exe
UninstallDisplayName=KeyConnect
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\KeyConnect\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\KeyConnect"; Filename: "{app}\KeyConnect.exe"
Name: "{autodesktop}\KeyConnect"; Filename: "{app}\KeyConnect.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\KeyConnect.exe"; Description: "{cm:LaunchProgram,KeyConnect}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM KeyConnect.exe"; Flags: runhidden; RunOnceId: "killapp"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM xray.exe"; Flags: runhidden; RunOnceId: "killxray"
