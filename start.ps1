# Music Tracks (Windows PowerShell): starts worker + API and opens the browser.
# Thin wrapper around the cross-platform launcher (backend/app/launcher.py).
# Usage: .\start.ps1 [--port N] [--no-browser] [--dev]
# If scripts are blocked: powershell -ExecutionPolicy Bypass -File .\start.ps1
# Env: MUSIC_TRACKS_PORT, MUSIC_TRACKS_HOME, MUSIC_TRACKS_HOST, MUSIC_TRACKS_NO_BROWSER

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv nao encontrado / uv not found. Instale / install:"
    Write-Host "  winget install astral-sh.uv"
    Write-Host '  or: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    Write-Host "Depois abra um novo terminal / then open a new terminal."
    exit 1
}

$backend = Join-Path $PSScriptRoot "backend"
& uv run --project $backend python -m app.launcher @args
exit $LASTEXITCODE
