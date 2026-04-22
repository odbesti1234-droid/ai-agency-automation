@echo off
title AI Agency Watcher - Canva Auto Designer
cd /d "C:\Users\Administrator\Documents\oido92\ai-agency-automation"
set CLAUDE_CMD=C:\Users\Administrator\AppData\Roaming\npm\claude.cmd
echo [%date% %time%] Watcher 시작...
python watch_approved.py
pause
