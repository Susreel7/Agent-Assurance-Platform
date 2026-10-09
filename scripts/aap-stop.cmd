@echo off
rem Stop the stack. The database volume is kept.
call "%~dp0aap.cmd" stop %*
set "RC=%ERRORLEVEL%"
echo %CMDCMDLINE% | find /i "%~nx0" >nul && pause
exit /b %RC%
