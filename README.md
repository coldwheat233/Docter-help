# 医疗预约多智能体系统

> 基于 LangGraph 的多智能体医疗预约系统，Supervisor + Swarm 双编排对比实现。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![LangGraph 0.3+](https://img.shields.io/badge/langgraph-0.3+-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![GLM](https://img.shields.io/badge/llm-GLM--4.5--flash-green.svg)](https://open.bigmodel.cn/)

## 项目简介

构建一个可演示的医疗预约系统：用户通过自然语言描述病情，系统自动完成 **问诊信息收集 → 时间推荐 → 人工确认 → 落库** 全流程。

**核心特性**：
- ✅ **4 个子 Agent 协作**：路由 / 问诊 / 推荐 / 确认
- ✅ **规则前置路由 + LLM Supervisor 兜底**：意图明确走确定性直连节点（0ms、不翻车），意图模糊才交给 LLM 路由
- ✅ **确定性问诊抽取**：intake 用结构化输出直接写 state，不赌工具调用
- ✅ **HITL 100% 把门（机制级）**：`interrupt()` 下沉到 set/cancel/reschedule/restore 四个写工具内部，人工 approve 前不产生任何副作用，不依赖 prompt 约定
- ✅ **主 LLM：智谱 GLM**（OpenAI 兼容接口，免费 glm-4.5-flash 起步；GLM 未配置自动回退 DeepSeek）
- ✅ **排班可视化直选**：患者端排班面板点选号源直约，过期时段全链路拦截（推荐/选定/落库三层校验）
- ✅ **业务中台实时审批**：写操作审批单只进中台（SSE 实时推送，患者提交 ≈0.5s 可见）；中台核准/驳回后患者端 ≈3s 内自动收到结果，审批单不对患者暴露
- ✅ **多模态病历**：检查报告拍照上传 → GLM-4V 结构化抽取 → 手机号/身份证自动打码入库
- ✅ **就诊摘要**：聚合历史预约 + 病历资料生成医生侧摘要（辅助归纳，不下诊断）
- ✅ **LangSmith 全链路追踪**（配置 LANGSMITH_API_KEY 后启用）

## 项目结构

```
medical-appointment-agent/
├── src/medical_agent/         # 源代码
│   ├── agents/                 # 4 个子 Agent + 确定性 intake 节点
│   ├── graphs/                 # Supervisor 装配 + 确定性确认落库节点
│   ├── tools/                  # LangChain @tool 函数
│   ├── vision.py               # GLM-4V 多模态抽取 + PII 打码
│   ├── admin_tools.py          # 中台管理函数（排班/医生/统计/审计）
│   ├── db/                     # 数据库 + Repository（7 张表）
│   ├── state.py                # State TypedDict
│   ├── llm.py                  # GLM/DeepSeek 统一工厂
│   └── main.py                 # CLI 入口
├── web/                        # FastAPI 后端（SSE 流式 + 中台 + REST）
├── web-react/                  # React 前端（患者端 + 业务中台）
├── demos/                      # 可跑 demo
├── tests/                      # pytest + JSON 用例
├── scripts/                    # 一键脚本 + e2e 回归脚本
└── references/                 # 调研参考（不进 git）
```

## 快速开始（5 步）

### 1. 准备环境

需要 Python 3.11+ 和 conda。

```bash
# 激活或创建 medical-appointment 环境
conda activate medical-appointment   # 如果已有
# 或运行一键脚本（装到 C 盘）
scripts\setup_env.bat
```

### 2. 配置 .env

```bash
copy .env.example .env
# 编辑 .env，填入 GLM_API_KEY（主 LLM，免费模型 glm-4.5-flash 即可跑通）
#           DEEPSEEK_API_KEY（可选，GLM 未配置时的兜底）
#           LANGSMITH_API_KEY（可选）
```

### 3. 安装依赖

```bash
pip install -e ".[dev]"
```

### 4. 初始化数据

```bash
scripts\seed_db.bat
# 或：python scripts/seed_db.py
```

输出：
```
✓ 模拟数据生成完成
  科室：5
  医生：20
  排班：~1260 条
  患者：10
```

### 5. 跑 demo

```bash
# Demo 01: Supervisor 基础（验证包安装）
python demos/01_voice_supervisor_demo.py

# Demo 02: Swarm 基础（验证包安装）
python demos/02_voice_swarm_demo.py

# Demo 03: 医疗预约端到端
python demos/03_medical_appointment_demo.py

# 或交互式
python -m medical_agent.main
```

### 6. Web 界面（推荐演示入口）

「数字病历夹」设计：聊天 = 病历纸，审核流程 = 中台盖章。

**一键启动（Windows）**：双击 `scripts\run_react_web.bat`（自动起后端+前端+开浏览器）

手动启动：
```bash
# 终端 1：FastAPI 后端（包 LangGraph 链路）
# 注意：① 必须在项目根目录执行 ② 必须用 python311 环境（base 环境缺依赖）
cd D:\PY_PROJ\NEW\medical-appointment-agent
D:\miniconda3\envs\python311\python.exe -m uvicorn web.api:app --port 8000

# 终端 2：Vite 前端（开发热更新）
cd web-react && npm install && npm run dev
# 打开 http://localhost:5173
```

生产模式：`cd web-react && npm run build` 后只起 FastAPI（8000 端口直接托管 dist）。

**双端演示流程**（开两个浏览器页面）：

| 端 | 账号 | 能力 |
|---|---|---|
| 患者端 | 注册/登录（如 `glmtest02`） | 聊天问诊预约、排班面板点选号源直约、📎 上传检查报告（GLM-4V 识别）、病历资料/历史预约/就诊摘要、预约卡直接取消/改约 |
| 业务中台 | `staff / Staff123456` | 审批队列实时推送（SSE）、核准/驳回、排班可视化网格 + 关键词检索 + 图表看板、排班管理、审计日志 |

实时闭环：患者提交申请 ≈0.5s 内推送到中台（SSE）；中台核准/驳回 ≈3s 内患者端自动收到结果（无需刷新）。审批单不对患者暴露，审核权只在中台。

## 主要 API

```
POST /api/register | /api/login        患者注册/登录（staff 登录返回 role=staff 进入中台）
POST /api/chat/stream                  SSE 流式对话（进度/消息/提交审核/结果）
GET  /api/schedules                    未过期排班（患者排班面板）
POST /api/select-slot                  患者直选号源 → 写入会话 → 对话确认
GET  /api/appointments                 我的预约（含历史，is_upcoming/is_past 分组）
POST /api/appointments/{id}/cancel     患者取消自己的预约
POST /api/appointments/{id}/reschedule 患者改约（乐观锁 + 过期校验）
POST /api/upload                       上传检查报告（GLM-4V 抽取 + PII 打码）
GET  /api/documents | /api/summary     病历资料 / 就诊摘要
GET  /api/threads/{tid}/status         患者轮询审核结果
GET  /api/admin/approvals[/stream]     中台审批队列（REST / SSE 实时流）
POST /api/admin/approvals/decision     中台核准/驳回
GET  /api/admin/stats | /audit         今日统计 / 审计日志
GET  /api/admin/schedules/view         排班总览（含满员，可视化用）
POST /api/admin/schedules[/{id}/{op}]  排班创建/停用/恢复/调容量
GET  /api/metrics                      运行指标（熔断/限流/会话）
```

## 命令行用法

```bash
# 交互式 Supervisor 模式
python -m medical_agent.main

# 交互式 Swarm 对比模式
python -m medical_agent.main --swarm

# 单条 query
python -m medical_agent.main --query "我想挂号"
python -m medical_agent.main --swarm --query "改个时间"

# 重新生成模拟数据
python -m medical_agent.main --seed
```

## 运行测试

```bash
# 单元测试
pytest -q

# 全链路回归（需后端运行在 8000 端口）
python scripts/e2e_schedule_flow.py   # 排班直选 → 确认 → HITL → 落库
python scripts/e2e_admin_flow.py      # 患者提交 → 中台审批 → 统计审计
python scripts/e2e_realtime.py        # SSE 推送 + 患者轮询实时性
```

## 文档导览

| 文档 | 内容 |
|---|---|
| [00-立项书需求分析.md](docs/00-立项书需求分析.md) | 拆解立项书 9 章节为可执行需求 |
| [01-架构设计.md](docs/01-架构设计.md) | 总体架构 + 4 Agent 分工 + State 流转 |
| [02-接口契约.md](docs/02-接口契约.md) | State / Tool / Agent / Repository 全部签名 |
| [03-supervisor-vs-swarm-对比报告.md](docs/03-supervisor-vs-swarm-对比报告.md) | 5 维对比 + 结论 |
| [04-数据库设计.md](docs/04-数据库设计.md) | 5 张表 + ER 图 + 索引 |
| [05-测试报告.md](docs/05-测试报告.md) | 第 3 周填充 |
| [06-实习报告素材.md](docs/06-实习报告素材.md) | 简历 / 面试题 / 总结模板 |

## 第 1 周完成度

- [x] 可运行环境
- [x] 架构设计 + 接口契约
- [x] 跑通 3 个 demo
- [x] Supervisor vs Swarm 对比报告
- [x] 4 个子 Agent 骨架
- [x] SQLite 5 张表 + Repository
- [x] 模拟数据生成（5 科室 + 20 医生 + 30 天排班）
- [x] 5 个测试用例骨架
- [x] README

第 2 周：业务实现 + HITL 完整接入 + 端到端 demo
第 3 周：20+ 测试用例 + 指标统计 + 5 分钟 demo

## 技术栈

| 组件 | 版本 | 用途 |
|---|---|---|
| Python | 3.11 | 主语言 |
| langgraph | ≥ 0.3.0 | StateGraph + interrupt |
| langgraph-supervisor | ≥ 0.0.15 | create_supervisor |
| langgraph-swarm | ≥ 0.0.14 | create_swarm + handoff |
| 智谱 GLM | glm-4.5-flash / glm-4v-flash | 主 LLM（OpenAI 兼容）+ 多模态识别 |
| langchain-openai | ≥ 0.3 | GLM/DeepSeek 统一接入（function_calling 结构化输出） |
| langchain-deepseek | ≥ 0.1.0 | ChatDeepSeek（备选主 LLM） |
| FastAPI | ≥ 0.110 | REST + SSE 流式后端 |
| React 19 + Vite + Tailwind 4 | — | 患者端 / 业务中台前端 |
| LangSmith | ≥ 0.2.0 | 可观测（仅环境变量配置） |
| SQLite | 3 | 数据库（7 张表） |

## 风险与限制

- **conda 环境名不符**：README 原说装到 `medical-appointment` env，实际依赖装在 `D:\miniconda3\envs\python311`；base 环境缺 `langchain_deepseek`/`langgraph_supervisor`，跑测试请用 python311 env
- **GLM 余额**：`glm-4.5-flash`/`glm-4v-flash` 免费可用；`glm-4.6` 需账户充值（实测无余额报 code 1113），切换只需改 `.env` 的 `GLM_MODEL`
- **GLM 不支持 json_schema response_format**：`with_structured_output` 必须用 `method="function_calling"`，否则新版 OpenAI SDK 会把模型文本当增量 JSON 解析报错
- **Swarm 模式是空壳对比实验**：4 个 Agent 只挂 handoff 工具，无业务工具，不能完成真实预约；演示请用 Supervisor 模式
- **非图环境写操作默认拦截**：单测/demo 直接调写工具需设 `MEDICAL_HITL_BYPASS=1`
- **审批不暴露给患者**：患者侧无审批卡、无 `/api/approve`，核准/驳回只能在中台（staff 鉴权）完成
- **token 存内存**：后端重启后所有登录态失效需重新登录；审批队列扫描基于内存 checkpointer，同理

## 贡献者

- 董骐睿（产品）/ 顾竣熙（技术）/ 白雷（项目）
- 张艺博（路由 + Supervisor）/ 陈熙睿（推荐 + 存储）/ 董超（HITL）/ 陈家兴（测试 + 文档）

## 许可

MIT
