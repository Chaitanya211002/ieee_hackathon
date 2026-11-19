@echo off
rem Shows this laptop's name and addresses on the current network, checks the service,
rem Ollama and the firewall, and prints the line the M5 needs in backend\config.yaml.
cd /d "%~dp0"
.venv\Scripts\python.exe net_info.py
pause
