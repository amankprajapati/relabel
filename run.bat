@echo off
rem Set up (once) and launch Relabel on Windows. Double-click, or:
rem   run.bat [FOLDER] [options]     open a project folder
rem   run.bat --demo                 open the bundled street-crossing example
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

if exist "%PY%" goto deps
set "SYS_PY="
for %%P in (py python python3) do (
  if not defined SYS_PY (
    %%P -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1 && set "SYS_PY=%%P"
  )
)
if not defined SYS_PY (
  echo Python 3.8 or newer is required: https://www.python.org/downloads/
  pause
  exit /b 1
)
echo Creating virtual environment in .venv ...
%SYS_PY% -m venv .venv || (pause & exit /b 1)

:deps
"%PY%" -c "import numpy, scipy" >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies ^(numpy, scipy^) ...
  "%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt || (pause & exit /b 1)
) else (
  echo Dependencies already installed, skipping download.
)

if /i "%~1"=="--demo" (
  "%PY%" -m relabel_gui_app examples
) else (
  "%PY%" -m relabel_gui_app %*
)
if errorlevel 1 pause
