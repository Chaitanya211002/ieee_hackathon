@echo off
rem Stop the WIN node if it is running in the background.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*backend.services.win.app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo WIN node stopped.
