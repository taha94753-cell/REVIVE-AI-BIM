@echo off
REM Start REVIVE. Sets itself up on first use and repairs a broken environment.
setlocal EnableExtensions
cd /d "%~dp0"
title REVIVE server - keep this window open
set "VPY=%~dp0.venv\Scripts\python.exe"

REM ---- no environment yet, or one whose Python was uninstalled: run setup
if not exist "%VPY%" goto :setup
"%VPY%" -c "import sys" >nul 2>&1
if errorlevel 1 goto :setup
goto :check

:setup
echo  First run (or the Python environment is broken): running setup now.
call "%~dp0setup.bat" nopause
if errorlevel 1 goto :fail
if not exist "%VPY%" goto :fail

:check
"%VPY%" -c "import fastapi, uvicorn, xgboost, shap, ifcopenshell, pulp, segno, multipart" >nul 2>&1
if not errorlevel 1 goto :start
echo  Some packages are missing or damaged. Repairing...
"%VPY%" -m pip install -r requirements-lock.txt
if not errorlevel 1 goto :start
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

:start
echo.
echo  Starting REVIVE. The browser opens when the server is ready (10-30 s the first time).
echo.
"%VPY%" -m revive serve --open %*
echo.
echo  REVIVE has stopped. If that was unexpected, the reason is in the lines above.
echo  For a full check run:  .venv\Scripts\python.exe -m revive doctor
pause
exit /b 0

:fail
echo.
echo  REVIVE could not start. Run setup.bat and read the first error it shows.
pause
exit /b 1
