@echo off
setlocal EnableDelayedExpansion

rem ---------------------------------------------------------------------------
rem Windows entry point for everything in the Makefile.
rem
rem The Makefile stays the source of truth for CI, but it needs `sh`, `openssl`
rem and `make`, none of which a stock Windows machine has. The commands below
rem mirror its targets one for one so the two cannot drift apart silently.
rem
rem   scripts\aap help
rem
rem Thin wrappers next to this file (aap-start.cmd and friends) exist so the
rem common ones can be double-clicked from Explorer. They all land here.
rem ---------------------------------------------------------------------------

rem Everything runs from the repository root regardless of where this was invoked.
pushd "%~dp0.." >nul

set "COMPOSE=docker compose"
set "BYOC=docker compose -f docker-compose.yml -f docker-compose.byoc.yml"

rem This script never pauses. It has to stay safe to call from another script and
rem from CI, and any "was I double-clicked?" heuristic here also matches
rem `cmd /c aap.cmd status`, which would then hang waiting for a keypress. The
rem double-clickable wrappers next to this file own that decision instead: they
rem can tell, because Explorer starts them with no arguments at all.
set "CMD=%~1"
if "%CMD%"=="" set "CMD=help"
shift

if /i "%CMD%"=="help"        goto :help
if /i "%CMD%"=="-h"          goto :help
if /i "%CMD%"=="--help"      goto :help
if /i "%CMD%"=="doctor"      goto :doctor
if /i "%CMD%"=="bootstrap"   goto :bootstrap
if /i "%CMD%"=="start"       goto :start
if /i "%CMD%"=="up"          goto :start
if /i "%CMD%"=="stop"        goto :stop
if /i "%CMD%"=="down"        goto :stop
if /i "%CMD%"=="restart"     goto :restart
if /i "%CMD%"=="status"      goto :status
if /i "%CMD%"=="ps"          goto :status
if /i "%CMD%"=="logs"        goto :logs
if /i "%CMD%"=="reset"       goto :reset
if /i "%CMD%"=="migrate"     goto :migrate
if /i "%CMD%"=="seed"        goto :seed
if /i "%CMD%"=="psql"        goto :psql
if /i "%CMD%"=="shell"       goto :psql
if /i "%CMD%"=="smoke"       goto :smoke
if /i "%CMD%"=="test"        goto :test
if /i "%CMD%"=="lint"        goto :lint
if /i "%CMD%"=="typecheck"   goto :typecheck
if /i "%CMD%"=="client"      goto :client
if /i "%CMD%"=="contracts"   goto :contracts
if /i "%CMD%"=="check"       goto :check
if /i "%CMD%"=="web"         goto :web
if /i "%CMD%"=="open"        goto :open
if /i "%CMD%"=="byoc-up"     goto :byocup
if /i "%CMD%"=="byoc-down"   goto :byocdown

echo Unknown command "%CMD%".
echo.
goto :help

rem ---------------------------------------------------------------------------
:help
echo.
echo   Agent Assurance Platform — Windows commands
echo.
echo   Daily
echo     start        bring the whole stack up, build if needed, then seed it
echo     stop         stop the stack, keep the database
echo     restart      stop then start
echo     status       what is running, and whether it is healthy
echo     logs         follow api and worker output (Ctrl+C to stop)
echo     open         open the console and the API docs in a browser
echo.
echo   Data
echo     seed         generate the demo estate (safe to repeat)
echo     migrate      apply database migrations
echo     psql         open a psql prompt on the database
echo     reset        DESTROY the database and rebuild from scratch, then seed
echo.
echo   Quality
echo     test         the full pytest suite inside the api container
echo     lint         ruff check and format check
echo     typecheck    mypy strict on app
echo     client       regenerate OpenAPI and the typed web client
echo     contracts    prove OpenAPI is current, then build the console
echo     check        lint, typecheck, test and contract checks
echo     smoke        end-to-end run against the live stack
echo.
echo   Other
echo     doctor       check Docker, Python and the local secrets
echo     bootstrap    generate dev signing and licence keys, create .env
echo     web          run the console in Vite dev mode with hot reload
echo     byoc-up      bring the stack up in single-tenant BYOC mode
echo     byoc-down    stop the BYOC stack
echo.
goto :done

rem ---------------------------------------------------------------------------
:doctor
echo Checking the local toolchain.
echo.
where docker >nul 2>&1
if errorlevel 1 (
  echo   docker      NOT FOUND — install Docker Desktop
) else (
  for /f "tokens=*" %%v in ('docker --version 2^>nul') do echo   docker      %%v
)

docker info >nul 2>&1
if errorlevel 1 (
  echo   engine      NOT RUNNING — start Docker Desktop and wait for it to settle
) else (
  echo   engine      running
)

where python >nul 2>&1
if errorlevel 1 (
  echo   python      NOT FOUND — needed only for bootstrap and host-side tests
) else (
  for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   python      %%v
)

if exist "secrets\signing.pem" (
  echo   signing key present
) else (
  echo   signing key MISSING — run: scripts\aap bootstrap
)
if exist "secrets\byoc\license.aap" (
  echo   licence     present
) else (
  echo   licence     MISSING — run: scripts\aap bootstrap
)
if exist ".env" (
  echo   .env        present
) else (
  echo   .env        MISSING — run: scripts\aap bootstrap
)
echo.
goto :done

rem ---------------------------------------------------------------------------
:bootstrap
echo Generating local development secrets.
python tools\bootstrap_secrets.py
if errorlevel 1 goto :fail

python tools\issue_license.py --key secrets\byoc\license-key.pem --out secrets\byoc\license.aap --licensee "Local Development" --mode byoc --days 365 --max-agents 100 --modules router,observe,prompt,evaluate
if errorlevel 1 goto :fail

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo created .env from .env.example
)
echo Bootstrap complete.
goto :done

rem ---------------------------------------------------------------------------
:start
call :ensure_docker
if errorlevel 1 goto :fail

if not exist "secrets\signing.pem" call :bootstrap_quiet
if not exist ".env"                call :bootstrap_quiet

echo Building and starting the stack. First run pulls images and can take a few minutes.
%COMPOSE% up -d --build postgres api worker collector web
if errorlevel 1 goto :fail

echo.
echo Waiting for the API to report ready.
call :wait_for_api
if errorlevel 1 (
  echo.
  echo The API did not come up. Recent logs:
  %COMPOSE% logs --tail 40 api
  goto :fail
)

echo.
echo Seeding the demo estate. Repeats are safe — it will say so and stop.
%COMPOSE% run --rm seed
if errorlevel 1 (
  echo.
  echo WARNING: seeding failed. The stack is up but the console may be empty.
  echo          Run "scripts\aap logs" to see why.
)

goto :banner

rem ---------------------------------------------------------------------------
:stop
call :ensure_docker
if errorlevel 1 goto :fail
echo Stopping the stack. The database volume is kept.
%COMPOSE% down
if errorlevel 1 goto :fail
echo Stopped. "scripts\aap start" brings it back with your data intact.
goto :done

rem ---------------------------------------------------------------------------
:restart
call :ensure_docker
if errorlevel 1 goto :fail
%COMPOSE% down
goto :start

rem ---------------------------------------------------------------------------
:status
call :ensure_docker
if errorlevel 1 goto :fail
%COMPOSE% ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}"
echo.
echo Migration revision:
%COMPOSE% exec -T postgres psql -U aap -d aap -At -c "SELECT version_num FROM alembic_version" 2>nul
if errorlevel 1 echo   (database not reachable)
goto :done

rem ---------------------------------------------------------------------------
:logs
call :ensure_docker
if errorlevel 1 goto :fail
echo Following api and worker. Ctrl+C to stop — this does not stop the containers.
%COMPOSE% logs -f api worker
goto :done

rem ---------------------------------------------------------------------------
:reset
call :ensure_docker
if errorlevel 1 goto :fail
echo.
echo   This DESTROYS the database volume. Every agent, release, accreditation
echo   and evidence event in the local stack is deleted and cannot be recovered.
echo.
set "CONFIRM="
set /p "CONFIRM=Type RESET to continue: "
if /i not "!CONFIRM!"=="RESET" (
  echo Cancelled. Nothing was deleted.
  goto :done
)
%COMPOSE% down -v
if errorlevel 1 goto :fail
goto :start

rem ---------------------------------------------------------------------------
:migrate
call :ensure_docker
if errorlevel 1 goto :fail
%COMPOSE% run --rm migrate
if errorlevel 1 goto :fail
echo Migrations applied.
goto :done

rem ---------------------------------------------------------------------------
:seed
call :ensure_docker
if errorlevel 1 goto :fail
%COMPOSE% run --rm seed %1 %2 %3 %4 %5 %6 %7 %8 %9
if errorlevel 1 goto :fail
goto :done

rem ---------------------------------------------------------------------------
:psql
call :ensure_docker
if errorlevel 1 goto :fail
echo Connecting. \q to quit, \dt to list tables.
%COMPOSE% exec postgres psql -U aap -d aap
goto :done

rem ---------------------------------------------------------------------------
:smoke
call :ensure_docker
if errorlevel 1 goto :fail
%COMPOSE% run --rm api python -m tests.smoke --base-url http://api:8000
if errorlevel 1 goto :fail
goto :done

rem ---------------------------------------------------------------------------
:test
call :ensure_docker
if errorlevel 1 goto :fail
%COMPOSE% run --rm api pytest -q
if errorlevel 1 goto :fail
goto :done

rem ---------------------------------------------------------------------------
:lint
call :ensure_docker
if errorlevel 1 goto :fail
%COMPOSE% run --rm api sh -c "ruff check . && ruff format --check ."
if errorlevel 1 goto :fail
goto :done

rem ---------------------------------------------------------------------------
:typecheck
call :ensure_docker
if errorlevel 1 goto :fail
%COMPOSE% run --rm api mypy app
if errorlevel 1 goto :fail
goto :done

rem ---------------------------------------------------------------------------
:client
call :ensure_docker
if errorlevel 1 goto :fail
%COMPOSE% run --rm api python -m app.export_openapi > services\web\openapi.json
if errorlevel 1 goto :fail
%COMPOSE% run --rm --no-deps web npm run client
if errorlevel 1 goto :fail
echo OpenAPI snapshot and generated client refreshed.
goto :done

rem ---------------------------------------------------------------------------
:contracts
call :ensure_docker
if errorlevel 1 goto :fail
%COMPOSE% run --rm -v "./services/web:/contracts:ro" api python -m app.export_openapi --check /contracts/openapi.json
if errorlevel 1 goto :fail
%COMPOSE% run --rm --no-deps web npm run build
if errorlevel 1 goto :fail
goto :done

rem ---------------------------------------------------------------------------
:check
call :lint
if errorlevel 1 goto :fail
call :typecheck
if errorlevel 1 goto :fail
call :test
if errorlevel 1 goto :fail
call :contracts
if errorlevel 1 goto :fail
echo.
echo All checks passed.
goto :done

rem ---------------------------------------------------------------------------
:web
where npm >nul 2>&1
if errorlevel 1 (
  echo npm not found. Install Node.js, or use the containerised console at
  echo http://localhost:5173 after "scripts\aap start".
  goto :fail
)
pushd "services\web" >nul
if not exist "node_modules" (
  echo Installing frontend dependencies. This happens once.
  call npm install
  if errorlevel 1 (
    popd >nul
    goto :fail
  )
)
echo.
echo Starting Vite with hot reload. It proxies the API at http://localhost:8000.
echo Ctrl+C to stop.
call npm run dev
popd >nul
goto :done

rem ---------------------------------------------------------------------------
:open
start "" "http://localhost:5173"
start "" "http://localhost:8000/docs"
echo Opened the console and the API docs.
goto :done

rem ---------------------------------------------------------------------------
:byocup
call :ensure_docker
if errorlevel 1 goto :fail
if not exist "secrets\byoc\license.aap" call :bootstrap_quiet
%BYOC% up -d --build
if errorlevel 1 goto :fail
echo BYOC mode: single-tenant, offline licence, S3 object store via MinIO.
echo   minio console  http://localhost:9001
goto :done

:byocdown
call :ensure_docker
if errorlevel 1 goto :fail
%BYOC% down
goto :done

rem ---------------------------------------------------------------------------
rem Helpers
rem ---------------------------------------------------------------------------

:ensure_docker
where docker >nul 2>&1
if errorlevel 1 (
  echo Docker was not found on PATH. Install Docker Desktop and reopen this window.
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo The Docker engine is not responding. Start Docker Desktop, wait for the
  echo whale icon to stop animating, then try again.
  exit /b 1
)
exit /b 0

:bootstrap_quiet
python tools\bootstrap_secrets.py >nul 2>&1
python tools\issue_license.py --key secrets\byoc\license-key.pem --out secrets\byoc\license.aap --licensee "Local Development" --mode byoc --days 365 --max-agents 100 --modules router,observe,prompt,evaluate >nul 2>&1
if not exist ".env" copy /y ".env.example" ".env" >nul 2>&1
exit /b 0

:wait_for_api
rem Poll readiness rather than sleeping a fixed time: the first build is slow and
rem a later one is nearly instant, and a fixed sleep is wrong for both.
set /a ATTEMPT=0
:wait_loop
set /a ATTEMPT+=1
%COMPOSE% exec -T api python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3).status==200 else 1)" >nul 2>&1
if not errorlevel 1 (
  echo   ready after %ATTEMPT% attempt^(s^).
  exit /b 0
)
if %ATTEMPT% GEQ 30 exit /b 1
<nul set /p "=."
rem ~2s per attempt without needing a sleep binary.
ping -n 3 127.0.0.1 >nul
goto :wait_loop

:banner
echo.
echo   ---------------------------------------------------------------
echo     console       http://localhost:5173
echo     API docs      http://localhost:8000/docs
echo     readiness     http://localhost:8000/readyz
echo   ---------------------------------------------------------------
echo.
echo   The console needs an organisation id. The seed prints one, and
echo   "scripts\aap psql" then "SELECT id, slug FROM organizations;"
echo   will show it again.
echo.
goto :done

:fail
echo.
echo Command failed.
popd >nul
endlocal
exit /b 1

:done
popd >nul
endlocal
exit /b 0
