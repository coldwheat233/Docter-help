@echo off
REM ==============================================
REM 一键创建 medical-appointment conda 环境
REM 装到 C 盘避免 D 盘空间紧张
REM ==============================================

set CONDA_ENV_PATH=C:\Users\25197\miniconda3\envs\medical-appointment
set PYTHON_VERSION=3.11

echo [1/4] 创建 conda 环境（Python %PYTHON_VERSION%）...
call conda create -n medical-appointment python=%PYTHON_VERSION% -p %CONDA_ENV_PATH% -y

echo [2/4] 激活环境...
call conda activate medical-appointment

echo [3/4] 升级 pip...
python -m pip install --upgrade pip

echo [4/4] 安装依赖（可能需要 3-5 分钟）...
pip install -e ".[dev]"

echo.
echo ==============================================
echo 完成！使用以下命令激活：
echo     conda activate medical-appointment
echo ==============================================
pause
