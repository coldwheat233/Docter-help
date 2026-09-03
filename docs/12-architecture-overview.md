# 12 - 系统架构总览

> 一图看懂整个项目。

---

## 1. 部署架构（4 层）

```
                      用户
                       │
                  ┌────▼─────┐
                  │ 浏览器/小程序│  (患者/医生/前台)
                  └────┬─────┘
                       │ HTTPS
        ┌──────────────▼──────────────┐
        │  CDN + WAF                 │  Layer 4
        │  (CloudFlare / 阿里云)      │
        └──────────────┬──────────────┘
                       │
                  ┌────▼─────┐
                  │  Nginx    │  反向代理 + 限流 + WebSocket
                  │  (4 worker)│
                  └────┬─────┘
                       │
        ┌──────────────▼──────────────┐
        │  Web 层 (Streamlit/gunicorn)│  Layer 3
        │  - 护栏 / 急诊 / 限流 / 缓存  │  ← 我们做的
        │  - 流式响应 / 输入验证       │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  Agent 层 (LangGraph)        │
        │  - Supervisor 中心调度       │
        │  - 5 Agent (router/intake/   │
        │    scheduler/confirmer/      │
        │    knowledge)                │
        │  - RAG (BM25 + 关键词 + Dense)│
        │  - 熔断 / 限流 / 缓存         │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  数据层                      │
        │  - SQLite (dev) / Postgres   │
        │  - Redis (缓存)              │
        │  - Chroma (向量库, 可选)     │
        └──────────────┬──────────────┘
                       │ (API 同步)
        ┌──────────────▼──────────────┐
        │  HIS (医院核心系统)          │  Layer 2
        │  - 排班主数据 / 患者主索引    │  ← 不做
        │  - 财务 / 医保               │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  LIS/PACS/EMR (临床)         │  Layer 1
        └──────────────────────────────┘
```

---

## 2. Agent 内部架构

```
                           用户输入
                              │
                              ▼
                    ┌──────────────────┐
                    │ 🛡️ Guardrails     │  敏感词/Injection
                    │   (input check)  │  ← 立即拒绝
                    └────────┬─────────┘
                             │ pass
                             ▼
                    ┌──────────────────┐
                    │ 🚑 Emergency     │  "突然胸痛"
                    │   Detection      │  ← 立即 120（不调 LLM）
                    └────────┬─────────┘
                             │ not emergency
                             ▼
                    ┌──────────────────┐
                    │ ⏳ Rate Limiter  │  10 req/min/user
                    └────────┬─────────┘
                             │ pass
                             ▼
                    ┌──────────────────┐
                    │ ⚡ Response Cache│  "感冒发烧"
                    │   (LRU + SQLite) │  ← 秒回（不调 LLM）
                    └────────┬─────────┘
                             │ miss
                             ▼
              ┌──────────────────────────┐
              │ 🎯 Supervisor (LLM 决策) │
              │   prompt: 5 路路由规则      │
              └────────┬─────────────────┘
                       │ tool_calls
        ┌──────────────┼──────────────────────────┐
        │              │              │              │
        ▼              ▼              ▼              ▼
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│  router  │  │  intake  │  │scheduler │  │confirmer │  │knowledge │
│ (LLM)    │  │ (LLM)    │  │  (LLM)   │  │  (LLM)   │  │  (LLM)   │
│          │  │          │  │          │  │          │  │          │
│ 分类     │  │ 抽取     │  │ 推荐     │  │ 落库     │  │ 知识问答 │
│ 意图     │  │ 字段     │  │ 时段     │  │ (HITL)   │  │ (RAG)    │
└────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
     │             │             │             │             │
     ▼             ▼             ▼             ▼             ▼
  classify_    list_         check_        set_         search_
  intent       departments   availability  appointment   medical
                              list_doctors  cancel        knowledge
                                            reschedule
                                            restore
                                               │
                                               ▼
                                    ┌──────────────────┐
                                    │ HITL interrupt    │  人工确认
                                    │   (interrupt())   │
                                    └────────┬─────────┘
                                             │ approve
                                             ▼
                                    ┌──────────────────┐
                                    │ 乐观锁 CAS        │
                                    │  + 事务 + 幂等    │
                                    │  + re-check       │
                                    └────────┬─────────┘
                                             │
                                             ▼
                                         落库 ✓
```

---

## 3. 数据流（一次完整预约）

```
用户: "我想挂号，胃疼"  (T=0s)
   │
   ▼ 护栏 / 急诊 / 限流 / 缓存（<10ms）
   │
   ▼ Supervisor 决策
   │
   ▼ router_agent（2-3s）
   │   output: {"intent": "book"}
   │
   ▼ intake_agent（3-5s × 多轮）
   │   收集: symptoms / duration / severity / department
   │
   ▼ scheduler_agent（3-5s）
   │   工具: check_availability / list_doctors
   │   output: 3-5 个候选时段
   │
   ▼ 用户选定时段
   │
   ▼ confirmer_agent（1-2s）
   │   复述详情 + 询问"确认？"
   │
   ▼ 用户: "确认"
   │
   ▼ HITL interrupt() 暂停
   │
   ▼ human_confirm_node 调 set_appointment
   │   ├── re-check（5ms）
   │   ├── 乐观锁 CAS（10ms）
   │   ├── 事务 + 幂等（10ms）
   │   └── 审计日志（5ms）
   │
   ▼ 落库（<50ms）
   │
   ▼ 通知下游（mock）
   │
   ▼ LLM 生成回复（2-3s）
   │
   ▼ 用户看到"✅ 预约成功，A2026090330FC"
```

**总耗时**：~30-60s（5-7 轮对话）

---

## 4. 高并发架构

```
1000 用户
   │
   ▼ CDN (静态资源 + SSL)
   │
   ▼ Nginx (4 worker, 限流)
   │
   ▼ [Streamlit × 4 instances]  sticky session
   │
   ├─→ 护栏/急诊/限流/缓存（90% 短路）
   │
   ├─→ [Worker pool × 16]  LangGraph
   │   │
   │   ├─→ RAG Cache (Redis, 命中秒回)
   │   │
   │   ├─→ LLM (DeepSeek 限流 50 RPS)
   │   │   │
   │   │   └─→ fallback OpenAI（熔断触发）
   │   │
   │   └─→ [Postgres] 主从
   │       │
   │       └─→ [Read replica × 3]  只读
   │
   ▼ User 看到秒回 / 流式 / 无感
```

**容量估算**：

| 阶段 | RPS | 并发用户 |
|---|---|---|
| 当前（单实例） | 10 | 100 |
| 多 worker + Redis | 100 | 1K |
| K8s 弹性 | 10K | 100K |

---

## 5. 关键组件

| 组件 | 文件 | 行数 | 作用 |
|---|---|---|---|
| **Supervisor** | `graphs/supervisor.py` | 150 | 中心调度，5 Agent 编排 |
| **5 Agents** | `agents/*.py` | 350 | router/intake/scheduler/confirmer/knowledge |
| **State** | `state.py` + `models.py` | 200 | TypedDict + Pydantic 双重约束 |
| **Tools** | `tools/*.py` | 400 | LangChain @tool 函数 |
| **RAG** | `agents/hybrid_search.py` | 250 | 3 路融合检索 |
| **DB** | `db/repositories.py` | 500 | 5 Repository + 乐观锁 + 审计 |
| **Web** | `web/app.py` | 350 | Streamlit 双视图 |
| **Protection** | `guardrails.py` + `emergency.py` + `cache.py` + `rate_limit.py` + `global_limiter.py` | 600 | 输入护栏/急诊/缓存/限流 |
| **Resilience** | `resilience.py` | 200 | 熔断/超时/重试/错误码 |
| **Checkpoint** | `checkpoint.py` | 80 | Memory/Sqlite/Postgres 抽象 |
| **Eval** | `eval/runner.py` | 200 | 20 用例执行 + 指标 |

**总计**：~10000 行代码

---

## 6. 关键决策表

| 决策 | 选择 | 理由 |
|---|---|---|
| Agent 编排 | Supervisor 集中式 | 流程型业务，可控性强 |
| LLM | DeepSeek-chat | 中文好，价格低 |
| Embedding | BGE-large-zh (1024d) | 中文 SOTA |
| 存储 | SQLite → Postgres | 单机 → 集群 |
| 缓存 | LRU + SQLite → Redis | 单进程 → 多实例 |
| Web | Streamlit | 开发快（生产建议 FastAPI） |
| ORM | 不用 ORM（Repository 模式） | LLM 不擅长复杂 SQL，SQL 直观 |
| 向量库 | numpy 内存 → Chroma | 35 KB → 1M+ KB 时切 |
| 状态持久化 | Memory → Sqlite → Postgres | dev → staging → prod |

---

## 7. 端到端测试结果

| 测试 | 结果 |
|---|---|
| 单元测试 | **202/202 passed** |
| 端到端 demo | 43.6s 落库 `A2026090330FC` |
| 意图路由准确率 | 100% (20 用例) |
| 召回率（RAG） | 95%+ (同义词) |
| 平均单次对话 | 44s (目标 ≤ 300s) |

---

## 8. 相关文档

- `docs/00-立项书需求分析.md` — 立项书 9 章节
- `docs/01-架构设计.md` — 详细架构
- `docs/02-接口契约.md` — State/Tool/Agent 签名
- `docs/03-supervisor-vs-swarm-对比报告.md` — 编排模式对比
- `docs/04-数据库设计.md` — SQLite schema
- `docs/05-测试报告.md` — Eval 自动生成
- `docs/06-实习报告素材.md` — 素材
- `docs/07-web-ui.md` — Web 使用
- `docs/08-production-features.md` — 15 大生产特征
- `docs/09-architecture-and-scalability.md` — Scalability
- `docs/10-internship-report.md` — **完整实习报告**
- `docs/11-deployment.md` — 部署指南
- `docs/CHECKLIST.md` — 交付清单
