@echo off
REM REVIVE first-time setup for Windows. Safe to run again: it repairs a broken or outdated setup.
setlocal EnableExtensions
cd /d "%~dp0"
title REVIVE setup
echo.
echo  REVIVE setup
echo  ------------

REM Files that came from a downloaded zip carry a "downloaded from the internet" mark, which makes
REM Windows warn "The publisher could not be verified" each time. Clear it once for this folder.
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%~dp0.' -Recurse -File | Unblock-File" >nul 2>&1

set "WINGET_TRIED="
:find
REM ---- find Python 3.11-3.14: the py launcher first, then PATH, then the usual install folders
set "PY="
for %%V in (3.12 3.13 3.14 3.11) do if not defined PY call :try py -%%V
if not defined PY call :try python
if not defined PY call :try python3
for %%D in (312 313 314 311) do if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%D\python.exe" call :try "%LOCALAPPDATA%\Programs\Python\Python%%D\python.exe"
for %%D in (312 313 314 311) do if not defined PY if exist "%ProgramFiles%\Python%%D\python.exe" call :try "%ProgramFiles%\Python%%D\python.exe"
if defined PY goto :found

echo.
echo  No usable Python was found. REVIVE needs Python 3.12 (3.13, 3.14 or 3.11 also work).
echo.
echo  What this computer has:
py --list 2>nul
where python 2>nul
echo.
if defined WINGET_TRIED goto :manual
winget --version >nul 2>&1
if errorlevel 1 goto :manual
choice /c YN /m "  Install Python 3.12 now? It is free, about 30 MB, and needs no administrator rights"
if errorlevel 2 goto :manual
set "WINGET_TRIED=1"
winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
goto :find

:manual
echo  Install Python yourself, then run setup.bat again:
echo  1. Download Python 3.12 from https://www.python.org/downloads/windows/
echo     Choose "Windows installer 64-bit" under the newest Python 3.12 release.
echo  2. On the first installer screen tick "Add python.exe to PATH", then Install Now.
echo  3. If typing python opens the Microsoft Store, turn off the two python entries in
echo     Settings ^> Apps ^> Advanced app settings ^> App execution aliases.
goto :fail

:found
echo  Using: %PY%
%PY% --version

REM ---- a .venv built with a Python that has since been removed or replaced is rebuilt
if not exist ".venv\Scripts\python.exe" goto :makevenv
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,14) else 1)" >nul 2>&1
if not errorlevel 1 goto :install
echo  The existing .venv is broken or uses an unsupported Python. Rebuilding it.
rmdir /s /q ".venv"

:makevenv
echo  Creating the virtual environment in .venv
%PY% -m venv .venv
if errorlevel 1 goto :fail

:install
set "VPY=%~dp0.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip
REM The tested versions first. On Python 3.11 some need 3.12, so compatible versions are used instead.
"%VPY%" -m pip install -r requirements-lock.txt
if not errorlevel 1 goto :ready
echo.
echo  The tested versions are not available for this Python; installing compatible versions instead.
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

:ready
"%VPY%" -m revive setup
if errorlevel 1 goto :fail
"%VPY%" -m revive doctor

echo.
echo  Setup complete. Double-click run.bat to start REVIVE.
if /i not "%~1"=="nopause" pause
exit /b 0

:fail
echo.
echo  Setup did not finish. Read the messages above; the first error is usually the cause.
if /i not "%~1"=="nopause" pause
exit /b 1

REM ---- :try <command...>  sets PY when the command is a Python between 3.11 and 3.14
:try
%* -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,14) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set "PY=%*"
exit /b 0
