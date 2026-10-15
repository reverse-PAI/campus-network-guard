@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
where pythonw >nul 2>nul
if not errorlevel 1 set "PY=pythonw"
if not defined PY (
  where pyw >nul 2>nul
  if not errorlevel 1 set "PY=pyw -3"
)
if not defined PY goto nopy
start "" %PY% "%~dp0app.py"
exit /b

:nopy
echo Python was not found, so the app cannot be started this way.
echo Install Python 3 (tick "Add Python to PATH" during setup),
echo or run the packaged .exe instead (see README).
pause
