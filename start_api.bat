@echo off
title AI Project Planner — API Server
color 0A

echo.
echo  ================================================================
echo   AI Project Planner — FastAPI Backend
echo   http://localhost:8000        (API)
echo   http://localhost:8000/app    (Frontend served by API)
echo   http://localhost:8000/docs   (Swagger UI)
echo  ================================================================
echo.

cd /d "%~dp0"

REM Check for .env file
if not exist ".env" (
    echo  [WARN] .env file not found!
    echo  Copy .env.example to .env and add your OPENAI_API_KEY
    echo.
)

REM Start the FastAPI server
python -m uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload

pause
