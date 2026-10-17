@echo off
title AI Project Planner — Full Stack Launcher
color 0B

echo.
echo  ================================================================
echo   AI Project Planner — Full Stack Launcher
echo  ================================================================
echo.

cd /d "%~dp0"

REM Check for .env
if not exist ".env" (
    echo  [WARN] .env not found. Copying from .env.example ...
    if exist ".env.example" (
        copy ".env.example" ".env" > nul
        echo  Please edit .env and add your OPENAI_API_KEY or ANTHROPIC_API_KEY
    )
    echo.
)

echo  Starting FastAPI backend on port 8000...
start "API Server" cmd /k "cd /d %~dp0 && python -m uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 3 /nobreak > nul

echo  Opening frontend in browser...
start http://localhost:8000/app

echo.
echo  ================================================================
echo   Frontend: http://localhost:8000/app
echo   API Docs: http://localhost:8000/docs
echo   API Base: http://localhost:8000/api
echo  ================================================================
echo.
echo  Press any key to exit this launcher (servers keep running)
pause > nul
