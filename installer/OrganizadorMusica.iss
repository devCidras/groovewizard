; Instalador Windows (Inno Setup 6). Gerado por build.ps1 depois do PyInstaller.
#define AppName "Organizador de Musica"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6F1C7B2E-3E7A-4B8E-9D47-2B9E6C1A5F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=devCidras
AppPublisherURL=https://github.com/devCidras/organizador-musica
DefaultDirName={autopf}\Organizador de Musica
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; deixa escolher: so para mim (sem admin) ou para todos
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=OrganizadorMusica-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\OrganizadorMusica.exe
ShowLanguageDialog=yes

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\Portuguese.isl"; LicenseFile: "build\termos_pt.txt"
Name: "en"; MessagesFile: "compiler:Default.isl"; LicenseFile: "build\termos_en.txt"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\OrganizadorMusica\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\OrganizadorMusica.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\OrganizadorMusica.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OrganizadorMusica.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
