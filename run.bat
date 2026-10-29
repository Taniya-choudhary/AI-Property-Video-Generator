@echo off
title AI Property Video Generator
cd /d "%~dp0"
echo Starting AI Property Video Generator...
py -3 app.py
if errorlevel 1 python app.py
pause
