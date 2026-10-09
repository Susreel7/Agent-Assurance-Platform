@echo off
rem Run the console in Vite dev mode with hot reload, against the containerised API.
call "%~dp0aap.cmd" web %*
set "RC=%ERRORLEVEL%"
echo %CMDCMDLINE% | find /i "%~nx0" >nul && pause
exit /b %RC%
