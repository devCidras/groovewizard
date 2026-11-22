; Instalador Windows (Inno Setup 6). Gerado por build.ps1 depois do PyInstaller.
#define AppName "Cratekeeper"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6F1C7B2E-3E7A-4B8E-9D47-2B9E6C1A5F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=devCidras
AppPublisherURL=https://github.com/devCidras/cratekeeper
DefaultDirName={autopf}\Cratekeeper
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; deixa escolher: so para mim (sem admin) ou para todos
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Cratekeeper-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\organizador\recursos\cratekeeper.ico
UninstallDisplayIcon={app}\Cratekeeper.exe
ShowLanguageDialog=yes

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\Portuguese.isl"; LicenseFile: "build\termos_pt.txt"
Name: "en"; MessagesFile: "compiler:Default.isl"; LicenseFile: "build\termos_en.txt"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Cratekeeper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Cratekeeper.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Cratekeeper.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Cratekeeper.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
