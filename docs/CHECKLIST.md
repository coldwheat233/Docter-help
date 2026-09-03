# 项目交付 Checklist

> 全力完成开发并交付。所有待办不分周，全部做。

## 待办清单

- [ ] **A. 真实缓存层**（cache_service.py）— 抽象本地 + Redis 双后端
- [ ] **B. 全局限流**（令牌桶 100 RPS）— 系统级保护
- [ ] **C. PostgresSaver**（状态持久化）— 替代 InMemorySaver
- [ ] **D. HITL interrupt 完整接入**（interrupt() 在节点用）
- [ ] **E. 5 分钟 demo 录屏脚本**（端到端自动跑）
- [ ] **F. 实习报告**（docs/06 素材合成）
- [ ] **G. docs/ 推上 GitHub**
- [ ] **H. Web 多 worker 配置**（gunicorn + nginx）
- [ ] **I. 修复 git history**（移除大文件）

完成后自校验：测试 + 跑一遍端到端 demo。
