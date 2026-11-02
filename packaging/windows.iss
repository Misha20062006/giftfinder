#ifndef AppVersion
  #error AppVersion is required
#endif
[Setup]
AppId=io.github.Misha20062006.GiftFinder
AppName=GiftFinder
AppVersion={#AppVersion}
AppPublisher=Misha20062006
AppPublisherURL=https://github.com/Misha20062006/giftfinder
AppUpdatesURL=https://github.com/Misha20062006/giftfinder/releases
DefaultDirName={localappdata}\Programs\GiftFinder
DefaultGroupName=GiftFinder
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir={#OutputDir}
OutputBaseFilename=GiftFinder-{#AppVersion}-Windows-x64-Setup
SetupIconFile={#SourceRoot}\giftfinder\icon.ico
UninstallDisplayIcon={app}\GiftFinder.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\GiftFinder"; Filename: "{app}\GiftFinder.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\GiftFinder"; Filename: "{app}\GiftFinder.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\GiftFinder.exe"; Description: "GiftFinder"; Flags: nowait postinstall skipifsilent; Check: ShouldLaunch
Filename: "{app}\GiftFinder.exe"; Flags: nowait; Check: ShouldLaunchUpdate

[Code]
function ShouldLaunch: Boolean;
begin
  Result := not CmdLineParamExists('/NOAUTORUN') and not CmdLineParamExists('/UPDATE');
end;

function ShouldLaunchUpdate: Boolean;
begin
  Result := CmdLineParamExists('/UPDATE') and not CmdLineParamExists('/NOAUTORUN');
end;
