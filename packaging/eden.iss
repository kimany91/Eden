; Eden installer (Inno Setup 6). Built by .github/workflows/windows-installer.yml:
;   ISCC packaging\eden.iss /DAppVersion=x.y.z
; Per-user install: no administrator rights needed, and automatic updates
; can replace the program silently.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F2C3A4E-7B1D-4E6B-9C8E-EDE0A1B2C3D4}
AppName=Eden
AppVersion={#AppVersion}
AppVerName=Eden {#AppVersion}
AppPublisher=Eden
DefaultDirName={localappdata}\Programs\Eden
DefaultGroupName=Eden
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist-installer
OutputBaseFilename=Eden-Setup-{#AppVersion}
SetupIconFile=..\src\eden\assets\eden.ico
UninstallDisplayIcon={app}\Eden.exe
UninstallDisplayName=Eden
WizardStyle=modern
WizardImageFile=build-art\wizard-100.bmp,build-art\wizard-150.bmp,build-art\wizard-200.bmp
WizardSmallImageFile=build-art\wizard-small-100.bmp,build-art\wizard-small-150.bmp,build-art\wizard-small-200.bmp
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer une icône sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "..\dist\Eden\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; old program files are replaced on update (user data lives elsewhere, in %LOCALAPPDATA%\Eden)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Eden"; Filename: "{app}\Eden.exe"
Name: "{autodesktop}\Eden"; Filename: "{app}\Eden.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Eden.exe"; Description: "Lancer Eden"; Flags: nowait postinstall skipifsilent
; after a silent automatic update, start the new version again
Filename: "{app}\Eden.exe"; Flags: nowait; Check: ShouldRelaunch

[Code]
function CmdLineParamExists(const Value: string): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Value) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

{ /NOLAUNCH is used by the automated installer test }
function ShouldRelaunch(): Boolean;
begin
  Result := WizardSilent and not CmdLineParamExists('/NOLAUNCH');
end;
