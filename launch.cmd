@echo off
cd /d C:\Users\jphit\.codex\Projects\Auto-PPT
start "" .venv\Scripts\python.exe -m pptx_gen.cli serve --host 127.0.0.1 --port 8000 --no-reload
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8000
