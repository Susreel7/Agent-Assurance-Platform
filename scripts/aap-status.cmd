@echo off
rem What is running, whether it is healthy, and the migration revision.
call "%~dp0aap.cmd" status %*
set "RC=%ERRORLEVEL%"
echo %CMDCMDLINE% | find /i "%~nx0" >nul && pause
exit /b %RC%
