"""Gunicorn 配置文件（生产用）。

启动：
    gunicorn -c gunicorn.conf.py web.app:app

或：
    gunicorn web.app:app --workers 4 --bind 0.0.0.0:8501
"""

# 绑端口
bind = "0.0.0.0:8501"

# Worker 数量（推荐 = CPU 核数 * 2 + 1）
import multiprocessing
workers = multiprocessing.cpu_count() * 2 + 1

# Worker 类型
worker_class = "gthread"  # 多线程 worker（适合 I/O 密集型）
threads = 4

# 超时
timeout = 120  # LLM 调用最长 60s + 缓冲
graceful_timeout = 30
keepalive = 5

# 内存限制（worker 异常时重启）
max_requests = 1000  # 每个 worker 处理 1000 请求后重启
max_requests_jitter = 100  # 随机扰动防雪崩

# 日志
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 进程名
proc_name = "medical-agent"

# 预加载（节省内存 + 启动更快，但注意：InMemorySaver 不可共享）
preload_app = False  # 关键：False 让每个 worker 独立 state

# Streamlit 兼容性（用 streamlit 的 run_on_save）
reload_extra_files = ["src/"]
reload_engines = ["inotify", "poll"]
