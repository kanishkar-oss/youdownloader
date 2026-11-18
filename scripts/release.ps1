<#
.SYNOPSIS
  Publish a new YouDownloader version to everyone who has the app installed.

.DESCRIPTION
  Bumps src/version.py, commits, creates an annotated tag vX.Y.Z (its message
  becomes the release notes) and pushes. GitHub Actions then builds the
  Windows installer and both Mac apps and publishes them as a GitHub Release;
  installed copies offer the update the next time they open.

.EXAMPLE
  .\scripts\release.ps1 5.0.1 -Notes "Fixes playlist names on Mac"

.EXAMPLE
  .\scripts\release.ps1 5.1.0      # notes default to the commit messages since the last release
#>
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Version,
    [string]$Notes = "",
    [switch]$Yes
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
# git prints UTF-8; without this Windows PowerShell decodes it with the OEM code
# page and characters like — or → in commit messages end up garbled in the notes.
[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false

function Invoke-Git {
    # Run git and stop the release if it fails.
    & git.exe @args
    if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') failed (exit $LASTEXITCODE)" }
}

if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version must look like 5.0.1 (got '$Version')" }
$tag = "v$Version"
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne 'main') { throw "Releases are cut from main (you're on '$branch')." }
if (git tag -l $tag) { throw "Tag $tag already exists." }

$current = (Select-String -Path src/version.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
if ([version]$Version -le [version]$current) {
    throw "$Version isn't newer than the current $current. Installed apps only update to a higher version."
}
Write-Host "Releasing $current -> $Version"

Invoke-Git fetch origin main --quiet
$behind = (git rev-list --count HEAD..origin/main).Trim()
if ($behind -ne '0') { throw "origin/main has $behind commit(s) you don't have. Pull first." }

$dirty = git status --porcelain
if ($dirty) {
    Write-Host "`nUncommitted changes:" -ForegroundColor Yellow
    $dirty | ForEach-Object { Write-Host "  $_" }
    if (-not $Yes) {
        $answer = Read-Host "Include these in the release commit? [y/N]"
        if ($answer -notmatch '^[yY]') { throw "Commit or stash them first." }
    }
}

if (-not $Notes) {
    $last = $null
    $tags = @(git tag -l "v*" --sort=-v:refname)
    if ($tags.Count -gt 0) { $last = $tags[0] }
    $range = if ($last) { "$last..HEAD" } else { "HEAD" }
    $Notes = (git log $range --no-merges --pretty="- %s" | Where-Object { $_ -notmatch '^- Release v' }) -join "`n"
    if ($dirty) { $Notes = (@($Notes, "- Other improvements and fixes") | Where-Object { $_ }) -join "`n" }
    if (-not $Notes) { $Notes = "- Improvements and fixes" }
}

# Rewrite the version without a BOM (Windows PowerShell's utf8 adds one).
$path = Join-Path (Get-Location) 'src/version.py'
$text = [IO.File]::ReadAllText($path) -replace '__version__ = ".*"', "__version__ = `"$Version`""
[IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false))

Write-Host "`nRelease notes:`n$Notes`n"
Invoke-Git add -A
Invoke-Git commit -m "Release $tag" --quiet
# Notes go through a file: Windows PowerShell mangles quotes in native arguments.
$notesFile = [IO.Path]::GetTempFileName()
[IO.File]::WriteAllText($notesFile, $Notes, (New-Object Text.UTF8Encoding $false))
Invoke-Git tag -a $tag --cleanup=verbatim -F $notesFile
Remove-Item $notesFile
Invoke-Git push origin main
Invoke-Git push origin $tag

$repo = (Select-String -Path src/version.py -Pattern 'GITHUB_REPO = "(.+)"').Matches[0].Groups[1].Value
Write-Host "`nPushed $tag. Builds take ~15 minutes:" -ForegroundColor Green
Write-Host "  https://github.com/$repo/actions"
Write-Host "When they finish, the release appears at https://github.com/$repo/releases/latest"
