@echo off
rem End-to-end run against the live stack: register, gate, record, seal, prove.
call "%~dp0aap.cmd" smoke %*
set "RC=%ERRORLEVEL%"
echo %CMDCMDLINE% | find /i "%~nx0" >nul && pause
exit /b %RC%
