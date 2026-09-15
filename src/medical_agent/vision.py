"""多模态资料抽取（v6）：GLM-4V 读检查报告/病历照片 → 结构化 JSON + PII 打码。

- 模型：glm-4v-flash（免费，OpenAI 兼容 image_url 接口）
- 输出统一 JSON：doc_type / title / summary / symptoms / key_fields / suggested_department / urgent
- PII 打码：手机号、身份证号在入库和返回前统一脱敏
"""

from __future__ import annotations

import base64
import json
import re

from medical_agent.config import get_settings

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5MB

_EXTRACT_PROMPT = """你是医院门诊系统的医疗资料结构化助手。请阅读这张图片（可能是检查报告、病历、处方等），
只输出一个 JSON 对象，不要输出任何其他文字，格式：
{
  "doc_type": "检查报告|病历|处方|其他 之一",
  "title": "资料标题，如'血常规检验报告单'",
  "summary": "一句话概述（50字内）",
  "symptoms": "图中提到的患者主诉症状，没有则空字符串",
  "key_fields": [{"name": "指标名", "value": "数值+单位", "abnormal": true}],
  "suggested_department": "建议就诊科室，不确定则空字符串",
  "urgent": false
}
urgent=true 仅限明显急症（如剧烈胸痛、疑似中风等）。abnormal=true 表示指标异常。"""


# =====================================================================
# PII 打码
# =====================================================================
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_ID_CARD_RE = re.compile(r"(?<!\d)(\d{6})\d{8}(\d{3}[\dXx])(?!\d)")


def mask_pii(text: str) -> str:
    """手机号 139****5678 / 身份证 110101********1234。"""
    if not text:
        return text
    text = _PHONE_RE.sub(r"\1****\2", text)
    text = _ID_CARD_RE.sub(r"\1********\2", text)
    return text


def _mask_deep(value):
    """递归打码 JSON 结构里的所有字符串。"""
    if isinstance(value, str):
        return mask_pii(value)
    if isinstance(value, list):
        return [_mask_deep(v) for v in value]
    if isinstance(value, dict):
        return {k: _mask_deep(v) for k, v in value.items()}
    return value


# =====================================================================
# GLM-4V 抽取
# =====================================================================
def extract_document(image_bytes: bytes, mime: str) -> dict:
    """读医疗资料图片，返回结构化 dict（已打码）。失败时抛异常由调用方兜底。"""
    import os

    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    api_key = settings.glm_api_key or os.environ.get("GLM_API_KEY", "")
    if not api_key:
        raise RuntimeError("GLM_API_KEY 未配置，无法进行多模态识别")

    b64 = base64.b64encode(image_bytes).decode()
    llm = ChatOpenAI(
        model=settings.glm_vision_model,
        api_key=api_key,
        base_url=settings.glm_base_url,
        max_tokens=1024,
        temperature=0,
        streaming=False,
    )
    resp = llm.invoke(
        [
            HumanMessage(
                content=[
                    {"type": "text", "text": _EXTRACT_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ]
            )
        ]
    )
    return parse_extraction(resp.content)


def parse_extraction(content) -> dict:
    """从模型输出里抠 JSON（容忍 ```json 围栏 / 前后废话）；失败退到纯文本摘要。"""
    text = content if isinstance(content, str) else str(content)
    text = text.strip()
    # 去 markdown 围栏
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        brace = re.search(r"\{.*\}", text, re.S)
        candidate = brace.group(0) if brace else None

    if candidate:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return _normalize(data)
        except json.JSONDecodeError:
            pass

    # 兜底：整段当摘要
    return _normalize(
        {
            "doc_type": "其他",
            "title": "",
            "summary": text[:200],
            "symptoms": "",
            "key_fields": [],
            "suggested_department": "",
            "urgent": False,
        }
    )


def _normalize(data: dict) -> dict:
    """字段规范化 + PII 打码。"""
    doc_type = str(data.get("doc_type") or "其他")
    if doc_type not in ("检查报告", "病历", "处方", "其他"):
        doc_type = "其他"
    fields = data.get("key_fields")
    if not isinstance(fields, list):
        fields = []
    clean_fields = []
    for f in fields[:20]:
        if not isinstance(f, dict):
            continue
        clean_fields.append(
            {
                "name": str(f.get("name") or "")[:50],
                "value": str(f.get("value") or "")[:80],
                "abnormal": bool(f.get("abnormal")),
            }
        )
    return _mask_deep(
        {
            "doc_type": doc_type,
            "title": str(data.get("title") or "")[:80],
            "summary": str(data.get("summary") or "")[:200],
            "symptoms": str(data.get("symptoms") or "")[:200],
            "key_fields": clean_fields,
            "suggested_department": str(data.get("suggested_department") or "")[:30],
            "urgent": bool(data.get("urgent")),
        }
    )
