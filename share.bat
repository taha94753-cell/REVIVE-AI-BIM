@echo off
rem Gives the REVIVE running on this laptop a temporary public https link (Cloudflare quick tunnel).
rem Free, no account, no card. The link works while this window and the run.bat window stay open.
setlocal
where cloudflared >nul 2>nul
if errorlevel 1 (
  echo cloudflared is not installed. Installing it with winget ^(one time^)...
  winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo Could not install cloudflared. Download it from https://github.com/cloudflare/cloudflared/releases
    pause
    exit /b 1
  )
  echo Installed. Close this window and double-click share.bat again.
  pause
  exit /b 0
)
echo Start REVIVE with run.bat first. The public link appears below, ending in .trycloudflare.com
cloudflared tunnel --url http://localhost:8000
pause
