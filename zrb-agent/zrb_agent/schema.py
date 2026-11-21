"""数据模型：悬赏任务、执行判定与中止原因。"""

from dataclasses import asdict, dataclass
from enum import Enum

class Verdict(Enum):
    DO = "DO"
    ABORT = "ABORT"

class AbortReason(Enum):
    ETHICS_FABRICATED_IDENTITY = "ETHICS_FABRICATED_IDENTITY"
    ETHICS_FAKE_SURVEY = "ETHICS_FAKE_SURVEY"
    REGION_REJECTED = "REGION_REJECTED"
    UNKNOWN_REGIONS = "UNKNOWN_REGIONS"
    REQUIRES_VPN = "REQUIRES_VPN"
    NEEDS_WECHAT = "NEEDS_WECHAT"
    NEEDS_ALIPAY = "NEEDS_ALIPAY"
    NEEDS_SCANNER = "NEEDS_SCANNER"
    NEEDS_THIRD_PARTY_APP = "NEEDS_THIRD_PARTY_APP"
    UNKNOWN_REWARD = "UNKNOWN_REWARD"
    LOW_REWARD = "LOW_REWARD"
    UNKNOWN_STEPS = "UNKNOWN_STEPS"

@dataclass
class Bounty:
    """一条众包悬赏任务。

    约定：``None`` 表示「没读到」，空列表表示「读到了，确实为空」，两者不能互相代偿。
    ``reward=None`` 是赏金没读到，不能当 0 元判 ``LOW_REWARD``；``allowed_regions``
    是白名单（非空且不含本机即拒），``forbidden_regions`` 是黑名单（含本机即拒），
    空列表表示该方向没有限制。两个地区字段都为 ``None`` 时返回 ``UNKNOWN_REGIONS``；
    两个字段同时非空是相反语义混用，构造时直接 ``ValueError``。
    """

    id: str
    title: str
    reward: float | None
    steps: list[str]
    allowed_regions: list[str] | None = None
    forbidden_regions: list[str] | None = None

    def __post_init__(self) -> None:
        """两个地区字段语义相反，同时非空说明调用方把两种名单混在了一起。"""
        if self.allowed_regions and self.forbidden_regions:
            raise ValueError("allowed_regions 与 forbidden_regions 不能同时设置")

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典（``None`` 原样保留）。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Bounty":
        """从字典还原任务，兼容已废弃的 ``restricted_regions``（按 allowed 处理）。

        字段缺失按「已知为空」处理，显式 ``null`` 才表示「没读到」。
        """
        reward = data.get("reward")
        allowed = data.get("allowed_regions", data.get("restricted_regions", []))
        forbidden = data.get("forbidden_regions", [])
        return cls(
            id=data["id"], title=data["title"],
            reward=None if reward is None else float(reward),
            steps=list(data.get("steps", [])),
            allowed_regions=None if allowed is None else list(allowed),
            forbidden_regions=None if forbidden is None else list(forbidden),
        )
