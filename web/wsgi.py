"""把 Streamlit app 暴露为 ASGI（gunicorn 友好）。

Gunicorn 启动：
    gunicorn web.wsgi:app -c gunicorn.conf.py

Streamlit 默认是单进程脚本，不能直接用 gunicorn。
这个文件把 streamlit 包装成 ASGI app（用 uvicorn/hypercorn 也可以）。

实际生产推荐：
- Streamlit 单进程（开发）
- FastAPI + WebSocket（生产）
- 见 docs/09-architecture-and-scalability.md
"""

import sys
from pathlib import Path

# 把项目根加入 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def app(*args, **kwargs):
    """Gunicorn 入口。委托给 streamlit.web.server。"""
    from streamlit.web import bootstrap
    from streamlit.runtime.scriptrunner import run_script
    from streamlit import config as _config

    _config.set_option("server.port", 8501)
    _config.set_option("server.headless", True)
    _config.set_option("server.address", "0.0.0.0")
    _config.set_option("server.runOnSave", False)
    _config.set_option("server.allowRunOnSave", False)

    script_path = str(PROJECT_ROOT / "web" / "app.py")
    bootstrap.run(script_path, is_hello=False, args=[], flag_options={})


# 让 gunicorn 能直接 import 这个文件
if __name__ == "__main__":
    app()
