"""可行性判定：先过伦理守卫，再按步骤关键词与奖励金额过滤。"""

from zrb_agent.guard.ethics import check_ethics
from zrb_agent.schema import AbortReason, Bounty, Verdict

_WECHAT_TERMS = ("长按识别", "二维码", "扫码")
_ALIPAY_TERMS = ("支付宝", "淘宝")
_THIRD_PARTY_TERMS = ("下载", "注册", "试玩", "安装")
_MIN_REWARD = 0.30  # 低于三角钱的悬赏不值得执行。

def check_feasibility(bounty: Bounty) -> tuple[Verdict, AbortReason | None]:
    """返回 (判定, 中止原因)；判定为 DO 时原因为 None。"""
    reason = check_ethics(bounty)
    if reason is not None:
        return Verdict.ABORT, reason

    text = " ".join(bounty.steps)
    if any(term in text for term in _WECHAT_TERMS):
        return Verdict.ABORT, AbortReason.NEEDS_WECHAT
    if any(term in text for term in _ALIPAY_TERMS):
        return Verdict.ABORT, AbortReason.NEEDS_ALIPAY
    if "保存图片" in text:
        return Verdict.ABORT, AbortReason.NEEDS_SCANNER
    if any(term in text for term in _THIRD_PARTY_TERMS):
        return Verdict.ABORT, AbortReason.NEEDS_THIRD_PARTY_APP
    if bounty.reward < _MIN_REWARD:
        return Verdict.ABORT, AbortReason.LOW_REWARD
    steps = [step.strip() for step in bounty.steps if step.strip()]
    if not steps or all(step == "待核" for step in steps):
        return Verdict.ABORT, AbortReason.UNKNOWN_STEPS
    return Verdict.DO, None
