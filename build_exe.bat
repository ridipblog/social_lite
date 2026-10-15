@echo off
setlocal EnableDelayedExpansion
title SocialLite - Build Standalone Executable (.exe)
cd /d "%~dp0"

echo ======================================================================
echo             SocialLite Messenger - Auto EXE Builder
echo ======================================================================
echo.

:: 1. Detect Python command (python or py)
set PYTHON_CMD=python
python --version >nul 2>&1
if not errorlevel 1 goto :PYTHON_OK

py --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=py
    goto :PYTHON_OK
)

echo [ERROR] Python is not detected in your system PATH!
echo Please install Python from https://www.python.org
echo and make sure to check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:PYTHON_OK
echo [*] Python detected:
%PYTHON_CMD% --version
echo.

:: 2. Terminate any currently running instance of SocialLite.exe to avoid file locks
taskkill /f /im SocialLite.exe >nul 2>&1

:: 3. Ensure PyInstaller is installed
%PYTHON_CMD% -c "import PyInstaller" >nul 2>&1
if not errorlevel 1 goto :PYINSTALLER_OK

echo [*] PyInstaller not found. Installing PyInstaller via pip...
%PYTHON_CMD% -m pip install pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    echo Please check your internet connection.
    pause
    exit /b 1
)

:PYINSTALLER_OK
echo [*] PyInstaller is ready.

:: 4. Ensure CustomTkinter is installed
%PYTHON_CMD% -c "import customtkinter" >nul 2>&1
if not errorlevel 1 goto :CTK_OK

echo [*] CustomTkinter not found. Installing CustomTkinter via pip...
%PYTHON_CMD% -m pip install customtkinter
if errorlevel 1 (
    echo [ERROR] Failed to install CustomTkinter.
    pause
    exit /b 1
)

:CTK_OK
echo [*] CustomTkinter is ready.

echo.
echo ======================================================================
echo [*] Compiling SocialLite into standalone .exe with PyInstaller...
echo [*] Bundling UI assets, fonts, themes, and dependencies...
echo ======================================================================
echo.

:: 5. Run PyInstaller build command
%PYTHON_CMD% -m PyInstaller --clean --noconfirm --onefile --windowed --name "SocialLite" --collect-all customtkinter main.py

if errorlevel 1 (
    echo.
    echo ======================================================================
    echo [ERROR] Build encountered an error. Please inspect the log output above.
    echo ======================================================================
    pause
    exit /b 1
)

:: 6. Verify output and create shareable ZIP package
if not exist "dist\SocialLite.exe" (
    echo.
    echo [ERROR] dist\SocialLite.exe was not found. Build may have failed.
    pause
    exit /b 1
)

echo.
echo [*] Packaging SocialLite.exe into a portable ZIP archive...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\SocialLite.exe' -DestinationPath 'dist\SocialLite.zip' -Force"

echo.
echo ======================================================================
echo  [SUCCESS] SocialLite Executable Created Successfully!
echo ======================================================================
echo.
echo  [Executable Location]:
echo    %~dp0dist\SocialLite.exe
echo.
echo  [Shareable ZIP Location]:
echo    %~dp0dist\SocialLite.zip
echo.
echo  You can send SocialLite.exe or SocialLite.zip to your friends!
echo  They do NOT need Python or any packages installed.
echo ======================================================================
echo.
echo Press any key to exit...
pause >nul
