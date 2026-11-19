@echo off
rem One-time setup for the WIN node. Needs internet and about 7 GB of free disk.
rem Everything is installed inside this folder (.venv, sandbox_venv, models).
cd /d "%~dp0"

if not exist .venv (
    echo Creating service environment...
    python -m venv .venv || goto :err
)
set PY=.venv\Scripts\python.exe
echo Installing service packages (no pip cache, to save disk)...
%PY% -m pip install --no-cache-dir --upgrade pip || goto :err
%PY% -m pip install --no-cache-dir torch || goto :err
%PY% -m pip install --no-cache-dir -r requirements-win.txt || goto :err

if not exist sandbox_venv (
    echo Creating code sandbox environment...
    python -m venv sandbox_venv || goto :err
)
sandbox_venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements-sandbox.txt || goto :err
rem Install the network block for sandboxed code (see sandbox_guard.py).
copy /y sandbox_guard.py sandbox_venv\Lib\site-packages\benchlog_sandbox_guard.py >nul || goto :err
echo import benchlog_sandbox_guard> sandbox_venv\Lib\site-packages\benchlog_sandbox.pth
rem Build the matplotlib font cache now so the first sandbox run is not slow.
set MPLCONFIGDIR=%~dp0sandbox_venv\.mplconfig
set MPLBACKEND=Agg
sandbox_venv\Scripts\python.exe -c "import matplotlib.pyplot" || goto :err

echo Downloading models...
%PY% download_models.py || goto :err

echo.
echo Setup complete. Start the node with run.bat
exit /b 0

:err
echo.
echo Setup FAILED. Scroll up for the first error.
exit /b 1
