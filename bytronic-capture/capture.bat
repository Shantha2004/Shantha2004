@echo off
REM Capture training images from the Basler camera.
REM Stop main.py (camera-worker) first - the camera can only be opened once.
REM
REM   capture.bat                                   manual mode, SPACE to save
REM   capture.bat --label ng                        save into dataset\raw\...\ng
REM   capture.bat --mode interval --interval 2      auto-save every 2 s
REM   capture.bat --mode interval --max-images 200 --preview

setlocal
cd /d "%~dp0"

REM Use the project's virtual environment if there is one (same Python as main.py)
set "PY="
for %%V in (".venv" "venv" "..\.venv" "..\venv" "camera-worker\.venv" "camera-worker\venv") do (
    if not defined PY if exist "%%~V\Scripts\python.exe" set "PY=%%~V\Scripts\python.exe"
)
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    where py >nul 2>nul && set "PY=py"
)
if not defined PY (
    echo ERROR: Python not found. Install Python or create .venv next to capture.bat.
    goto :fail
)
echo Using Python: %PY%

REM Check the packages the capture tool needs
"%PY%" -c "import cv2, yaml, pypylon" >nul 2>nul
if errorlevel 1 (
    echo.
    echo Some packages are missing for this Python: opencv-python / PyYAML / pypylon
    choice /C YN /M "Install them now"
    if errorlevel 2 goto :fail
    "%PY%" -m pip install opencv-python PyYAML pypylon
    "%PY%" -c "import cv2, yaml, pypylon" >nul 2>nul
    if errorlevel 1 (
        echo ERROR: install failed - see messages above.
        goto :fail
    )
)

"%PY%" "capture-worker\app\capture_main.py" %*
if errorlevel 1 goto :fail
endlocal
exit /b 0

:fail
pause
endlocal
exit /b 1
