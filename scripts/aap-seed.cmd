@echo off
rem Generate the demo estate. Refuses to double-seed unless given --force.
call "%~dp0aap.cmd" seed %*
set "RC=%ERRORLEVEL%"
echo %CMDCMDLINE% | find /i "%~nx0" >nul && pause
exit /b %RC%
