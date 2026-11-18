# Creates "YouDownloader" shortcuts on the Desktop and in the Start Menu that
# open the app with no console window (via the project's .venv pythonw.exe).
# Safe to re-run: it just overwrites the two shortcuts.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    Write-Host "No .venv found. Set it up first:"
    Write-Host "  py -3 -m venv .venv"
    Write-Host "  .venv\Scripts\python -m pip install -r requirements.txt"
    exit 1
}
$icon = Join-Path $root 'assets\youdownloader.ico'
$launcher = Join-Path $root 'YouDownloader.pyw'

$shell = New-Object -ComObject WScript.Shell
$targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'YouDownloader.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'YouDownloader.lnk')
)
foreach ($lnkPath in $targets) {
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = '"' + $launcher + '"'
    $lnk.WorkingDirectory = $root
    $lnk.Description = 'YouDownloader - YouTube video and audio downloader'
    if (Test-Path $icon) { $lnk.IconLocation = "$icon,0" }
    $lnk.Save()
    Write-Host "Created $lnkPath"
}
