@echo off
rem The full pytest suite inside the api container.
call "%~dp0aap.cmd" test %*
set "RC=%ERRORLEVEL%"
echo %CMDCMDLINE% | find /i "%~nx0" >nul && pause
exit /b %RC%
