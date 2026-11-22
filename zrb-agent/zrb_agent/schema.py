"""数据模型：悬赏任务、执行判定与中止原因。"""

from dataclasses import asdict, dataclass
from enum import Enum

class Step:
    """详情页的一步操作。

    ``needs_capture=True``（对应 ``step_detail_cap``）表示这一步做完必须落一张
    截图证据再提交；``False``（对应 ``step_detail_nocap``）表示不需要截图，
    **但仍然要执行** —— nocap 不等于已完成，这是真机踩过的坑：
    起点读书那单第 2、4 步都是 nocap，跳过就交不了。

    ``has_text_input`` / ``input_hint`` 对应步骤行内挂的 ``step_txt`` 输入框
    （hint 实测是「按要求输入文字」）。出现这个框时，不填它就点提交只会弹
    700ms 的 toast「有内容没有填写...」，页面不变，极易误判为「提交没反应」。

    所有字段都是纯数据，不做校验：``text`` 允许为空串（真机上出现过只剩序号
    没有正文的步骤行），由调用方决定是否跳过。
    """

    __slots__ = ("text", "needs_capture", "has_text_input", "input_hint")

    def __init__(
        self,
        text: str = "",
        *,
        needs_capture: bool = False,
        has_text_input: bool = False,
        input_hint: str | None = None,
    ) -> None:
        self.text = text
        self.needs_capture = needs_capture
        self.has_text_input = has_text_input
        self.input_hint = input_hint

    @classmethod
    def from_value(cls, value: object) -> "Step":
        """把三种历史形态统一还原成 Step。

        - ``Step``：原样返回（幂等）；
        - ``str``：旧数据，按 ``needs_capture=False`` 处理；
        - ``dict``：``perceive.extract_steps()`` 的产出，键名
          ``text`` / ``type``（"cap"|"nocap"）/ ``has_text_input`` / ``input_hint``。
        """
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(value)
        if isinstance(value, dict):
            return cls(
                str(value.get("text", "")),
                needs_capture=(
                    value.get("needs_capture") is True or value.get("type") == "cap"
                ),
                has_text_input=bool(value.get("has_text_input", False)),
                input_hint=value.get("input_hint"),
            )
        raise TypeError(f"无法还原成 Step：{value!r}")

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典（字段名与 perceive 的产出对齐）。"""
        return {
            "text": self.text,
            "type": "cap" if self.needs_capture else "nocap",
            "has_text_input": self.has_text_input,
            "input_hint": self.input_hint,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Step):
            return NotImplemented
        return (self.text, self.needs_capture, self.has_text_input,
                self.input_hint) == (
            other.text, other.needs_capture, other.has_text_input,
            other.input_hint)

    def __repr__(self) -> str:
        return (f"Step({self.text!r}, needs_capture={self.needs_capture}, "
                f"has_text_input={self.has_text_input}, "
                f"input_hint={self.input_hint!r})")


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
    steps: list[str] | list[dict] | list[Step]
    allowed_regions: list[str] | None = None
    forbidden_regions: list[str] | None = None
    type: str | None = None
    limite: str | None = None
    # 默认 False 追加在末尾：保持既有位置参数用法兼容（详情页数据视为完整）。
    steps_incomplete: bool = False

    def __post_init__(self) -> None:
        """把 steps 规整成 list[Step]，并校验地区字段语义。

        ``steps`` 接受 ``list[str]``（旧数据 / 手写）、``list[dict]``
        （``perceive.extract_steps()`` 的产出）与其混合；统一还原成 :class:`Step`
        之后，``cap`` / ``nocap`` 语义不会在边界上蒸发 —— 执行层据此决定这一步
        做完要不要落截图证据。

        两个地区字段语义相反，同时非空说明调用方把两种名单混在了一起。
        """
        if self.allowed_regions and self.forbidden_regions:
            raise ValueError("allowed_regions 与 forbidden_regions 不能同时设置")
        if not isinstance(self.steps, list):
            raise TypeError(f"steps 必须是 list，收到 {type(self.steps).__name__}")
        if self.steps and all(isinstance(step, Step) for step in self.steps):
            return
        self.steps = [Step.from_value(step) for step in self.steps]

    @property
    def step_texts(self) -> list[str]:
        """步骤原文列表，给只关心文本的守卫层用。

        ``check_ethics`` / ``check_feasibility`` 里的 ``" ".join(bounty.steps)``
        在 steps 变成 Step 之后会抛 ``TypeError: sequence item 0: expected str
        instance``；它们应改用本属性，旧行为逐字节不变。
        """
        return [step.text for step in self.steps]

    def capture_indexes(self) -> list[int]:
        """需要落截图证据的步骤序号（1 起，与 ``step_detail_cap`` 的显示序号对齐）。"""
        return [index for index, step in enumerate(self.steps, 1)
                if step.needs_capture]

    def text_input_indexes(self) -> list[int]:
        """带文本输入框的步骤序号（1 起）；这些步骤不填就提交必然失败。"""
        return [index for index, step in enumerate(self.steps, 1)
                if step.has_text_input]

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典（``None`` 原样保留）。

        ``steps`` 一律写成 ``[{"text","type","has_text_input","input_hint"}]``，
        与 ``perceive.extract_steps()`` 的产出同形，便于账本回放。
        """
        data = asdict(self)
        data["steps"] = [step.to_dict() for step in self.steps]
        return data

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
            steps=list(data.get("steps", [])),  # 交 __post_init__ 规整
            allowed_regions=None if allowed is None else list(allowed),
            forbidden_regions=None if forbidden is None else list(forbidden),
            type=data.get("type"),
            limite=data.get("limite"),
            steps_incomplete=bool(data.get("steps_incomplete", False)),
        )
