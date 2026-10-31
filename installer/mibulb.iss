; Inno Setup script for the Mi Bulb installer.
; Build the app first (dist\MiBulb\ from build.ps1), then:
;   ISCC.exe /DAppVersion=0.2.0 installer\mibulb.iss

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
; Held by the running app, so setup and uninstall ask to close it first.
AppMutex=MiBulbSingleInstance
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
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Mi Bulb"; ValueData: """{app}\MiBulb.exe"" --minimized"; Flags: uninsdeletevalue; Tasks: startup

[InstallDelete]
; v0.2.0 used a Startup folder shortcut instead of the Run key.
Type: files; Name: "{userstartup}\Mi Bulb.lnk"

[Run]
Filename: "{app}\MiBulb.exe"; Description: "{cm:LaunchProgram,Mi Bulb}"; Flags: nowait postinstall skipifsilent

; Your settings in %APPDATA%\mibulb are kept on uninstall, so reinstalling
; doesn't need a new sign-in.
