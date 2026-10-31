# Builds a standalone dist\MiBulb.exe that runs without Python installed.
# Exit codes are checked by hand: pip prints notices to stderr, which
# $ErrorActionPreference = "Stop" would treat as a failure in Windows PowerShell.

# Same PyInstaller version as .github/workflows/release.yml
python -m pip install -r requirements.txt pyinstaller==6.11.1
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

python -m PyInstaller --noconfirm --onefile --windowed --icon assets\icon.ico --name MiBulb run_gui.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "Built dist\MiBulb.exe"
