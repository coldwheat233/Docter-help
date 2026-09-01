@echo off
REM ==============================================
REM 一键运行 3 个 demo
REM ==============================================

setlocal

if not exist .env (
    echo .env 文件不存在！先运行 scripts\setup_env.bat 和 seed_db.bat
    pause
    exit /b 1
)

set CHOICE=
echo ==============================================
echo  选择要运行的 demo
echo ==============================================
echo  1. Supervisor 基础 demo（验证 langgraph-supervisor 包）
echo  2. Swarm 基础 demo（验证 langgraph-swarm 包）
echo  3. 医疗预约场景 demo（端到端）
echo  0. 全部依次跑
echo ==============================================
set /p CHOICE="请输入 [0-3]："

if "%CHOICE%"=="1" python demos\01_voice_supervisor_demo.py
if "%CHOICE%"=="2" python demos\02_voice_swarm_demo.py
if "%CHOICE%"=="3" python demos\03_medical_appointment_demo.py
if "%CHOICE%"=="0" (
    echo --- Demo 01 ---
    python demos\01_voice_supervisor_demo.py
    echo --- Demo 02 ---
    python demos\02_voice_swarm_demo.py
    echo --- Demo 03 ---
    python demos\03_medical_appointment_demo.py
)

pause
