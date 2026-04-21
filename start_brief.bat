@echo off
title AI Agency - Brief Collector
cd /d "C:\Users\Administrator\Documents\oido92\ai-agency-automation"
echo [%date% %time%] 주간 브리프 수집 요청 발송 시작...
python -m src.agents.brief_collector %*
pause
