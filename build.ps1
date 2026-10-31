# Builds Mi Bulb for Windows:
#   dist\MiBulb-Portable.exe   single file, runs from anywhere
#   dist\MiBulb\               folder used by the installer
#   dist\MiBulb-Setup.exe      installer (only if Inno Setup 6 is installed)
#
# The release workflow runs this same script with -RequireInstaller.
# Exit codes are checked by hand: pip prints notices to stderr, which
# $ErrorActionPreference = "Stop" would treat as a failure in Windows PowerShell.
param([switch]$RequireInstaller)

# Same PyInstaller version for local and release builds
python -m pip install -r requirements.txt pyinstaller==6.11.1
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$version = python -c "import mibulb; print(mibulb.__version__)"
$common = @("--noconfirm", "--windowed", "--icon", "assets\icon.ico", "run_gui.py")

python -m PyInstaller --onefile --name MiBulb-Portable @common
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (portable) failed" }

# A folder build starts faster than the single file, which unpacks itself on every launch.
python -m PyInstaller --onedir --name MiBulb @common
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (installer files) failed" }

$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($iscc) {
    & $iscc "/DAppVersion=$version" installer\mibulb.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
    Write-Host "Built dist\MiBulb-Portable.exe and dist\MiBulb-Setup.exe ($version)"
} elseif ($RequireInstaller) {
    throw "Inno Setup 6 not found"
} else {
    Write-Host "Built dist\MiBulb-Portable.exe ($version). Install Inno Setup 6 to also build the installer."
}
