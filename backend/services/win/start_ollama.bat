@echo off
rem Serve Ollama to the local network so the M5 can call qwen2.5-coder:7b here.
rem Quit the Ollama tray app first (it holds port 11434), then run this.
set OLLAMA_HOST=0.0.0.0
set OLLAMA_KEEP_ALIVE=-1
ollama serve
