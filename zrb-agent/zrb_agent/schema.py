"""数据模型：悬赏任务、执行判定与中止原因。"""

from dataclasses import asdict, dataclass, field
from enum import Enum

class Verdict(Enum):
    DO = "DO"
    ABORT = "ABORT"

class AbortReason(Enum):
    ETHICS_FABRICATED_IDENTITY = "ETHICS_FABRICATED_IDENTITY"
    ETHICS_FAKE_SURVEY = "ETHICS_FAKE_SURVEY"
    REGION_REJECTED = "REGION_REJECTED"
    # 要求把 IP 改到指定地区才能继续：骗过平台校验，属红线。
    REQUIRES_VPN = "REQUIRES_VPN"
    NEEDS_WECHAT = "NEEDS_WECHAT"
    NEEDS_ALIPAY = "NEEDS_ALIPAY"
    NEEDS_SCANNER = "NEEDS_SCANNER"
    NEEDS_THIRD_PARTY_APP = "NEEDS_THIRD_PARTY_APP"
    LOW_REWARD = "LOW_REWARD"
    UNKNOWN_STEPS = "UNKNOWN_STEPS"

@dataclass
class Bounty:
    """一条众包悬赏任务。"""

    id: str
    title: str
    reward: float
    steps: list[str]
    restricted_regions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Bounty":
        """从字典还原任务，缺失的步骤与地区使用空列表。"""
        return cls(
            id=data["id"], title=data["title"], reward=float(data["reward"]),
            steps=list(data.get("steps", [])),
            restricted_regions=list(data.get("restricted_regions", [])),
        )
