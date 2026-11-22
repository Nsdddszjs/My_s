"""伦理红牌：地区限制、伪造身份与虚假调研（纯逻辑，无副作用）。"""

from zrb_agent.schema import AbortReason, Bounty

# 本机公网 IP 归属地为中国云南省昆明市；换机器时必须按实际 IP 归属地修改。
DEVICE_REGION = "云南"

# 分类标签剔除：悬赏大厅的分类标签（如「认证绑卡分类」）不是任务要求，需剔除避免误判
_CATEGORY_LABELS = ("认证绑卡分类", "注册下载体验", "简单帮忙体验",
                    "积分兑换体验", "其他体验", "全部体验")

_LEGACY_IDENTITY_TERMS = ("手机", "验证码", "地址", "证件照", "证件", "实名", "绑卡", "认证")
_FABRICATION_VERBS = ("自编", "编造", "随意填", "随便填", "乱填", "不用真实",
                      "无需真实", "多换几个号码", "虚拟号",
                      "改成", "修改成", "改为")
_REAL_IDENTITY_REQS = ("实名认证", "证件照", "证件照片", "身份证", "人脸识别", "绑卡")

# 虚假调研：要求填写或编造问卷，或指定「标准答案」等答案（移除「不要选」通用选购词避免误伤）
_SURVEY_TERMS = ("调查", "问卷", "IPSOS", "标准答案")
# 改 IP 绕过地区校验：不是「我在不在那儿」，而是「去骗校验」，属硬红线。
_VPN_TERMS = ("ip调到", "IP调到")

def _identity_text(bounty: Bounty) -> str:
    text = " ".join(p for p in (bounty.limite, *bounty.steps) if p)
    for label in _CATEGORY_LABELS:
        text = text.replace(label, "")
    return text

def _is_fabricated(text: str) -> bool:
    if "姓名" in text and any(t in text for t in _LEGACY_IDENTITY_TERMS):
        return True          # 保留旧支：兼容原有测试
    if any(v in text for v in _FABRICATION_VERBS):
        return True
    return any(r in text for r in _REAL_IDENTITY_REQS)

def check_ethics(bounty: Bounty) -> AbortReason | None:
    """返回伦理红牌原因；通过时返回 None。

    优先级：地区（拒）> 改 IP > 身份 > 调研 > 地区（未知）。地区是客观事实，
    伦理是主观决定，所以先讲事实再讲立场。地区语义以字段名为准：黑名单
    ``forbidden_regions`` 含本机即拒，白名单 ``allowed_regions`` 非空且不含本机即拒；
    空列表表示该方向没有限制；两个都为 ``None`` 时返回 ``UNKNOWN_REGIONS``。
    """
    if bounty.forbidden_regions and DEVICE_REGION in bounty.forbidden_regions:
        return AbortReason.REGION_REJECTED
    if bounty.allowed_regions and DEVICE_REGION not in bounty.allowed_regions:
        return AbortReason.REGION_REJECTED
    text = " ".join(bounty.steps)
    if any(term in text for term in _VPN_TERMS):
        return AbortReason.REQUIRES_VPN
    ident_text = _identity_text(bounty)
    if _is_fabricated(ident_text):
        return AbortReason.ETHICS_FABRICATED_IDENTITY
    if any(term in text for term in _SURVEY_TERMS):
        return AbortReason.ETHICS_FAKE_SURVEY
    if bounty.allowed_regions is None and bounty.forbidden_regions is None:
        return AbortReason.UNKNOWN_REGIONS
    return None
