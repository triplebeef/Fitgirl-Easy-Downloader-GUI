@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo  Building FuckingFast GUI Downloader
echo ========================================
echo.

set "SCRIPT=main_GUI.py"
set "ICON=fg-icon.ico"
set "EXE=%~dp0dist\FuckingFast-GUI.exe"

if not exist "%SCRIPT%" (
    echo ERROR: "%SCRIPT%" was not found in:
    echo   %CD%
    goto :error
)

if not exist "%ICON%" (
    echo ERROR: "%ICON%" was not found.
    goto :error
)

if not exist "requirements.txt" (
    echo ERROR: requirements.txt was not found.
    goto :error
)

echo [1/3] Updating pip...
py -m pip install --upgrade pip
if errorlevel 1 goto :error

echo.
echo [2/3] Installing requirements...
py -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo [3/3] Building EXE...
py -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "FuckingFast-GUI" ^
  --collect-all nodriver ^
  --collect-all customtkinter ^
  --icon "%ICON%" ^
  --add-data "%ICON%;." ^
  "%SCRIPT%"

if errorlevel 1 goto :error

if not exist "%EXE%" (
    echo ERROR: Build finished but the EXE was not found:
    echo   %EXE%
    goto :error
)

echo.
echo ========================================
echo  BUILD COMPLETE
echo ========================================
echo   %EXE%
echo.
echo Runtime global icon location:
echo   %%APPDATA%%\FuckingFast-GUI\fg-icon.ico
echo.
pause
exit /b 0

:error
echo.
echo ========================================
echo  BUILD FAILED
echo ========================================
echo Check the error above.
echo.
pause
exit /b 1
