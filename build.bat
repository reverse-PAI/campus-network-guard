@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "APPNAME="
set "PY="

echo ==========================================
echo   CampusGuard - single file exe builder
echo ==========================================

where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 -c "import sys" >nul 2>nul
if errorlevel 1 goto try_python
set "PY=py -3"
goto got_py

:try_python
where python >nul 2>nul
if errorlevel 1 goto try_python3
set "PY=python"
goto got_py

:try_python3
where python3 >nul 2>nul
if errorlevel 1 goto no_py
set "PY=python3"

:got_py
%PY% -c "import sys;print('  [info] python',sys.version.split()[0])"
if errorlevel 1 goto no_py

%PY% -c "import ctypes,sys;sys.path.insert(0,'.');import winutil;cp=ctypes.windll.kernel32.GetConsoleOutputCP() or 936;open('_appname.cmd','wb').write(('set '+chr(34)+'APPNAME='+winutil.APP_NAME+chr(34)).encode('cp'+str(cp)))"
if errorlevel 1 goto no_name
call _appname.cmd
del /q _appname.cmd >nul 2>nul
if not defined APPNAME goto no_name
echo   [info] app name: %APPNAME%

%PY% -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
  echo   [info] installing pyinstaller ...
  %PY% -m pip install --upgrade pyinstaller
  if errorlevel 1 goto no_pyi
)

echo   [info] cleaning ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
del /q *.spec >nul 2>nul

echo   [info] running PyInstaller ...
%PY% -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name "%APPNAME%" ^
  --icon app.ico ^
  --optimize 2 ^
  --exclude-module tkinter --exclude-module unittest --exclude-module pydoc ^
  --exclude-module doctest --exclude-module test --exclude-module sqlite3 ^
  --exclude-module asyncio --exclude-module multiprocessing --exclude-module xml ^
  --exclude-module pdb --exclude-module lib2to3 --exclude-module setuptools ^
  --exclude-module pip --exclude-module ssl --exclude-module _hashlib ^
  --hidden-import _md5 --hidden-import _sha1 ^
  --add-data "ui.html;." ^
  --add-data "app.ico;." ^
  app.py
if errorlevel 1 goto build_fail

if exist build rmdir /s /q build
del /q *.spec >nul 2>nul

echo.
echo   [done] %~dp0dist\%APPNAME%.exe
endlocal
exit /b 0

:no_py
echo   [error] Python not found. Install Python 3.10+ and add it to PATH.
endlocal
exit /b 1

:no_name
echo   [error] cannot read APP_NAME from winutil.py.
endlocal
exit /b 1

:no_pyi
echo   [error] PyInstaller is not available. Try: python -m pip install pyinstaller
endlocal
exit /b 1

:build_fail
echo   [error] PyInstaller failed, see the messages above.
endlocal
exit /b 1
