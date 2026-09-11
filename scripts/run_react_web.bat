@echo off
REM 一键启动 React 前端 + FastAPI 后端（各开一个窗口）
REM 双击运行；关窗口即停服务

set "ROOT=D:\PY_PROJ\NEW\medical-appointment-agent"
set "PY=D:\miniconda3\envs\python311\python.exe"

start "medical-api" cmd /k "cd /d %ROOT% && set PYTHONPATH=%ROOT%\src&& set PYTHONUTF8=1&& set MEDICAL_ADMIN_TOKEN=dev-demo-token&& %PY% -m uvicorn web.api:app --host 127.0.0.1 --port 8000"
timeout /t 2 >nul
start "medical-web" cmd /k "cd /d %ROOT%\web-react && npm run dev"
timeout /t 3 >nul
start http://localhost:5173
