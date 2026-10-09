@echo off
setlocal EnableDelayedExpansion

rem ---------------------------------------------------------------------------
rem Agent Assurance Platform - Docker control panel.
rem
rem Double-click for a menu, or pass a command:
rem   stack.bat start | stop | restart | status | logs | seed
rem   stack.bat rebuild | reset | clean | open | doctor
rem
rem Start brings services up in dependency tiers and waits for each tier to be
rem healthy before the next one, so a failure points at the service that broke
rem instead of at whatever happened to time out first.
rem ---------------------------------------------------------------------------

pushd "%~dp0" >nul

set "COMPOSE=docker compose"
set "WAITOPT=--wait --wait-timeout 420"

set "CMD=%~1"
if not "%CMD%"=="" (
  call :dispatch "%CMD%"
  set "RC=!ERRORLEVEL!"
  popd >nul
  exit /b !RC!
)

:menu
echo.
echo   ===============================================================
echo     Agent Assurance Platform - Docker control panel
echo   ===============================================================
echo.
echo     1   Start          bring the stack up in order, wait for healthy
echo     2   Stop           stop everything, keep the data
echo     3   Restart        stop then start
echo     4   Status         what is running and whether it is healthy
echo     5   Logs           follow api and worker, Ctrl+C to return
echo     6   Seed           generate the demo estate
echo.
echo     7   Rebuild        rebuild images from scratch, then start
echo     8   Reset          DELETE the databases, then start clean
echo     9   Clean          DELETE containers, volumes and local images
echo.
echo     O   Open           console and API docs in the browser
echo     D   Doctor         check Docker, secrets and .env
echo     Q   Quit
echo.
set "PICK="
set /p "PICK=  Select: "
echo.

if /i "!PICK!"=="1" call :start
if /i "!PICK!"=="2" call :stop
if /i "!PICK!"=="3" call :restart
if /i "!PICK!"=="4" call :status
if /i "!PICK!"=="5" call :logs
if /i "!PICK!"=="6" call :seed
if /i "!PICK!"=="7" call :rebuild
if /i "!PICK!"=="8" call :reset
if /i "!PICK!"=="9" call :clean
if /i "!PICK!"=="O" call :open
if /i "!PICK!"=="D" call :doctor
if /i "!PICK!"=="Q" goto :bye

echo.
echo   Press any key to return to the menu.
pause >nul
goto :menu

:bye
popd >nul
exit /b 0

rem ---------------------------------------------------------------------------
:dispatch
set "C=%~1"
if /i "%C%"=="start"   ( call :start   & exit /b !ERRORLEVEL! )
if /i "%C%"=="up"      ( call :start   & exit /b !ERRORLEVEL! )
if /i "%C%"=="stop"    ( call :stop    & exit /b !ERRORLEVEL! )
if /i "%C%"=="down"    ( call :stop    & exit /b !ERRORLEVEL! )
if /i "%C%"=="restart" ( call :restart & exit /b !ERRORLEVEL! )
if /i "%C%"=="status"  ( call :status  & exit /b !ERRORLEVEL! )
if /i "%C%"=="ps"      ( call :status  & exit /b !ERRORLEVEL! )
if /i "%C%"=="logs"    ( call :logs    & exit /b !ERRORLEVEL! )
if /i "%C%"=="seed"    ( call :seed    & exit /b !ERRORLEVEL! )
if /i "%C%"=="rebuild" ( call :rebuild & exit /b !ERRORLEVEL! )
if /i "%C%"=="reset"   ( call :reset   & exit /b !ERRORLEVEL! )
if /i "%C%"=="clean"   ( call :clean   & exit /b !ERRORLEVEL! )
if /i "%C%"=="open"    ( call :open    & exit /b !ERRORLEVEL! )
if /i "%C%"=="doctor"  ( call :doctor  & exit /b !ERRORLEVEL! )
echo Unknown command "%C%". Run stack.bat with no arguments for the menu.
exit /b 1

rem ---------------------------------------------------------------------------
rem Actions
rem ---------------------------------------------------------------------------

:start
call :ensure_engine || exit /b 1
call :ensure_files

echo.
echo   [1/7] data stores - postgres, redis, clickhouse
%COMPOSE% up -d --build %WAITOPT% postgres redis clickhouse
if errorlevel 1 ( call :diagnose postgres redis clickhouse & exit /b 1 )

echo.
echo   [2/7] database migrations
%COMPOSE% run --rm --build migrate
if errorlevel 1 ( echo   Migrations failed. Nothing downstream will start correctly. & exit /b 1 )

echo.
echo   [3/7] observe - query, ingest, worker
%COMPOSE% up -d --build %WAITOPT% observe-query observe-ingest observe-worker
if errorlevel 1 ( call :diagnose observe-query observe-ingest observe-worker & exit /b 1 )

echo.
echo   [4/7] prompt and evaluate APIs
%COMPOSE% up -d --build %WAITOPT% prompt-api evaluate-api
if errorlevel 1 ( call :diagnose prompt-api evaluate-api & exit /b 1 )

echo.
echo   [5/7] control plane - api, worker
%COMPOSE% up -d --build %WAITOPT% api worker
if errorlevel 1 ( call :diagnose api worker & exit /b 1 )

echo.
echo   [6/7] edge - gateway, collector, mcp-adapter, evaluate-worker
%COMPOSE% up -d --build %WAITOPT% gateway collector mcp-adapter evaluate-worker
if errorlevel 1 ( call :diagnose gateway collector mcp-adapter evaluate-worker & exit /b 1 )

echo.
echo   [7/7] console
%COMPOSE% up -d --build web
if errorlevel 1 ( call :diagnose web & exit /b 1 )

echo.
echo   ---------------------------------------------------------------
echo     console       http://localhost:5173
echo     API docs      http://localhost:8000/docs
echo     readiness     http://localhost:8000/readyz
echo   ---------------------------------------------------------------
echo.
echo   The stack is up. Menu option 6 seeds the demo estate.
exit /b 0

:stop
call :ensure_engine || exit /b 1
echo   Stopping the stack. Volumes are kept, so your data survives.
%COMPOSE% down --remove-orphans
exit /b %ERRORLEVEL%

:restart
call :stop || exit /b 1
call :start
exit /b %ERRORLEVEL%

:status
call :ensure_engine || exit /b 1
%COMPOSE% ps -a --format "table {{.Service}}\t{{.State}}\t{{.Status}}\t{{.Ports}}"
exit /b 0

:logs
call :ensure_engine || exit /b 1
echo   Following api and worker. Ctrl+C stops the tail, not the containers.
%COMPOSE% logs -f --tail 50 api worker
exit /b 0

:seed
call :ensure_engine || exit /b 1
%COMPOSE% run --rm seed
exit /b %ERRORLEVEL%

:rebuild
call :ensure_engine || exit /b 1
echo   Rebuilding every image without the layer cache. This takes a while.
%COMPOSE% build --no-cache
if errorlevel 1 exit /b 1
call :start
exit /b %ERRORLEVEL%

:reset
call :confirm "This DELETES the postgres, clickhouse and artifact volumes." || exit /b 0
call :ensure_engine || exit /b 1
%COMPOSE% down -v --remove-orphans
if errorlevel 1 exit /b 1
call :start
exit /b %ERRORLEVEL%

:clean
call :confirm "This DELETES containers, volumes AND the images built here." || exit /b 0
call :ensure_engine || exit /b 1
%COMPOSE% down -v --rmi local --remove-orphans
if errorlevel 1 exit /b 1
echo   Gone. The next start rebuilds everything from source.
exit /b 0

:open
start "" "http://localhost:5173"
start "" "http://localhost:8000/docs"
echo   Opened the console and the API docs.
exit /b 0

:doctor
where docker >nul 2>&1
if errorlevel 1 (
  echo   docker      NOT ON PATH - install Docker Desktop
) else (
  for /f "tokens=*" %%v in ('docker --version 2^>nul') do echo   docker      %%v
)
docker info >nul 2>&1
if errorlevel 1 (
  echo   engine      NOT RESPONDING - option 1 waits for it automatically
) else (
  for /f "tokens=*" %%v in ('docker info --format "{{.ServerVersion}}" 2^>nul') do echo   engine      running, server %%v
)
if exist ".env" ( echo   .env        present ) else ( echo   .env        MISSING - copied from .env.example on start )
if exist "secrets\signing.pem" ( echo   signing key present ) else ( echo   signing key MISSING - generated on start )
if exist "secrets\byoc\license.aap" ( echo   licence     present ) else ( echo   licence     MISSING - generated on start )
exit /b 0

rem ---------------------------------------------------------------------------
rem Helpers
rem ---------------------------------------------------------------------------

rem The engine answers the named pipe with a 500 for a minute or two after
rem Docker Desktop launches, and every compose call fails during that window.
rem Waiting here is the difference between "it is broken" and "it is starting".
:ensure_engine
where docker >nul 2>&1
if errorlevel 1 (
  echo   Docker is not on PATH. Install Docker Desktop, then reopen this window.
  exit /b 1
)
docker info >nul 2>&1
if not errorlevel 1 exit /b 0

tasklist /fi "imagename eq Docker Desktop.exe" 2>nul | find /i "Docker Desktop.exe" >nul
if errorlevel 1 (
  echo   Docker Desktop is not running. Starting it.
  if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
    start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
  ) else (
    echo   Could not find Docker Desktop.exe. Start it by hand, then retry.
    exit /b 1
  )
)

<nul set /p "=  Waiting for the Docker engine"
set /a TRIES=0
:engine_loop
docker info >nul 2>&1
if not errorlevel 1 (
  echo .
  echo   Engine ready.
  exit /b 0
)
set /a TRIES+=1
if !TRIES! GEQ 90 (
  echo .
  echo   The engine never answered. Open Docker Desktop and check for an error,
  echo   or restart it with: wsl --shutdown  then launch Docker Desktop again.
  exit /b 1
)
<nul set /p "=."
ping -n 5 127.0.0.1 >nul
goto :engine_loop

:ensure_files
if not exist ".env" (
  if exist ".env.example" (
    copy /y ".env.example" ".env" >nul
    echo   Created .env from .env.example.
  )
)
if not exist "secrets\signing.pem" (
  echo   Generating local development secrets.
  python tools\bootstrap_secrets.py
  python tools\issue_license.py --key secrets\byoc\license-key.pem --out secrets\byoc\license.aap --licensee "Local Development" --mode byoc --days 365 --max-agents 100 --modules router,observe,prompt,evaluate
)
exit /b 0

:confirm
echo.
echo   %~1
echo   This cannot be undone.
echo.
set "ANSWER="
set /p "ANSWER=  Type YES to continue: "
if /i "!ANSWER!"=="YES" exit /b 0
echo   Cancelled. Nothing was deleted.
exit /b 1

rem Show why a tier failed instead of leaving the user to hunt for it.
:diagnose
echo.
echo   That tier did not come up. Last 30 lines from each service:
for %%s in (%*) do (
  echo.
  echo   ----- %%s -----
  %COMPOSE% logs --tail 30 %%s 2>&1
)
echo.
echo   Full state:
%COMPOSE% ps -a --format "table {{.Service}}\t{{.State}}\t{{.Status}}"
exit /b 0
