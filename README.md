# 医疗预约多智能体系统

> 基于 LangGraph 的多智能体医疗预约系统，Supervisor + Swarm 双编排对比实现。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![LangGraph 0.3+](https://img.shields.io/badge/langgraph-0.3+-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![DeepSeek](https://img.shields.io/badge/llm-deepseek--chat-purple.svg)](https://platform.deepseek.com/)

## 项目简介

构建一个可演示的医疗预约系统：用户通过自然语言描述病情，系统自动完成 **问诊信息收集 → 时间推荐 → 人工确认 → 落库** 全流程。

**核心特性**：
- ✅ **4 个子 Agent 协作**：路由 / 问诊 / 推荐 / 确认
- ✅ **Supervisor 集中编排**（主）+ **Swarm 去中心化对比实验**
- ✅ **HITL 100% 把门**：所有写操作前必须人工确认
- ✅ **SQLite 5 张表**：科室 / 医生 / 排班 / 患者 / 预约
- ✅ **LangSmith 全链路追踪**

## 项目结构

```
medical-appointment-agent/
├── src/medical_agent/         # 源代码
│   ├── agents/                 # 4 个子 Agent
│   ├── graphs/                 # Supervisor + Swarm 装配
│   ├── tools/                  # LangChain @tool 函数
│   ├── db/                     # 数据库 + Repository
│   ├── state.py                # State TypedDict
│   ├── llm.py                  # ChatDeepSeek 工厂
│   └── main.py                 # 入口
├── demos/                      # 3 个可跑 demo
├── tests/                      # pytest + JSON 用例
├── docs/                       # 6 份文档
├── scripts/                    # 一键脚本
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
# 编辑 .env，填入 DEEPSEEK_API_KEY（必须）
#           和 LANGSMITH_API_KEY（可选）
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
pytest -q
```

输出：
```
tests/test_state.py ....            [ 40%]
tests/test_repositories.py .....    [100%]
5 passed
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
| langchain-deepseek | ≥ 0.1.0 | ChatDeepSeek |
| LangSmith | ≥ 0.2.0 | 可观测（仅环境变量配置） |
| SQLite | 3 | 数据库 |

## 风险与限制

- **第 1 周为骨架阶段**：Agent 不真正调用工具、不落库，HITL 流程未启用
- **D 盘空间紧**：conda env 必须装到 C 盘（`miniconda3\envs\medical-appointment`）
- **Python 3.13 兼容性未明确**：本项目用 3.11
- **deepseek-reasoner 不支持 tool calling**：必须用 `deepseek-chat`

## 贡献者

- 董骐睿（产品）/ 顾竣熙（技术）/ 白雷（项目）
- 张艺博（路由 + Supervisor）/ 陈熙睿（推荐 + 存储）/ 董超（HITL）/ 陈家兴（测试 + 文档）

## 许可

MIT
