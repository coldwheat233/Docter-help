# 部署文档

## 三种部署方式（按规模）

### 1. 单机开发（当前）

```bash
# 直接 streamlit run
streamlit run web/app.py --server.port 8501
```

**容量**：~10 RPS，~100 并发用户

**适用**：开发/演示/小团队内部用

### 2. 单机生产（gunicorn + nginx）

```bash
# 后端
gunicorn -c gunicorn.conf.py web.wsgi:app

# 前端（独立 nginx 配置）
cp nginx.conf.example /etc/nginx/sites-available/medical-agent
ln -s /etc/nginx/sites-available/medical-agent /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

**容量**：~100 RPS，~1000 并发用户

**适用**：单医院部署

### 3. K8s 弹性（待实现）

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: medical-agent
spec:
  replicas: 3
  selector:
    matchLabels:
      app: medical-agent
  template:
    metadata:
      labels:
        app: medical-agent
    spec:
      containers:
      - name: agent
        image: medical-agent:latest
        ports:
        - containerPort: 8501
        env:
        - name: CHECKPOINT_URL
          value: "postgresql://user:pass@postgres:5432/medical"
        - name: REDIS_URL
          value: "redis://redis:6379/0"
        - name: DEEPSEEK_API_KEY
          valueFrom:
            secretKeyRef:
              name: llm-secrets
              key: deepseek-key
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8501
          initialDelaySeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8501
          initialDelaySeconds: 5
```

**容量**：~10000 RPS，~100K 并发用户

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 必填 | DeepSeek LLM key |
| `OPENAI_API_KEY` | 空 | OpenAI 备用 key（fallback） |
| `MOCK_LLM` | false | true 走 mock（不调真实 API） |
| `LANGSMITH_TRACING` | false | 启用 LangSmith 观测 |
| `LANGSMITH_API_KEY` | 空 | LangSmith key |
| `LANGSMITH_PROJECT` | medical-agent | LangSmith 项目名 |
| `REDIS_URL` | 空 | 启用 Redis 缓存（多实例） |
| `CHECKPOINT_URL` | 空 | Postgres 检查点（生产） |
| `CHECKPOINT_PATH` | 空 | SQLite 检查点（轻量持久） |
| `DB_PATH` | data/medical.db | SQLite 数据库路径 |

## 端口

| 端口 | 服务 | 备注 |
|---|---|---|
| 8501 | Streamlit / Gunicorn | 主入口 |
| 80/443 | Nginx | 外部访问 |

## 健康检查

```bash
curl http://localhost:8501/_stcore/health
# 返回 "ok"
```

## 监控

- **指标**：Prometheus + Grafana（待集成）
- **日志**：JSON 格式 + ELK（待集成）
- **追踪**：LangSmith（已配置位）

## 备份

- SQLite/Postgres 每日全量备份
- embeddings.npy 自动重建（丢了重新 build）
- 配置文件（.env, gunicorn.conf.py）纳入版本控制

## 升级流程

1. 拉新代码：`git pull`
2. 更新依赖：`pip install -e .[dev]`
3. DB 迁移（如有）：`alembic upgrade head`
4. 重启服务：`systemctl restart medical-agent`
5. 健康检查：`curl /health`
6. 灰度发布（如用 K8s）：滚动更新 10% → 50% → 100%
