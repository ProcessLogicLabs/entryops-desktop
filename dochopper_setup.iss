; Inno Setup Script for DocHopper
; Build with: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" dochopper_setup.iss
;
; Build-time overrides (all optional):
;   /dMyAppPublisher="..."     — installer publisher field (default: "DocHopper")
;   /dTesseractShareDir="..."  — LAN share to pull Tesseract installer from
;                                (default: routes operator to GitHub download)
;   /dGitHubToken="..."        — PAT for private auth_users.json fetch

#define MyAppName "DocHopper"
#define MyAppVersion "0.1.1"
#ifndef MyAppPublisher
  #define MyAppPublisher "DocHopper"
#endif
#define MyAppExeName "DocHopper.exe"
#define SourceDir "dist\DocHopper"
#ifndef TesseractShareDir
  ; Default sentinel: when this prefix is unreachable the installer falls
  ; through to the GitHub download path. Set via /dTesseractShareDir=... to
  ; bake in your LAN install share.
  #define TesseractShareDir "\\REPLACE_ME\share\install"
#endif
; IMPORTANT: Replace this placeholder with your actual GitHub token before building
; Or pass via command line: ISCC.exe /dGitHubToken=your_token_here dochopper_setup.iss
#ifndef GitHubToken
  #define GitHubToken "YOUR_GITHUB_TOKEN_HERE"
#endif

[Setup]
; Application info
AppId={{1C13222D-9A41-4A54-96B7-2396D8570B91}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=DocHopper_Setup_{#MyAppVersion}
SetupIconFile=Dochopper\Resources\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

; Privileges - install to user's local appdata (no admin required)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Uninstall info
UninstallDisplayIcon={app}\_internal\Resources\icon.ico
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Offer to download + install Tesseract OCR (UB-Mannheim build) when missing.
; Required to OCR scanned/image-only PDFs. App falls back to no-op without it.
Name: "installtesseract"; Description: "Download and install Tesseract OCR engine (required for scanned PDFs)"; GroupDescription: "Optional components:"; Check: TesseractMissing

; (The ISF Filing tab — and its Playwright/Chrome dependency — was retired
; in v1.6.1. Moved to a separate inbox-monitoring agent; see the
; project_isf_standalone_agent memory note.)

[InstallDelete]
; Remove stale empty auth_users.json — auth is loaded from network
Type: files; Name: "{app}\auth_users.json"
Type: files; Name: "{localappdata}\DocHopper\auth_users.json"
; Clear stale bytecode cache — prevents old compiled templates from overriding updated .py files
Type: filesandordirs; Name: "{app}\_internal\templates\__pycache__"
Type: filesandordirs; Name: "{localappdata}\DocHopper\templates\__pycache__"
; Remove pre-rename supplier templates left over from v1.6.x and earlier installs.
; Inno Setup [Files] only overlays — it doesn't wipe — so without this, upgrading
; from a build made before 2026-05-01 leaves the OLD file names sitting next to
; the new ones, and auto-discovery loads both (causing duplicate Templates UI
; entries and `name` attribute collisions). Sweep the bundled dir AND the AppData
; overlay so workstations that already pulled stale copies via shared sync are
; cleaned up too. Per memory feedback_template_naming_convention.md.
Type: files; Name: "{app}\_internal\templates\aubex_sanford_consignment.py"
Type: files; Name: "{app}\_internal\templates\essen_international.py"
Type: files; Name: "{app}\_internal\templates\global_castings.py"
Type: files; Name: "{app}\_internal\templates\hebei_shinyee.py"
Type: files; Name: "{app}\_internal\templates\himcast_invoice.py"
Type: files; Name: "{app}\_internal\templates\himgiri_castings_sigma.py"
Type: files; Name: "{app}\_internal\templates\jangoh_machinery.py"
Type: files; Name: "{app}\_internal\templates\karmen_international_sigma.py"
Type: files; Name: "{app}\_internal\templates\king_multimetal.py"
Type: files; Name: "{app}\_internal\templates\masonry_supply_agarwalla.py"
Type: files; Name: "{app}\_internal\templates\orient_metacast.py"
Type: files; Name: "{app}\_internal\templates\rba_exports_sigma.py"
Type: files; Name: "{app}\_internal\templates\rba_ferro_sigma.py"
Type: files; Name: "{app}\_internal\templates\reynolds_pens_india.py"
Type: files; Name: "{app}\_internal\templates\seksaria_foundries.py"
Type: files; Name: "{app}\_internal\templates\shaanxi_fangzhi.py"
Type: files; Name: "{app}\_internal\templates\smart_shaanxi_template.py"
Type: files; Name: "{app}\_internal\templates\vitech_development_limited.py"
; Same sweep against the AppData overlay (where shared-sync downloads land).
Type: files; Name: "{localappdata}\DocHopper\templates\aubex_sanford_consignment.py"
Type: files; Name: "{localappdata}\DocHopper\templates\essen_international.py"
Type: files; Name: "{localappdata}\DocHopper\templates\global_castings.py"
Type: files; Name: "{localappdata}\DocHopper\templates\hebei_shinyee.py"
Type: files; Name: "{localappdata}\DocHopper\templates\himcast_invoice.py"
Type: files; Name: "{localappdata}\DocHopper\templates\himgiri_castings_sigma.py"
Type: files; Name: "{localappdata}\DocHopper\templates\jangoh_machinery.py"
Type: files; Name: "{localappdata}\DocHopper\templates\karmen_international_sigma.py"
Type: files; Name: "{localappdata}\DocHopper\templates\king_multimetal.py"
Type: files; Name: "{localappdata}\DocHopper\templates\masonry_supply_agarwalla.py"
Type: files; Name: "{localappdata}\DocHopper\templates\orient_metacast.py"
Type: files; Name: "{localappdata}\DocHopper\templates\rba_exports_sigma.py"
Type: files; Name: "{localappdata}\DocHopper\templates\rba_ferro_sigma.py"
Type: files; Name: "{localappdata}\DocHopper\templates\reynolds_pens_india.py"
Type: files; Name: "{localappdata}\DocHopper\templates\seksaria_foundries.py"
Type: files; Name: "{localappdata}\DocHopper\templates\shaanxi_fangzhi.py"
Type: files; Name: "{localappdata}\DocHopper\templates\smart_shaanxi_template.py"
Type: files; Name: "{localappdata}\DocHopper\templates\vitech_development_limited.py"

[Files]
; All files from the PyInstaller dist folder
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; auth_users.json is loaded from the shared network drive at runtime — not bundled
; Install config.ini in user's AppData so the app can find the network database.
; Overwrites unconditionally on every install — the canonical UNC database path
; is the same for every workstation (we all share one DB on the LAN), and the
; old `onlyifdoesntexist` flag let early installs that were saved with a
; drive-letter path stick around forever, breaking template/DB resolution for
; any user whose drive letter mapping differs. Per memory: shared DB lives at
; \\YOUR\share
Source: "config.ini"; DestDir: "{localappdata}\DocHopper"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\Resources\icon.ico"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\Resources\icon.ico"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: string; ValueName: "TARIFFMILL_GITHUB_TOKEN"; ValueData: "{#GitHubToken}"; Flags: uninsdeletevalue

[Run]
; Launch after interactive install (checkbox on final page)
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runasoriginaluser shellexec
; Launch after silent/auto-update install
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifdoesntexist runasoriginaluser shellexec; Check: WizardSilent

[Code]
const
  TesseractShareDir   = '{#TesseractShareDir}';
  TesseractPattern    = 'tesseract-ocr-w64-setup-*.exe';
  TesseractInstallerURL = 'https://github.com/UB-Mannheim/tesseract/releases/download/v5.5.0.20241111/tesseract-ocr-w64-setup-5.5.0.20241111.exe';
  TesseractWikiURL    = 'https://github.com/UB-Mannheim/tesseract/wiki';

var
  TesseractDownloadPage: TDownloadWizardPage;

function IsTesseractInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf}\Tesseract-OCR\tesseract.exe')) or
            FileExists(ExpandConstant('{commonpf32}\Tesseract-OCR\tesseract.exe')) or
            FileExists(ExpandConstant('{userpf}\Tesseract-OCR\tesseract.exe')) or
            FileExists(ExpandConstant('{localappdata}\Programs\Tesseract-OCR\tesseract.exe'));
end;

function TesseractMissing(): Boolean;
begin
  Result := not IsTesseractInstalled();
end;

{ Enumerate the LAN install share for tesseract-ocr-w64-setup-*.exe and return
  the lexically-largest filename. UB-Mannheim files embed a YYYYMMDD date in
  the filename so lexical sort == chronological sort == "latest". Returns ''
  when the share is unreachable or no installer is present. }
function FindLatestTesseractInShare(): String;
var
  FindRec: TFindRec;
  LatestName: String;
begin
  Result := '';
  LatestName := '';
  if FindFirst(TesseractShareDir + '\' + TesseractPattern, FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then
        begin
          if FindRec.Name > LatestName then
            LatestName := FindRec.Name;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
  if LatestName <> '' then
    Result := TesseractShareDir + '\' + LatestName;
end;

procedure InitializeWizard();
begin
  TesseractDownloadPage := CreateDownloadPage(
    'Tesseract OCR Engine',
    'Downloading Tesseract installer from UB-Mannheim',
    nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ResultCode: Integer;
  ShareInstaller: String;
  TmpInstaller: String;
  InstallerLaunched: Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and WizardIsTaskSelected('installtesseract') and TesseractMissing() then
  begin
    InstallerLaunched := False;
    TmpInstaller := ExpandConstant('{tmp}\tesseract-installer.exe');

    { Preferred path: copy the latest installer from the LAN install share
      and run it. Avoids GitHub download + MOTW blocking on UNC execution. }
    ShareInstaller := FindLatestTesseractInShare();
    if ShareInstaller <> '' then
    begin
      WizardForm.StatusLabel.Caption := 'Copying Tesseract installer from network share...';
      if FileCopy(ShareInstaller, TmpInstaller, False) then
      begin
        if Exec(TmpInstaller, '', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
          InstallerLaunched := True
        else
          MsgBox('Tesseract installer (from network share) could not be launched. You can install it manually later from:' + #13#10 + TesseractWikiURL,
                 mbInformation, MB_OK);
      end;
    end;

    { Fallback: GitHub download (used when share is unreachable or empty). }
    if not InstallerLaunched then
    begin
      TesseractDownloadPage.Clear;
      TesseractDownloadPage.Add(TesseractInstallerURL, 'tesseract-installer.exe', '');
      TesseractDownloadPage.Show;
      try
        try
          TesseractDownloadPage.Download;
          if not Exec(TmpInstaller, '', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
          begin
            MsgBox('Tesseract installer could not be launched. You can install it manually later from:' + #13#10 + TesseractWikiURL,
                   mbInformation, MB_OK);
          end;
        except
          if MsgBox('Tesseract download failed. The OCR feature requires Tesseract to process scanned PDFs.' + #13#10#13#10 +
                    'Open the download page in your browser? (You can install it later — DocHopper will run without it.)',
                    mbConfirmation, MB_YESNO) = IDYES then
          begin
            ShellExec('open', TesseractWikiURL, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
          end;
        end;
      finally
        TesseractDownloadPage.Hide;
      end;
    end;
  end;
end;
