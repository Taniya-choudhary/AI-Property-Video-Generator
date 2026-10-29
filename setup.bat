@echo off
title AI Property Video Generator - Setup
cd /d "%~dp0"
echo ==========================================
echo Installing project dependencies...
echo This may take several minutes, especially Torch.
echo ==========================================
py -3 -m pip install --upgrade pip
if errorlevel 1 python -m pip install --upgrade pip
py -3 -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Setup failed. Try running setup.bat again with a stable internet connection.
  pause
  exit /b 1
)
echo.
echo Setup completed.
echo The first video may download the AI image-caption model from Hugging Face.
pause
