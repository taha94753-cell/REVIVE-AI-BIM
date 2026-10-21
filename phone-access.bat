@echo off
REM Let phones on the same Wi-Fi/hotspot open the REVIVE site-update page.
REM Adds (or with "remove", deletes) one inbound Windows Firewall rule for TCP port 8000.
setlocal EnableExtensions
set "PORT=8000"
if not "%~2"=="" set "PORT=%~2"

net session >nul 2>&1
if errorlevel 1 (
  echo Asking Windows for administrator rights...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%~1 %PORT%' -Verb RunAs"
  exit /b 0
)

netsh advfirewall firewall delete rule name="REVIVE phone link (TCP %PORT%)" >nul 2>&1
if /i "%~1"=="remove" (
  echo Firewall rule removed. Phones can no longer reach REVIVE on port %PORT%.
  pause
  exit /b 0
)
netsh advfirewall firewall add rule name="REVIVE phone link (TCP %PORT%)" dir=in action=allow protocol=TCP localport=%PORT% profile=private,public
if errorlevel 1 (
  echo Could not add the firewall rule.
  pause
  exit /b 1
)
echo.
echo Done. Phones on the same Wi-Fi or hotspot can now open the REVIVE link on port %PORT%.
echo This also applies on public networks so a phone hotspot works; anyone on the same
echo network could open the app while it runs. Remove the rule after the demo with:
echo     phone-access.bat remove
pause
