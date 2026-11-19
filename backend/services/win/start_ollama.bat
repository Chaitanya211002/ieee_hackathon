@echo off
rem Serve Ollama to the local network so the M5 can call qwen2.5-coder:7b here.
rem Stops any Ollama that is already running (the tray app only listens on this laptop).
taskkill /IM "ollama app.exe" /F >nul 2>&1
taskkill /IM ollama.exe /F >nul 2>&1
set OLLAMA_HOST=0.0.0.0
set OLLAMA_KEEP_ALIVE=-1
ollama serve
