from collections.abc import Generator
from typing import Any

import requests
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

# 28 risk category codes -> Chinese names
RISK_NAMES = {
    "pc": "色情违禁", "dc": "毒品犯罪", "dw": "危险武器",
    "pi": "财产侵犯", "ec": "经济犯罪", "ac": "辱骂谩骂",
    "def": "诽谤中伤", "ti": "威胁恐吓", "cy": "网络欺凌",
    "ph": "身体健康", "mh": "心理健康", "se": "社会伦理",
    "sci": "科学伦理", "pp": "个人隐私", "cs": "商业机密",
    "acc": "访问控制", "mc": "恶意代码", "ha": "黑客攻击",
    "ps": "物理安全", "ter": "暴力恐怖活动", "sd": "社会扰乱",
    "ext": "极端主义思潮", "fin": "金融建议", "med": "医疗建议",
    "law": "法律建议", "cm": "未成年人不良引导",
    "ma": "未成年人虐待与剥削", "md": "未成年人犯罪",
}

RISK_CODES = list(RISK_NAMES.keys())


class ContentCheckTool(Tool):
    def _yield_result(
        self,
        is_safe: bool,
        risk_category: str | None,
        risk_category_name: str | None,
        risk_score: float,
        risk_details: dict,
        blocked_categories: list,
    ) -> Generator[ToolInvokeMessage, None, None]:
        yield self.create_variable_message("is_safe", is_safe)
        yield self.create_variable_message("risk_category", risk_category or "")
        yield self.create_variable_message("risk_category_name", risk_category_name or "")
        yield self.create_variable_message("risk_score", risk_score)
        yield self.create_variable_message("risk_details", risk_details)
        yield self.create_variable_message("blocked_categories", blocked_categories)

    def _yield_error(self, msg: str) -> Generator[ToolInvokeMessage, None, None]:
        yield from self._yield_result(
            is_safe=False,
            risk_category=None,
            risk_category_name=None,
            risk_score=0.0,
            risk_details={},
            blocked_categories=[],
        )
        yield self.create_variable_message("error", msg)

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        text = tool_parameters.get("text", "")
        if not text or not text.strip():
            yield from self._yield_error("Input text is empty.")
            return

        # Resolve default threshold
        default_threshold = tool_parameters.get("default_threshold")
        if default_threshold is None:
            cred_str = self.runtime.credentials.get("default_threshold", "")
            if cred_str:
                try:
                    default_threshold = float(cred_str)
                except (ValueError, TypeError):
                    default_threshold = 0.5
            else:
                default_threshold = 0.5

        base_url = self.runtime.credentials.get("xguard_service_url", "").rstrip("/")
        if not base_url:
            yield from self._yield_error("XGuard service URL is not configured.")
            return

        # Request with threshold=0.0 to get all scores
        try:
            resp = requests.post(
                f"{base_url}/api/check",
                json={"text": text, "threshold": 0.0},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.Timeout:
            yield from self._yield_error("XGuard service request timed out.")
            return
        except requests.RequestException as e:
            yield from self._yield_error(f"Failed to connect to XGuard service: {e}")
            return

        # Response uses: safe, label, score, scores
        all_scores = data.get("scores", {})

        # Per-category evaluation
        blocked = []
        for code in RISK_CODES:
            enabled = tool_parameters.get(f"{code}_enabled", True)
            if not enabled:
                continue
            cat_threshold = tool_parameters.get(f"{code}_threshold")
            if cat_threshold is None:
                cat_threshold = default_threshold
            score = all_scores.get(code, 0.0)
            if score >= cat_threshold:
                blocked.append({
                    "code": code,
                    "name": RISK_NAMES[code],
                    "score": score,
                    "threshold": cat_threshold,
                })

        blocked.sort(key=lambda x: x["score"], reverse=True)
        is_safe = len(blocked) == 0
        top = blocked[0] if blocked else None

        yield from self._yield_result(
            is_safe=is_safe,
            risk_category=top["code"] if top else None,
            risk_category_name=top["name"] if top else None,
            risk_score=top["score"] if top else data.get("score", 0.0),
            risk_details=all_scores,
            blocked_categories=blocked,
        )
