; Script de Inno Setup para generar un instalador de Dossier Builder QA/QC.
;
; Requiere tener compilado antes dist\DossierBuilderQAQC.exe (build_exe.bat)
; y Inno Setup instalado (gratuito): https://jrsoftware.org/isinfo.php
;
; Para compilar el instalador:
;   1. Abrir este archivo con Inno Setup Compiler (ISCC), o
;   2. Desde la linea de comandos: ISCC installer.iss
;
; El instalador resultante queda en installer_output\DossierBuilderQAQC_Setup.exe

#define MyAppName "Dossier Builder QA/QC"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Romao Israel Landazuri Balseca"
#define MyAppExeName "DossierBuilderQAQC.exe"

[Setup]
; Identificador fijo de la aplicacion (no cambiar entre versiones: permite
; que el instalador detecte una instalacion previa y la actualice en vez de
; crear una segunda entrada duplicada en "Agregar o quitar programas").
AppId={{4F2B8B0E-6C6B-4B7B-9C0B-2E7A6E5C9B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}

; Instalacion "por usuario" (no en Archivos de Programa) para que NO haga
; falta ser administrador ni tener permisos especiales del equipo: cada
; persona que use este instalador lo instala en su propia carpeta de
; usuario, sin pedir aprobacion de TI para la instalacion en si.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\DossierBuilderQAQC
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=installer_output
OutputBaseFilename=DossierBuilderQAQC_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el Escritorio"; GroupDescription: "Accesos directos adicionales:"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar {#MyAppName}"; Flags: nowait postinstall skipifsilent
