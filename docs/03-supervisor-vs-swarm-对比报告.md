# 03 - Supervisor vs Swarm 对比报告

> 同一医疗预约场景，分别用 Supervisor 模式（主交付）和 Swarm 模式（对比实验）实现，
> 从代码层、流程层、可控性、HITL 集成、token 成本 5 维对比。

---

## 一、对比概览

| 维度 | Supervisor（主） | Swarm（对比） |
|---|---|---|
| 路由主体 | 中心 Supervisor 节点 LLM | 当前 Agent 主动调用 handoff 工具 |
| 拓扑 | 星型（hub-and-spoke） | 网状（peer-to-peer） |
| 上下文 | Supervisor 看到全部 | 消息"跟着"handoff 走 |
| checkpointer | 可选 | **必须** |
| HITL 集成 | ✅ 集中接入 | ⚠️ 分散在每个 Agent |
| 医疗预约适配 | ✅ 流程型强可控 | ⚠️ 易漂移 |

**结论**：医疗预约场景 **Supervisor 完胜**，Swarm 仅作学术对比。

---

## 二、代码层差异

### 2.1 import 与 Agent 工厂

**Supervisor 模式**：
```python
from langgraph_supervisor import create_supervisor

router_agent = create_react_agent(
    model=llm, tools=[], name="router_agent", prompt=...
)
intake_agent = create_react_agent(
    model=llm, tools=[list_departments], name="intake_agent", prompt=...
)
# ... scheduler_agent, confirmer_agent

workflow = create_supervisor(
    agents=[router_agent, intake_agent, scheduler_agent, confirmer_agent],
    model=llm,
    prompt="你是调度中心...- 路由到 router_agent...",
    output_mode="last_message",
    add_handoff_messages=True,
)
```

**Swarm 模式**：
```python
from langgraph_swarm import create_swarm, create_handoff_tool

# 每个 Agent 必须持 handoff 工具
transfer_to_intake = create_handoff_tool(agent_name="intake_agent", description="...")
transfer_to_scheduler = create_handoff_tool(agent_name="scheduler_agent", description="...")

router_agent = create_react_agent(
    model=llm,
    tools=[transfer_to_intake],  # ← 关键差异
    name="router_agent",
    prompt="你是路由员，需要问诊时调 transfer_to_intake 工具。",
)
intake_agent = create_react_agent(
    model=llm,
    tools=[transfer_to_scheduler],  # ← 每个 Agent 自己决定转给谁
    name="intake_agent",
    prompt="...",
)
# ... scheduler, confirmer 各持 handoff 工具

workflow = create_swarm(
    agents=[router_agent, intake_agent, scheduler_agent, confirmer_agent],
    default_active_agent="router_agent",  # ← 必须指定入口
)
```

### 2.2 关键差异点

| 代码层差异 | Supervisor | Swarm |
|---|---|---|
| 路由逻辑位置 | Supervisor 的 prompt | 每个 Agent 的 prompt + handoff 工具 |
| handoff 工具 | 不需要（Supervisor 内部处理） | 每个 Agent 必须持 1+ 个 handoff 工具 |
| 默认入口 | 不需要 | 必须指定 `default_active_agent` |
| 状态累加 | 全局共享 `messages` | Swarm 自动按 handoff 切换 active agent |
| checkpointer | 可选 | **必须**（记 active_agent） |

---

## 三、流程层差异

### 3.1 同一场景"用户想挂心内科明天的号"

**Supervisor 流程**：
```
User → Supervisor（决策） → router_agent
                              ↓
                          Supervisor（决策）→ intake_agent
                              ↓
                          Supervisor（决策）→ scheduler_agent
                              ↓
                          Supervisor（决策）→ confirmer_agent
                              ↓
                          Supervisor → END
```
- 每次子 Agent 完成**必须**回 Supervisor
- Supervisor 节点做最终路由决策
- **可审计性强**：每一步都过中心节点

**Swarm 流程**：
```
User → router_agent → （调 handoff_to_intake）→ intake_agent
                                                  ↓
                                       （调 handoff_to_scheduler）
                                                  ↓
                                              scheduler_agent
                                                  ↓
                                       （调 handoff_to_confirmer）
                                                  ↓
                                              confirmer_agent
                                                  ↓
                                                END
```
- Agent 完成自己决定下一个 Agent
- 没有中心节点
- **流程漂移风险**：Agent 可能循环 handoff

### 3.2 实际跑的轨迹差异

| 轮次 | Supervisor 节点 | Swarm 节点 |
|---|---|---|
| 1 | supervisor → router_agent | router_agent |
| 2 | router → supervisor → intake_agent | router → intake_agent |
| 3 | intake → supervisor → scheduler_agent | intake → scheduler_agent |
| 4 | scheduler → supervisor → confirmer_agent | scheduler → confirmer_agent |
| 5 | confirmer → supervisor → END | confirmer → END |

**Supervisor 节点数 = 2N+1（N 为子 Agent 数）**；**Swarm 节点数 = N**。

## 四、可控性对比

### 4.1 流程漂移风险

| 风险 | Supervisor | Swarm |
|---|---|---|
| Agent 循环互转 | ⚠️ Supervisor 看到循环可中止 | ❌ 无中心，难中止 |
| 跳过关键 Agent | ✅ Supervisor 强制走 confirmer | ❌ 任意 Agent 可绕过 |
| 多次落库 | ✅ Supervisor 不会让 confirmer 跑两次 | ❌ 可能 |

### 4.2 可解释性

- **Supervisor**：每一步跳转都有 Supervisor 节点的 LLM 决策，可读 LLM log
- **Swarm**：handoff 链是 LLM 自驱的，决策散落在多个 LLM 调用里

### 4.3 状态一致性

- **Supervisor**：StateGraph 集中维护状态
- **Swarm**：消息历史跨 Agent 共享，但 active_agent 在 checkpointer 里

---

## 五、HITL 集成难度

### 5.1 Supervisor 模式

```python
# 在 Supervisor 决策后、confirmer 工具调用前插入
from langgraph.types import interrupt, Command
from langgraph.graph import StateGraph

def human_confirm_node(state):
    decision = interrupt({
        "type": "appointment_confirm",
        "patient_id": state["patient_id"],
        ...
        "ask": "approve / reject"
    })
    return {"pending_human_confirm": False, "status": "confirmed" if decision == "approve" else "cancelled"}

# 装配：supervisor_graph.add_node("human_confirm", human_confirm_node)
# 在 confirmer_agent 之后、END 之前
```

**优点**：HITL 是图的一个节点，Supervisor 知道它存在
**插入位置明确**：在 confirmer_agent → set_appointment 工具调用之间

### 5.2 Swarm 模式

```python
# 每个 Agent 自己持 handoff_to_human 工具
transfer_to_human = create_handoff_tool(agent_name="human_confirm_node", description="...")

# 在 confirmer_agent 的 tools 列表里加这个工具
confirmer_agent = create_react_agent(
    model=llm,
    tools=[set_appointment, transfer_to_human, transfer_to_intake],
    ...
)

# 然后定义一个 human_confirm_node 作为 Swarm 的"Agent"
# 但 Swarm 的"Agent"必须是 ReAct agent，单独定义一个人工节点很别扭
```

**问题**：
- Swarm 的"Agent"必须能调 LLM，但人工节点不需要 LLM
- 必须把"人工节点"包装成一个最小 ReAct agent（违反 Swarm 的对等假设）
- 分散在 4 个 Agent 各自的 prompt 里说明何时调 `transfer_to_human`

**结论**：HITL 在 Swarm 里"能做但丑"，Supervisor 里"自然"。

### 5.3 对比表

| 维度 | Supervisor + HITL | Swarm + HITL |
|---|---|---|
| 接入点 | 1 个图节点 | 4 个 Agent 各埋点 |
| 中断一致性 | 100% 一致 | 易遗漏 |
| 状态恢复 | 简单 | 需同步 active_agent |
| 推荐度 | ✅ 推荐 | ⚠️ 仅对比实验 |

---

## 六、Token 成本对比

按 1 个完整预约流程估算（仅供量级参考）：

| 模式 | LLM 调用次数 | 累计 token（含 prompt） |
|---|---|---|
| Supervisor | 5-7 次（每子 Agent 1-2 次 + Supervisor 决策） | ~6-8K tokens |
| Swarm | 5-7 次（每个 Agent 1-2 次，含 handoff 决策） | ~7-10K tokens |

**差异**：
- Supervisor：每次 Supervisor 决策是 1 次独立 LLM 调用，prompt 固定
- Swarm：每个 Agent 决定何时 handoff 是 LLM 决策的一部分，prompt 包含 handoff 工具描述

**Swarm 略高的原因**：
1. 每个 Agent 的 prompt 要说明何时 handoff
2. handoff 工具描述本身消耗 token
3. 消息历史可能更长（handoff 跨 Agent 携带）

---

## 七、医疗预约场景适用性

| 场景特征 | Supervisor 适配 | Swarm 适配 |
|---|---|---|
| 流程标准化 | ✅ | ⚠️ |
| 强 HITL | ✅ | ❌ |
| 状态一致 | ✅ | ⚠️ |
| 多轮对话复杂 | ✅ | ⚠️ |
| 灵活探索 | ⚠️ | ✅ |

**医疗预约是流程型业务，Supervisor 完胜。**

---

## 八、参考

- LangGraph Multi-Agent 官方文档：<https://langchain-ai.github.io/langgraph/concepts/multi_agent/>
- langgraph-supervisor-py：<https://github.com/langchain-ai/langgraph-supervisor-py>
- langgraph-swarm-py：<https://github.com/langchain-ai/langgraph-swarm-py>
- pareshraut/Langgraph-agents：<https://github.com/pareshraut/Langgraph-agents>（参考 doc-agent/ 的 Supervisor 实现）

---

## 九、附录：跑通对比 demo

```bash
# Supervisor 主模式
python -m medical_agent.main --query "我想挂号"

# Swarm 对比模式
python -m medical_agent.main --swarm --query "我想挂号"
```

两个模式都会输出：
- LLM 调用次数
- Token 消耗
- 流程节点序列（哪个 Agent 跑了多少次）
