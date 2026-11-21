"""受限动作空间：模型只能输出这 10 种动作，不允许自由文本指令。"""
from dataclasses import dataclass
from enum import Enum

RISK_LEVELS = ("low", "medium", "high")


class ActionType(Enum):
    """允许的动作；新增类型须同步 prompts/planner.md 与执行层。"""
    TAP = "TAP"
    SWIPE = "SWIPE"
    INPUT_TEXT = "INPUT_TEXT"
    BACK = "BACK"
    WAIT = "WAIT"
    OPEN_URL = "OPEN_URL"
    CAPTURE_EVIDENCE = "CAPTURE_EVIDENCE"
    PICK_FROM_GALLERY = "PICK_FROM_GALLERY"
    ASK_HUMAN = "ASK_HUMAN"
    FINISH = "FINISH"


_RULES = {
    ActionType.TAP: lambda p: "ref" in p or ("x" in p and "y" in p),
    ActionType.SWIPE: lambda p: all(isinstance(p.get(k), (list, tuple)) and len(p.get(k)) == 2 for k in ("from", "to")),
    ActionType.INPUT_TEXT: lambda p: "ref" in p and "text" in p,
    ActionType.OPEN_URL: lambda p: isinstance(p.get("url"), str) and p["url"].startswith(("http://", "https://")),
    ActionType.CAPTURE_EVIDENCE: lambda p: "name" in p,
    ActionType.PICK_FROM_GALLERY: lambda p: "name" in p,
    ActionType.ASK_HUMAN: lambda p: "question" in p,
    ActionType.FINISH: lambda p: p.get("result") == "done" or (p.get("result") == "aborted" and "reason" in p),
}


@dataclass
class Action:
    """一个待执行动作：thought 进账本，expect 供事后闭环校验。"""

    thought: str
    action: ActionType
    params: dict
    expect: str
    risk: str = "low"

    def validate(self) -> list[str]:
        """返回错误列表；空表示合法。"""
        errors = []
        if not (str(self.thought).strip() and str(self.expect).strip()):
            errors.append("thought/expect 不能为空")
        if self.risk not in RISK_LEVELS:
            errors.append("risk 只能是 low/medium/high")
        if not isinstance(self.params, dict) or not isinstance(self.action, ActionType):
            return errors + ["params 或 action 类型不合法"]
        if self.risk == "high" and self.params.get("confirm") is not True:
            errors.append("risk=high 时必须 confirm=True")
        if not _RULES.get(self.action, lambda _: True)(self.params):
            errors.append(f"{self.action.value} 参数不合法")
        return errors

    def to_dict(self) -> dict:
        return {"thought": self.thought, "action": self.action.value,
                "params": self.params, "expect": self.expect, "risk": self.risk}

    @classmethod
    def from_dict(cls, data: dict) -> "Action":
        return cls(data["thought"], ActionType(data["action"]),
                   dict(data.get("params") or {}), data["expect"], data.get("risk", "low"))
