# Installs Deno (JS runtime that defeats YouTube download throttling) after
# verifying the official installer instead of blindly piping it into iex.
#
# Set $ExpectedHash to a known-good SHA-256 to ENFORCE a pin (recommended for a
# locked-down setup). Leave it empty to review-and-confirm interactively: the
# script downloads the installer, prints its hash and location, and asks before
# running it.

$ErrorActionPreference = 'Stop'

# Paste an uppercase, space-free SHA-256 here to enforce it (e.g. 'A1B2...').
$ExpectedHash = ''
$InstallerUrl = 'https://deno.land/install.ps1'

Write-Host '============================================'
Write-Host '  Installing Deno for Faster YouTube Downloads'
Write-Host '============================================'
Write-Host ''
Write-Host 'Deno lets yt-dlp solve YouTube''s throttling challenge, raising'
Write-Host 'download speeds from ~0.3 Mbps to tens of Mbps.'
Write-Host ''

$tmp = Join-Path $env:TEMP ("deno-install-{0}.ps1" -f ([guid]::NewGuid().ToString('N')))
try {
    Write-Host "Downloading installer from $InstallerUrl ..."
    Invoke-WebRequest -Uri $InstallerUrl -OutFile $tmp -UseBasicParsing

    $hash = (Get-FileHash -Path $tmp -Algorithm SHA256).Hash.ToUpperInvariant()
    Write-Host ''
    Write-Host 'SHA-256 of downloaded installer:'
    Write-Host "  $hash"
    Write-Host ''

    if ($ExpectedHash -ne '') {
        if ($hash -ne $ExpectedHash.ToUpperInvariant()) {
            Write-Host "ABORT: hash does not match the pinned value:" -ForegroundColor Red
            Write-Host "  expected $($ExpectedHash.ToUpperInvariant())" -ForegroundColor Red
            Write-Host "  got      $hash" -ForegroundColor Red
            exit 1
        }
        Write-Host 'Hash matches the pinned value. Proceeding.' -ForegroundColor Green
    }
    else {
        Write-Host 'No pinned hash is set. You can inspect the installer here before continuing:'
        Write-Host "  $tmp"
        Write-Host ''
        $answer = Read-Host 'Run this installer now? (y/N)'
        if ($answer -notmatch '^[Yy]') {
            Write-Host "Cancelled. The downloaded installer remains at $tmp for review."
            exit 1
        }
    }

    Write-Host ''
    Write-Host 'Running Deno installer...'
    & $tmp
}
finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}

Write-Host ''
Write-Host '============================================'
Write-Host '  Done. Restart YouDownloader to pick up Deno.'
Write-Host '  (Deno installs to %USERPROFILE%\.deno\bin)'
Write-Host '============================================'
