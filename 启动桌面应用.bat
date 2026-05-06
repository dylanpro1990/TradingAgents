@echo off
setlocal
cd /d "%~dp0"
python -m desktop.app
if errorlevel 1 pause
