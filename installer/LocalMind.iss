#ifndef Payload
  #define Payload "..\dist\LocalMind"
#endif
#ifndef ReleaseVersion
  #define ReleaseVersion "1.0.0-rc2"
#endif
[Setup]
AppId={{E51E0AD1-BB08-4EC7-95B8-0A50D0543A88}
AppName=LocalMind
AppVersion={#ReleaseVersion}
DefaultDirName={localappdata}\Programs\LocalMind
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DefaultGroupName=LocalMind
OutputDir=..\dist
#ifdef OfflineBundle
OutputBaseFilename=LocalMind-{#ReleaseVersion}-Offline-Setup
#else
OutputBaseFilename=LocalMind-{#ReleaseVersion}-Setup
#endif
Compression=lzma2/fast
SolidCompression=yes
UninstallDisplayIcon={app}\LocalMind.exe
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
SetupIconFile=..\static\assets\localmind.ico
[Languages]
Name: russian; MessagesFile: "compiler:Languages\Russian.isl"
[Tasks]
Name: desktopicon; Description: "Создать ярлык на рабочем столе"
Name: ollama; Description: "Локальный движок нейросети Ollama (если ещё не установлен)"
[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Excludes: "*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\LocalMind"; Filename: "{app}\LocalMind.exe"; AppUserModelID: "LocalMind.Desktop.1"
Name: "{autodesktop}\LocalMind"; Filename: "{app}\LocalMind.exe"; AppUserModelID: "LocalMind.Desktop.1"; Tasks: desktopicon
[Run]
Filename: "{app}\prerequisites\OllamaSetup.exe"; Tasks: ollama; Flags: waituntilterminated; Check: not OllamaPresent
Filename: "{app}\LocalMind.exe"; Description: "Запустить LocalMind"; Flags: postinstall nowait skipifsilent
[Code]
function OllamaPresent: Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
end;
// Uninstall removes only installed files. User models/settings are retained.
