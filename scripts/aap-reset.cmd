@echo off
rem DESTROYS the database volume, rebuilds and reseeds. Asks for confirmation.
call "%~dp0aap.cmd" reset %*
set "RC=%ERRORLEVEL%"
echo %CMDCMDLINE% | find /i "%~nx0" >nul && pause
exit /b %RC%
