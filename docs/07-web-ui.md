# 07 - Web UI 使用说明

> 第 1 周交付的 Streamlit Web UI 简单版。

## 启动

```bash
scripts\run_web.bat
# 或
"D:\miniconda3\envs\python311\python.exe" -m streamlit run web/app.py
```

打开浏览器：**http://localhost:8501**

## 界面

```
+--------------------------------------------------+
|  🏥 医疗预约助手                                   |
|  基于 LangGraph 多智能体的医疗预约系统 · 第 1 周    |
+----------+---------------------------------------+
| ⚙️ 设置   |  [对话区]                              |
|          |                                        |
| 编排模式  |  👤 你好，我想挂个号                    |
| ◉ Supervisor |  🤖 ...                              |
| ○ Swarm  |                                        |
|          |  [输入框]                               |
| 🔄 清空对话 |                                       |
|          |                                        |
| 💡 测试话术 |                                      |
| ▶ 你们产品 |                                       |
| ▶ 我想申请 |                                       |
| ▶ 你好... |                                        |
|          |                                        |
| 📊 项目状态 |                                      |
| DB: medical |                                      |
| Mock: true |   ─────────────────────────           |
|          |   消息数: 4   Thread: 7f8a   模式: sup |
+----------+---------------------------------------+
```

## 功能

- Chat 界面：用户消息 + Agent 响应，自动滚动
- 模式切换：侧边栏切换 Supervisor / Swarm
- 测试话术快捷按钮：侧边栏 4 条预置 query
- 清空对话：重置消息历史 + thread_id
- 底部统计：消息数 / Thread ID / 当前模式

## 第 1 周限制

- HITL 未实现：确认预约时不会真弹出人工审批按钮
- 无流式输出：等 Agent 全部跑完才显示
- 无 LangSmith 链接：trace 暂不展示
- 无排班卡片：scheduler 推荐纯文本
- 无预约单查询：落库后看不到单号

## 第 2/3 周可加

- 流式输出（st.write_stream）
- HITL 审批按钮（确认/取消）
- 排班卡片网格（医生/时段/号源）
- LangSmith trace 链接
- 预约历史查询
- 患者 ID 选择器
- 暗色模式

## 文件

- web/app.py — Streamlit 主程序
- scripts/run_web.bat — 启动脚本

## 技术栈

- Streamlit 1.62+
- LangGraph（复用 graphs/supervisor.py 和 graphs/swarm.py）
- SessionState 内存存储（不持久化）
