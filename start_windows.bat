@echo off
cd /d %~dp0
if not exist .venv\Scripts\python.exe python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
docker compose up -d --wait
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe seed_pgvector.py
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
