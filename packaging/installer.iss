; Instalador de Windows de AstroPhysics Suite -- Fase 9 (empaquetado
; comercial). Compilar con Inno Setup (https://jrsoftware.org/isinfo.php,
; gratuito) DESPUES de generar dist\AstroPhysicsSuite\ con
; packaging\build_windows.bat. Ver packaging\README.md para el flujo
; completo.

#define MyAppName "AstroPhysics Suite"
#define MyAppVersion "0.5.0"
#define MyAppPublisher "AstroPhysics Suite"
#define MyAppExeName "AstroPhysicsSuite.exe"
#define MyDistDir "..\dist\AstroPhysicsSuite"

[Setup]
AppId={{B6E2B1B4-6C8B-4E3E-9C8B-ASTROPHYSICS1}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; El instalador se genera en packaging\output\ (no en la raiz del repo)
OutputDir=output
OutputBaseFilename=AstroPhysicsSuite-{#MyAppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Requiere que dist\AstroPhysicsSuite\ ya exista (ver build_windows.bat) --
; Inno Setup no construye el propio ejecutable, solo lo empaqueta.
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Copia todo el contenido de la carpeta que produjo PyInstaller (modo
; onedir: el .exe mas sus dependencias) -- ver AstroPhysicsSuite.spec.
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
