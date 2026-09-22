@echo off
title Auto-Sync to GitHub + Vercel
cd /d "%~dp0"
echo Starting auto-sync watcher...
echo This window must stay open for auto-deploy.
echo ==========================================
powershell -ExecutionPolicy Bypass -File "%~dp0auto-sync.ps1"
