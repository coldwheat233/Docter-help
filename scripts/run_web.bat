@echo off
REM ==============================================
REM 启动 Streamlit Web UI
REM 访问：http://localhost:8501
REM ==============================================

setlocal

if not exist .env (
    echo .env 文件不存在！先复制 .env.example
    pause
    exit /b 1
)

cd /d "%~dp0\.."

echo [启动] Streamlit Web UI
echo [访问] http://localhost:8501
echo [停止] Ctrl+C
echo.

"D:\miniconda3\envs\python311\python.exe" -m streamlit run web\app.py --server.headless false

pause
