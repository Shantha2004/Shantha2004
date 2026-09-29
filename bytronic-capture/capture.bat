@echo off
REM Capture training images from the Basler camera.
REM Stop main.py (camera-worker) first - the camera can only be opened once.
REM
REM   capture.bat                                   manual mode, SPACE to save
REM   capture.bat --label ng                        save into dataset\raw\<date>\ng
REM   capture.bat --mode interval --interval 2      auto-save every 2 s
REM   capture.bat --mode interval --max-images 200 --preview

setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

"%PY%" "capture-worker\app\capture_main.py" %*

if errorlevel 1 pause
endlocal
