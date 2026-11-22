"""数据模型：悬赏任务、执行判定与中止原因。"""

from dataclasses import asdict, dataclass
from enum import Enum

class Verdict(Enum):
    DO = "DO"
    ABORT = "ABORT"
    # 当前数据不足以判定：大厅列表预览只给了不完整的步骤，需报名后带完整步骤复判。
    DEFERRED = "DEFERRED"

class AbortReason(Enum):
    ETHICS_FABRICATED_IDENTITY = "ETHICS_FABRICATED_IDENTITY"
    ETHICS_FAKE_SURVEY = "ETHICS_FAKE_SURVEY"
    REGION_REJECTED = "REGION_REJECTED"
    UNKNOWN_REGIONS = "UNKNOWN_REGIONS"
    REQUIRES_VPN = "REQUIRES_VPN"
    NEEDS_WECHAT = "NEEDS_WECHAT"
    NEEDS_ALIPAY = "NEEDS_ALIPAY"
    NEEDS_SCANNER = "NEEDS_SCANNER"
    # 任务动作需要登录态（账号/手机号/短信验证码）才能完成。
    NEEDS_LOGIN = "NEEDS_LOGIN"
    NEEDS_THIRD_PARTY_APP = "NEEDS_THIRD_PARTY_APP"
    # 标题/类型点名了完成动作（试玩、助力、答题等），步骤里却没有对应动作：
    # 装完或按步骤做完不等于达标，属于「完成条件未在步骤中说明」。
    COMPLETION_UNSPECIFIED = "COMPLETION_UNSPECIFIED"
    UNKNOWN_REWARD = "UNKNOWN_REWARD"
    LOW_REWARD = "LOW_REWARD"
    UNKNOWN_STEPS = "UNKNOWN_STEPS"

    @property
    def kind(self) -> "ReasonKind":
        """返回「谁能解开这道门」，用于把多个原因折叠成行动分组。"""
        return _REASON_KINDS[self]


class ReasonKind(Enum):
    """阻断归因分组：环境缺件 / 平台硬门槛 / 红线 / 数据不足 / 性价比结论。"""

    ENVIRONMENT = "ENVIRONMENT"
    PLATFORM = "PLATFORM"
    RED_LINE = "RED_LINE"
    DATA = "DATA"
    ECONOMIC = "ECONOMIC"


_REASON_KINDS = {
    AbortReason.ETHICS_FABRICATED_IDENTITY: ReasonKind.RED_LINE,
    AbortReason.ETHICS_FAKE_SURVEY: ReasonKind.RED_LINE,
    AbortReason.REGION_REJECTED: ReasonKind.RED_LINE,
    AbortReason.REQUIRES_VPN: ReasonKind.RED_LINE,
    AbortReason.NEEDS_WECHAT: ReasonKind.PLATFORM,
    AbortReason.NEEDS_ALIPAY: ReasonKind.PLATFORM,
    AbortReason.NEEDS_SCANNER: ReasonKind.ENVIRONMENT,
    AbortReason.NEEDS_LOGIN: ReasonKind.ENVIRONMENT,
    AbortReason.NEEDS_THIRD_PARTY_APP: ReasonKind.ENVIRONMENT,
    AbortReason.COMPLETION_UNSPECIFIED: ReasonKind.DATA,
    AbortReason.UNKNOWN_REGIONS: ReasonKind.DATA,
    AbortReason.UNKNOWN_REWARD: ReasonKind.DATA,
    AbortReason.UNKNOWN_STEPS: ReasonKind.DATA,
    AbortReason.LOW_REWARD: ReasonKind.ECONOMIC,
}

@dataclass
class Bounty:
    """一条众包悬赏任务。

    约定：``None`` 表示「没读到」，空列表表示「读到了，确实为空」，两者不能互相代偿。
    ``reward=None`` 是赏金没读到，不能当 0 元判 ``LOW_REWARD``；``allowed_regions``
    是白名单（非空且不含本机即拒），``forbidden_regions`` 是黑名单（含本机即拒），
    空列表表示该方向没有限制。两个地区字段都为 ``None`` 时返回 ``UNKNOWN_REGIONS``；
    两个字段同时非空是相反语义混用，构造时直接 ``ValueError``。

    ``type`` / ``limite`` 是详情页的「类型标签」与「报名条件」原文。两者是
    ``None`` 表示没读到，空串表示读到了但为空；登录态判定会读这两项（人群限定
    词只出现在这两个字段的文案里），所以不要把没读到写成空串来冒充「无限制」。

    ``steps_incomplete=True`` 表示 ``steps`` 抓取自大厅列表预览，可能只给出了第 1 步，
    不代表完整任务；守卫层据此不下可行性结论，要求报名后带完整步骤复判。默认
    ``False`` 表示步骤来自详情页或已知完整。
    """

    id: str
    title: str
    reward: float | None
    steps: list[str]
    allowed_regions: list[str] | None = None
    forbidden_regions: list[str] | None = None
    type: str | None = None
    limite: str | None = None
    # 默认 False 追加在末尾：保持既有位置参数用法兼容（详情页数据视为完整）。
    steps_incomplete: bool = False

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

        地区字段缺失按「已知为空」处理，显式 ``null`` 才表示「没读到」；
        ``type`` / ``limite`` 没有历史默认值，缺失与 ``null`` 都按「没读到」处理。
        ``steps_incomplete`` 缺失按 ``False`` 处理（旧数据默认步骤完整）。
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
            type=data.get("type"),
            limite=data.get("limite"),
            steps_incomplete=bool(data.get("steps_incomplete", False)),
        )
