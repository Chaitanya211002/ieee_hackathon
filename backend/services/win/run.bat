@echo off
rem Start the WIN node on port 8001. Works from anywhere: it switches to the repo root.
cd /d "%~dp0..\..\.."
rem Stop the model libraries from touching the internet at all.
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
rem /run_code executes the code it is sent. "lan" lets devices on the same local network
rem (same /24, private addresses only) call it, so nothing here changes when the laptops
rem move to another network. Only use it on our own router or hotspot. To lock it to one
rem machine, put the M5 IP here instead, e.g. set RUN_CODE_CLIENTS=192.168.8.10
set RUN_CODE_CLIENTS=lan
backend\services\win\.venv\Scripts\python.exe -m uvicorn backend.services.win.app:app --host 0.0.0.0 --port 8001
