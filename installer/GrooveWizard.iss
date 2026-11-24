; Instalador Windows (Inno Setup 6). Gerado por build.ps1 depois do PyInstaller.
#define AppName "GrooveWizard"
#ifndef AppVersion
  #define AppVersion "1.5.1"
#endif

[Setup]
AppId={{6F1C7B2E-3E7A-4B8E-9D47-2B9E6C1A5F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=devCidras
AppPublisherURL=https://github.com/devCidras/groovewizard
DefaultDirName={autopf}\GrooveWizard
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; deixa escolher: so para mim (sem admin) ou para todos
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=GrooveWizard-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\organizador\recursos\groovewizard.ico
UninstallDisplayIcon={app}\GrooveWizard.exe
ShowLanguageDialog=yes

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\Portuguese.isl"; LicenseFile: "build\termos_pt.txt"
Name: "en"; MessagesFile: "compiler:Default.isl"; LicenseFile: "build\termos_en.txt"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; versions up to 1.1.0 were called Cratekeeper
Type: files; Name: "{app}\Cratekeeper.exe"
Type: files; Name: "{autoprograms}\Cratekeeper.lnk"
Type: files; Name: "{autodesktop}\Cratekeeper.lnk"

[Files]
; dist\GrooveWizard already holds LICENSE.txt (GPL-3.0) and licencas\ (third-party licenses + source offer)
Source: "..\dist\GrooveWizard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\GrooveWizard.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\GrooveWizard.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\GrooveWizard.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
