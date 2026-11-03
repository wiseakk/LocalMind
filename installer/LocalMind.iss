#ifndef Payload
  #define Payload "..\dist\LocalMind"
#endif
[Setup]
AppId={{E51E0AD1-BB08-4EC7-95B8-0A50D0543A88}
AppName=LocalMind
AppVersion=1.0.0
DefaultDirName={localappdata}\Programs\LocalMind
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DefaultGroupName=LocalMind
OutputDir=..\dist
#ifdef OfflineBundle
OutputBaseFilename=LocalMind-Offline-Setup
#else
OutputBaseFilename=LocalMind-Setup
#endif
Compression=lzma2/fast
SolidCompression=yes
UninstallDisplayIcon={app}\LocalMind.exe
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
[Languages]
Name: russian; MessagesFile: "compiler:Languages\Russian.isl"
[Tasks]
Name: desktopicon; Description: "Создать ярлык на рабочем столе"
Name: ollama; Description: "Локальный движок нейросети Ollama (если ещё не установлен)"
[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Excludes: "*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\LocalMind"; Filename: "{app}\LocalMind.exe"
Name: "{autodesktop}\LocalMind"; Filename: "{app}\LocalMind.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\prerequisites\OllamaSetup.exe"; Tasks: ollama; Flags: waituntilterminated; Check: not OllamaPresent
Filename: "{app}\LocalMind.exe"; Description: "Запустить LocalMind"; Flags: postinstall nowait skipifsilent
[Code]
function OllamaPresent: Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
end;
// Uninstall removes only installed files. User models/settings are retained.
