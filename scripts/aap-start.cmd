@echo off
rem Bring the whole stack up and seed it. Safe to run repeatedly.
rem Double-clickable: holds the window open so the result can be read.
call "%~dp0aap.cmd" start %*
set "RC=%ERRORLEVEL%"
echo %CMDCMDLINE% | find /i "%~nx0" >nul && pause
exit /b %RC%
