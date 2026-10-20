@echo off
title Rust No-Recoil
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python nije nadjen. Instaliraj Python 3.10+ i pokreni opet.
  pause & exit /b
)
python -m pip install --upgrade pip >nul 2>nul
python avast.py
pause