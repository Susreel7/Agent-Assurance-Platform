@echo off
rem Follow api and worker output. Ctrl+C stops following, not the containers.
call "%~dp0aap.cmd" logs %*
