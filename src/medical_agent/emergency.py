"""急诊识别（emergency short-circuit）。

当用户描述"突然胸痛"、"剧烈头痛"、"呼吸困难"等急诊症状时：
- ❌ 不走预约流程
- ❌ 不等收集完信息
- ✅ 立即 120 指引
- ✅ 找最近急诊科
- ✅ 给出自我急救建议

触发：用户输入包含急诊关键词
"""

from __future__ import annotations

import re
from typing import Any


# 急诊关键词（中英）
EMERGENCY_KEYWORDS: list[str] = [
    # 心血管
    "突然胸痛", "剧烈胸痛", "胸痛出冷汗", "心梗", "心肌梗死",
    "心绞痛", "胸闷气短", "胸闷呼吸困难",
    # 脑卒中
    "突然偏瘫", "口角歪斜", "言语不清", "一侧无力", "突发昏迷",
    "中风", "脑卒中", "脑梗", "脑出血",
    # 呼吸
    "呼吸困难", "喘不上气", "窒息", "嘴唇发紫", "嘴唇发乌",
    "咯血", "咳血不止", "大量咳血",
    # 创伤
    "大出血", "血流不止", "车祸", "高处坠落",
    # 过敏
    "全身过敏", "喉头水肿", "过敏性休克", "严重过敏",
    # 腹痛
    "剧烈腹痛", "板状腹", "突发剧痛",
    # 其他
    "突然晕倒", "意识丧失", "抽搐不止", "高热惊厥",
    "服药过量", "中毒", "触电", "溺水",
]

EMERGENCY_PATTERN = re.compile("|".join(EMERGENCY_KEYWORDS))


# 急诊响应模板
EMERGENCY_RESPONSE = """⚠️ **您的症状可能是急症，请立即拨打 120 或前往最近的急诊科！**

**症状识别**：{keywords_matched}

**现在请做**：
1. **立即拨打 120**（如果无法立即到院）
2. 或让家人/朋友送您去**最近医院的急诊科**
3. 就医路上保持冷静，不要自行驾车

**同时可以**：
- 舌下含服硝酸甘油（如有冠心病史，胸痛发作时）
- 不要进食、饮水（可能需手术）
- 保持电话畅通以便急救人员联系

**就医时告诉医生**：
- 症状起始时间
- 是否有既往病史
- 正在服用的药物
- 家族病史

⚠️ **本回答不替代医生诊断。情况紧急请立即就医。**"""


def detect_emergency(text: str) -> tuple[bool, list[str]]:
    """检测用户输入是否含急诊关键词。

    Args:
        text: 用户输入

    Returns:
        (is_emergency, matched_keywords)
    """
    if not text:
        return False, []

    matched = [kw for kw in EMERGENCY_KEYWORDS if kw in text]
    return bool(matched), matched


def build_emergency_response(matched: list[str]) -> str:
    """构造急诊响应。"""
    return EMERGENCY_RESPONSE.format(
        keywords_matched="、".join(matched[:3])  # 最多展示 3 个
    )


def is_emergency_node(state: dict) -> dict:
    """急诊检测节点（LangGraph node）。

    用法：在 Supervisor 入口加此节点
    - if 检测到急诊：写入 final_answer 走 END（不调其他 Agent）
    - else：state 不变，走正常流程
    """
    messages = state.get("messages", [])
    if not messages:
        return state

    # 拿最后一条 user 消息
    last_user_msg = None
    for m in reversed(messages):
        if type(m).__name__ == "HumanMessage":
            last_user_msg = m.content if hasattr(m, "content") else str(m)
            break

    if not last_user_msg:
        return state

    is_emergency, matched = detect_emergency(last_user_msg)
    if is_emergency:
        return {
            **state,
            "is_emergency": True,
            "emergency_keywords": matched,
            "final_answer": build_emergency_response(matched),
            "current_step": "done",
        }

    return {"**state": state, "is_emergency": False} if False else state
