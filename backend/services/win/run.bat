@echo off
rem Start the WIN node on port 8001. Works from anywhere: it switches to the repo root.
cd /d "%~dp0..\..\.."
rem Stop the model libraries from touching the internet at all.
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
rem /run_code executes the code it is sent, so by default it answers this laptop only.
rem Put the M5 IP here (comma-separated list, or * for any device on the network):
rem set RUN_CODE_CLIENTS=127.0.0.1,192.168.8.10
backend\services\win\.venv\Scripts\python.exe -m uvicorn backend.services.win.app:app --host 0.0.0.0 --port 8001
