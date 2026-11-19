@echo off
rem Run ONCE as Administrator (right-click, "Run as administrator").
rem Opens the WIN service (8001) and Ollama (11434) to the SAME local network only.
for %%P in (8001 11434) do (
    netsh advfirewall firewall delete rule name="BenchLog WIN %%P" >nul 2>&1
    netsh advfirewall firewall add rule name="BenchLog WIN %%P" dir=in action=allow protocol=TCP localport=%%P remoteip=localsubnet || goto :err
)
echo Ports 8001 and 11434 are open to the local network.
pause
exit /b 0
:err
echo Failed. Did you run this as Administrator?
pause
exit /b 1
