; Inno Setup script for the Mi Bulb installer.
; Build the app first (dist\MiBulb\ from build.ps1), then:
;   ISCC.exe /DAppVersion=0.5.0 installer\mibulb.iss
;
; Mi Bulb updates itself by running this installer with
;   /SILENT /SUPPRESSMSGBOXES /NORESTART /SP- /UPDATE [/RELAUNCH=--minimized]
; /UPDATE waits for the running app to close and starts it again afterwards.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: Windows uses it to recognise upgrades and the uninstaller.
AppId={{2A6700FD-B38A-43AB-9AB8-3CA82B93A8F6}
AppName=Mi Bulb
AppVersion={#AppVersion}
AppVerName=Mi Bulb {#AppVersion}
AppPublisher=Ayberk Alcan
AppPublisherURL=https://github.com/akanora/mibulb
AppSupportURL=https://github.com/akanora/mibulb/issues
AppUpdatesURL=https://github.com/akanora/mibulb/releases
; Per-user install: no admin prompt needed.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\Mi Bulb
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=MiBulb-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\MiBulb.exe
UninstallDisplayName=Mi Bulb
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "startup"; Description: "Start Mi Bulb in the system tray when I sign in to Windows"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\MiBulb\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Mi Bulb"; Filename: "{app}\MiBulb.exe"
Name: "{autodesktop}\Mi Bulb"; Filename: "{app}\MiBulb.exe"; Tasks: desktopicon

[Registry]
; Same value the app's "Start with Windows" setting uses (mibulb/startup.py).
; The first entry only makes sure uninstall removes it, even if it was
; turned on later from the app.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Mi Bulb"; Flags: uninsdeletevalue
; Automatic updates leave it alone, so turning it off in the app sticks.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Mi Bulb"; ValueData: """{app}\MiBulb.exe"" --minimized"; Flags: uninsdeletevalue; Tasks: startup; Check: not IsUpdate

[InstallDelete]
; v0.2.0 used a Startup folder shortcut instead of the Run key.
Type: files; Name: "{userstartup}\Mi Bulb.lnk"

[Run]
Filename: "{app}\MiBulb.exe"; Description: "{cm:LaunchProgram,Mi Bulb}"; Flags: nowait postinstall skipifsilent
; After an automatic update, start Mi Bulb again (as you, not as admin).
Filename: "{app}\MiBulb.exe"; Parameters: "{param:RELAUNCH|}"; Flags: nowait runasoriginaluser; Check: IsUpdate

; Your settings in %APPDATA%\mibulb are kept on uninstall, so reinstalling
; doesn't need a new sign-in.

[Code]
const
  AppMutexName = 'MiBulbSingleInstance';

function IsUpdate: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/UPDATE') = 0 then
      Result := True;
end;

{ Ask until Mi Bulb is closed. Returns False if the user gives up. }
function WaitForAppToClose(): Boolean;
var
  Waited: Integer;
begin
  Result := True;
  { An automatic update: Mi Bulb quits right after starting the installer. }
  Waited := 0;
  while IsUpdate and CheckForMutexes(AppMutexName) and (Waited < 20000) do
  begin
    Sleep(250);
    Waited := Waited + 250;
  end;
  while CheckForMutexes(AppMutexName) do
    if MsgBox('Mi Bulb is still running.' + #13#10#13#10 +
              'Right-click its tray icon and choose Quit, then click OK.',
              mbError, MB_OKCANCEL) <> IDOK then
    begin
      Result := False;
      Exit;
    end;
end;

function InitializeSetup(): Boolean;
begin
  Result := WaitForAppToClose();
end;

{ IsUpdate is always False here: uninstalling never waits, it asks. }
function InitializeUninstall(): Boolean;
begin
  Result := WaitForAppToClose();
end;
