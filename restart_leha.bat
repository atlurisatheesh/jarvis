@echo off
REM Restart Leha with the fixed wake word pipeline

echo Stopping any running Leha processes...
taskkill /F /IM python.exe /FI "COMMANDLINE eq jarvis*" 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *leha*" 2>nul

echo.
echo Waiting for Leha to fully stop...
timeout /t 3 /nobreak >nul

echo.
echo Starting Leha listener...
call D:\farm-robo\farm_robot_ai\.venv\Scripts\activate.bat
python -m jarvis_ai.listen

pause
