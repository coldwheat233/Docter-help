@echo off
REM ==============================================
REM 创建 .env 文件（如果不存在）并运行 seed
REM ==============================================

setlocal

if not exist .env (
    echo .env 文件不存在，从 .env.example 复制...
    copy .env.example .env
    echo.
    echo ⚠️  请编辑 .env，填入你的 DEEPSEEK_API_KEY 和 LANGSMITH_API_KEY
    echo 然后重新运行本脚本
    pause
    exit /b 1
)

echo [1/2] 初始化数据库 schema...
python -m medical_agent.db.database --init

echo [2/2] 生成排班模拟数据...
python scripts/seed_db.py

echo.
echo ==============================================
echo 完成！SQLite 数据库：data/medical.db
echo ==============================================
pause
