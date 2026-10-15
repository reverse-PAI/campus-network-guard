@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY (
  where py >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY goto nopy
%PY% "%~dp0app.py"
goto done

:nopy
echo Python was not found, so the app cannot be started this way.
echo Install Python 3 (tick "Add Python to PATH" during setup),
echo or run the packaged .exe instead (see README).
:done
echo.
echo The program has exited. Press any key to close this window.
pause >nul
