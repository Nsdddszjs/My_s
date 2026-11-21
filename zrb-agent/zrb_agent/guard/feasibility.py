"""可行性判定：先过伦理守卫，再按步骤关键词与奖励金额过滤。"""

import re

from zrb_agent.guard.ethics import check_ethics
from zrb_agent.schema import AbortReason, Bounty, Verdict

# 判定顺序按「特异 → 通用」：支付宝/淘宝是明确的 App 信号，扫码类词更通用，
# 先判特异词，避免「支付宝扫码」被扫码抢先归因为 NEEDS_WECHAT。
# 「某宝」「支某宝」「ZFB」是平台为规避审核故意写错字的黑话；词表不可能穷举，
# 这里只是针对「故意写错字绕过审核」这一已知对抗行为的最小防线。
_ALIPAY_TERMS = ("支付宝", "淘宝", "某宝", "支某宝", "ZFB", "zfb")
_THIRD_PARTY_TERMS = ("下载", "注册", "试玩", "安装")
_WECHAT_TERMS = (
    "长按识别", "二维码", "扫码", "扫一扫", "识别二维码",
    "某信", "薇信", "威信", "WX", "wx", "VX", "vx",
)

# 第三方 App 名表：平台文案常默认你已装 App，只写「打开 XX」而不写「下载」，
# 只认安装类动词会漏。命中任一 App 名即判 NEEDS_THIRD_PARTY_APP。
_THIRD_PARTY_APPS = (
    "得物", "淘宝", "京东", "拼多多", "抖音", "快手", "哔哩哔哩", "支付宝",
    "微信", "小红书", "美团", "起点读书", "番茄", "番茄小说", "高德",
    "百度地图", "夸克", "剪映", "汽水音乐",
    "联通", "王卡", "微店", "天猫", "滴滴", "麦当劳", "惠康", "手心输入法",
    "穿越火线", "梦幻西游", "爱加速",
)

# 平台文案的惯用句式是「打开 XX」，只认动词会漏；捕获组不在浏览器白名单里，
# 说明打开的是 App、小程序或 App 内页面，同样判 NEEDS_THIRD_PARTY_APP。
_OPEN_APP_PATTERN = re.compile(
    r"打开\s*([\u4e00-\u9fa5A-Za-z0-9]{2,8})\s*(弹窗|App|app|小程序|页面)"
)
_BROWSER_WHITELIST = ("浏览器", "链接", "网页", "百度", "搜狗", "必应")
_MIN_REWARD = 0.30  # 低于三角钱的悬赏不值得执行。

# 不含具体动作的套话：整条步骤只剩这些词，等于没说清要干什么。
_VAGUE_STEP_MARKERS = ("按页面提示", "按提示", "详见", "待核", "按说明", "见页面", "以页面为准")
# 套话步骤都很短；10 字的「按提示操作后截图上传」带具体动作，必须放行，所以上限取 9。
_VAGUE_MAX_LEN = 9


def _is_vague(step: str) -> bool:
    """整条步骤只剩「按页面提示操作」之类套话时返回 True。"""
    return len(step) <= _VAGUE_MAX_LEN and any(marker in step for marker in _VAGUE_STEP_MARKERS)


def check_feasibility(bounty: Bounty) -> tuple[Verdict, AbortReason | None]:
    """返回 (判定, 中止原因)；判定为 DO 时原因为 None。

    低赏金是性价比结论，不是可行性结论，两者不该抢同一个枚举位：LOW_REWARD
    放在所有其它判定之后，只有没有任何其它中止原因时才作为最后理由返回。
    ``reward is None`` 是赏金没读到，返回 UNKNOWN_REWARD，不能当 0 元判 LOW_REWARD。
    """
    reason = check_ethics(bounty)
    if reason is not None:
        return Verdict.ABORT, reason

    text = " ".join(bounty.steps)
    if any(term in text for term in _ALIPAY_TERMS):
        return Verdict.ABORT, AbortReason.NEEDS_ALIPAY
    if "保存图片" in text:
        return Verdict.ABORT, AbortReason.NEEDS_SCANNER
    if any(term in text for term in _WECHAT_TERMS):
        return Verdict.ABORT, AbortReason.NEEDS_WECHAT
    if any(term in text for term in _THIRD_PARTY_TERMS):
        return Verdict.ABORT, AbortReason.NEEDS_THIRD_PARTY_APP
    if any(app in text for app in _THIRD_PARTY_APPS):
        return Verdict.ABORT, AbortReason.NEEDS_THIRD_PARTY_APP
    for match in _OPEN_APP_PATTERN.finditer(text):
        if match.group(1) not in _BROWSER_WHITELIST:
            return Verdict.ABORT, AbortReason.NEEDS_THIRD_PARTY_APP
    steps = [step.strip() for step in bounty.steps if step.strip()]
    # 只要有一条步骤说清了，这单就还能继续做，所以用 all 而不是 any；
    # 长度上限避免误杀「按提示操作后截图上传」这类带具体动作的步骤。
    if not steps or all(_is_vague(step) for step in steps):
        return Verdict.ABORT, AbortReason.UNKNOWN_STEPS
    if bounty.reward is None:
        return Verdict.ABORT, AbortReason.UNKNOWN_REWARD
    if bounty.reward < _MIN_REWARD:
        return Verdict.ABORT, AbortReason.LOW_REWARD
    return Verdict.DO, None
