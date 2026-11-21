"""伦理红牌：地区限制、伪造身份与虚假调研（纯逻辑，无副作用）。"""

from zrb_agent.schema import AbortReason, Bounty

# 本机公网 IP 归属地为中国云南省昆明市；换机器时必须按实际 IP 归属地修改。
DEVICE_REGION = "云南"

# 伪造身份：出现「姓名」且出现任一手机 / 验证码 / 地址类词。
_IDENTITY_TERMS = ("手机", "验证码", "地址")
# 虚假调研：要求填写或编造问卷，或指定「标准答案」「不要选」等答案。
_SURVEY_TERMS = ("调查", "问卷", "IPSOS", "标准答案", "不要选")

def check_ethics(bounty: Bounty) -> AbortReason | None:
    """返回伦理红牌原因；通过时返回 None。

    优先级：地区 > 身份 > 调研。地区是客观事实（我不在你那儿），伦理是主观
    决定（我不干这事），所以先讲事实，再讲立场。地区名单表示任务允许的地区
    （如「限泰国 IP」「限 7 城」），本机不在名单内即地区不匹配。
    """
    if bounty.restricted_regions and DEVICE_REGION not in bounty.restricted_regions:
        return AbortReason.REGION_REJECTED
    text = " ".join(bounty.steps)
    if "姓名" in text and any(term in text for term in _IDENTITY_TERMS):
        return AbortReason.ETHICS_FABRICATED_IDENTITY
    if any(term in text for term in _SURVEY_TERMS):
        return AbortReason.ETHICS_FAKE_SURVEY
    return None
