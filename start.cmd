@echo off
rem Music Tracks (Windows cmd): starts worker + API and opens the browser.
rem Thin wrapper around the cross-platform launcher (backend\app\launcher.py).
rem Usage: start.cmd [--port N] [--no-browser] [--dev]
setlocal
where uv >nul 2>nul
if errorlevel 1 goto nouv
uv run --project "%~dp0backend" python -m app.launcher %*
exit /b %ERRORLEVEL%

:nouv
echo uv nao encontrado / uv not found. Instale / install:
echo   winget install astral-sh.uv
echo   or: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
echo Depois abra um novo terminal / then open a new terminal.
exit /b 1
