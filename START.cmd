@echo off
rem BCC Review: double-click or .\START.cmd in PowerShell. All the work is done by start.ps1 next to this file.
chcp 65001 >nul
title BCC Review
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 pause
exit /b %errorlevel%
