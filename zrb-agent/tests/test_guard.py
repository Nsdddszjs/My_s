"""守卫层与数据模型的单元测试（标准库 unittest）。"""

import unittest

from zrb_agent.guard.ethics import DEVICE_REGION, check_ethics
from zrb_agent.guard.feasibility import check_feasibility
from zrb_agent.schema import AbortReason, Bounty, Verdict


def make_bounty(steps, reward=1.0, allowed_regions=(), forbidden_regions=(), **fields):
    """构造测试任务，默认奖励 1 元、地区字段已知且为空（无地区限制）。

    需要「没读到」时显式传 None；空列表表示「读到了，确实为空」。
    ``fields`` 用来透传详情页字段（``type`` / ``limite``）。
    """
    return Bounty(
        "t1", "测试任务", reward, list(steps),
        None if allowed_regions is None else list(allowed_regions),
        None if forbidden_regions is None else list(forbidden_regions),
        **fields,
    )


def ethics(steps, **kwargs):
    return check_ethics(make_bounty(steps, **kwargs))


def feasibility(steps, **kwargs):
    return check_feasibility(make_bounty(steps, **kwargs))


class EthicsGuardTest(unittest.TestCase):
    def test_fabricated_identity(self):
        steps = ["填写姓名", "输入手机号", "输入验证码", "填写地址"]
        self.assertEqual(ethics(steps), AbortReason.ETHICS_FABRICATED_IDENTITY)
        self.assertIsNone(ethics(["填写姓名"]))
    def test_fabricated_identity_extended(self):
        # 编造支：自编号码
        self.assertEqual(ethics(["填155********（后8位自编的11位口令码）"]), AbortReason.ETHICS_FABRICATED_IDENTITY)
        # 编造支：改成别人的地址
        self.assertEqual(ethics(["手动修改成下方口令中地址和邀请码"]), AbortReason.ETHICS_FABRICATED_IDENTITY)
        # 实证件支：需要证件照片（来自 limite）
        self.assertEqual(ethics(["打开链接进入"], limite="新用户 满18周岁 需要证件照片 认证绑卡分类"), AbortReason.ETHICS_FABRICATED_IDENTITY)
        # 实证件支：实名认证
        self.assertEqual(ethics(["完成实名认证"]), AbortReason.ETHICS_FABRICATED_IDENTITY)
        # 不误伤：仅含分类标签
        self.assertIsNone(ethics(["打开App签到"], limite="认证绑卡分类"))
        # 不误伤：提示不要选有广告的（不应被虚假调研误杀）
        self.assertIsNone(ethics(["打开页面", "不要选有广告的"]))
    def test_fake_survey_by_survey_word(self):
        self.assertEqual(ethics(["完成一份调查"]), AbortReason.ETHICS_FAKE_SURVEY)
    def test_fake_survey_by_standard_answer(self):
        self.assertEqual(ethics(["按标准答案作答"]), AbortReason.ETHICS_FAKE_SURVEY)
    def test_region_rejected(self):
        self.assertEqual(ethics(["点每日打卡"], forbidden_regions=["新疆", "云南"]),
                         AbortReason.REGION_REJECTED)
        self.assertEqual(DEVICE_REGION, "云南")
        self.assertEqual(ethics(["签到"], forbidden_regions=["新疆"]), None)
        self.assertIsNone(check_ethics(Bounty("t1", "t", 1.0, ["签到"], forbidden_regions=["新疆"])))
        self.assertIsNone(ethics(["签到"]))
    def test_allowed_region_whitelist(self):
        # allowed_regions 是白名单：非空且不含本机才拒；空列表表示页面无白名单限制。
        self.assertEqual(ethics(["签到"], allowed_regions=["泰国"]), AbortReason.REGION_REJECTED)
        self.assertIsNone(ethics(["签到"], allowed_regions=["云南", "四川"]))
        self.assertIsNone(ethics(["签到"], allowed_regions=[]))
    def test_both_region_lists_non_empty_raises(self):
        with self.assertRaises(ValueError):
            make_bounty(["签到"], allowed_regions=["云南"], forbidden_regions=["新疆"])
    def test_unknown_regions_do_not_pass_as_unrestricted(self):
        self.assertEqual(ethics(["签到"], allowed_regions=None, forbidden_regions=None),
                         AbortReason.UNKNOWN_REGIONS)
    def test_requires_vpn_for_region_switch(self):
        # 「ip调到」是要求改 IP 绕过地区校验，属硬红线，不能落到 LOW_REWARD。
        self.assertEqual(ethics(["各大商店搜索【爱加速】打开，ip调到北京"]),
                         AbortReason.REQUIRES_VPN)
    def test_region_before_survey(self):
        # P743 类：既是问卷又限地区，地区是客观事实，应归因为地区不匹配。
        self.assertEqual(ethics(["完成一份调查"], allowed_regions=["泰国"]),
                         AbortReason.REGION_REJECTED)


class FeasibilityGuardTest(unittest.TestCase):
    def test_ethics_runs_first(self):
        self.assertEqual(feasibility(["填写姓名和手机号", "下载 App"]),
                         (Verdict.ABORT, AbortReason.ETHICS_FABRICATED_IDENTITY))
    def test_needs_wechat(self):
        self.assertEqual(feasibility(["长按识别图中二维码"]), (Verdict.ABORT, AbortReason.NEEDS_WECHAT))
    def test_needs_wechat_slang(self):
        self.assertEqual(feasibility(["用某信打开小程序"]), (Verdict.ABORT, AbortReason.NEEDS_WECHAT))
    def test_needs_alipay(self):
        self.assertEqual(feasibility(["打开支付宝"]), (Verdict.ABORT, AbortReason.NEEDS_ALIPAY))
    def test_needs_alipay_slang(self):
        self.assertEqual(feasibility(["打开某宝扫码"]), (Verdict.ABORT, AbortReason.NEEDS_ALIPAY))
    def test_needs_scanner(self):
        self.assertEqual(feasibility(["保存图片"]), (Verdict.ABORT, AbortReason.NEEDS_SCANNER))
    def test_needs_third_party_app(self):
        self.assertEqual(feasibility(["下载 App"]), (Verdict.ABORT, AbortReason.NEEDS_THIRD_PARTY_APP))
    def test_low_reward(self):
        self.assertEqual(feasibility(["截图上传"], reward=0.17), (Verdict.ABORT, AbortReason.LOW_REWARD))
    def test_reward_none_is_not_low_reward(self):
        self.assertEqual(feasibility(["截图上传"], reward=None),
                         (Verdict.ABORT, AbortReason.UNKNOWN_REWARD))
    def test_unknown_steps(self):
        self.assertEqual(feasibility(["待核"]), (Verdict.ABORT, AbortReason.UNKNOWN_STEPS))
    def test_vague_steps_are_unknown(self):
        # 「按页面提示操作」和「待核」等价，都是没说清要做什么。
        self.assertEqual(feasibility(["按页面提示操作"]), (Verdict.ABORT, AbortReason.UNKNOWN_STEPS))
    def test_long_vague_containing_step_is_ok(self):
        # 长句里夹「按提示」，但整体有具体动作，不能误杀。
        self.assertEqual(feasibility(["按提示操作后截图上传"]), (Verdict.DO, None))
    def test_one_clear_step_is_enough(self):
        # 只要有一条步骤说清了，就还能做。
        self.assertEqual(feasibility(["按页面提示操作", "截图上传"]), (Verdict.DO, None))
    def test_needs_login_by_implicit_action(self):
        # 红果免费短剧真机步骤：全文没有「登录」二字，但助力/搜索挂在账号上。
        self.assertEqual(feasibility([
            "复制链接前往浏览器",
            "再依次复制口令打开红果短剧搜索🔎",
            "助力所有，再右下角我的截图",
        ]), (Verdict.ABORT, AbortReason.NEEDS_LOGIN))
    def test_needs_login_by_explicit_account(self):
        # 秋水织素妆：唯一暴露点是步骤里的「账号手机号」，不能被「下载」抢先。
        self.assertEqual(feasibility([
            "复制到浏览器打开下载", "代号众人帮，账号手机号",
        ]), (Verdict.ABORT, AbortReason.NEEDS_LOGIN))
    def test_needs_login_by_audience_type(self):
        # ai荔枝：步骤只写「下载」，但 type 的「新用户」把它锁死。
        self.assertEqual(feasibility(["应用商店下载ai荔枝"], type="新用户"),
                         (Verdict.ABORT, AbortReason.NEEDS_LOGIN))
    def test_needs_login_by_audience_limite(self):
        # 同一 App 另一条：limite 明确写新用户，步骤里还有「老用户别来」。
        self.assertEqual(feasibility([
            "应用商店下载ai荔枝（老用户别来）", "打开链接复制口令打开ai荔枝助力",
        ], limite="新用户 认证绑卡分类"), (Verdict.ABORT, AbortReason.NEEDS_LOGIN))
    def test_needs_login_by_audience_in_steps(self):
        self.assertEqual(feasibility(["三十天回归后再助力"]),
                         (Verdict.ABORT, AbortReason.NEEDS_LOGIN))
    def test_needs_login_by_audience_multiple_accounts(self):
        # 词绘山河：type 写「每日一次 勿多账号提交」，答题按账号计。
        self.assertEqual(feasibility(["复制浏览器打开下载", "正确答题"],
                                     type="每日一次 勿多账号提交"),
                         (Verdict.ABORT, AbortReason.NEEDS_LOGIN))
    def test_needs_login_by_explicit_register_and_code(self):
        # Issue #49：注册 / 验证码也是显式登录信号，即使通篇没写「登录」。
        self.assertEqual(feasibility(["打开链接注册", "输入验证码"]),
                         (Verdict.ABORT, AbortReason.NEEDS_LOGIN))
    def test_needs_login_by_invite_share_claim_exchange(self):
        # Issue #49 追加的四个依赖登录态的动作词；逐词单独验证，避免互相掩盖。
        for step in ("邀请好友", "分享给好友", "领取奖励", "兑换礼品"):
            with self.subTest(step=step):
                self.assertEqual(feasibility([step]),
                                 (Verdict.ABORT, AbortReason.NEEDS_LOGIN))
    def test_needs_login_by_audience_newcomer_first_order(self):
        self.assertEqual(feasibility(["完成任务"], type="新人首单"),
                         (Verdict.ABORT, AbortReason.NEEDS_LOGIN))
    def test_pure_browse_without_account_action_is_not_login(self):
        # 纯浏览器浏览 + 截图不需要账号，不能被登录规则误伤。
        self.assertEqual(feasibility(["浏览器打开链接浏览商品", "截图上传"]),
                         (Verdict.DO, None))
    def test_download_only_corpus_task_is_never_do(self):
        # 【仙遇】3 元真机语料：唯一一步只写浏览器下载安装，真实达标条件在
        # sm（操作说明图）里。文本守卫读不到图片里的条件，至少必须 ABORT；
        # 精确判 UNKNOWN_STEPS 需要感知层先给出「条件不可读」（#37/#41）。
        verdict, _ = feasibility([
            "浏览器打开链接，直接下载安装，选择上方apk按键，找到\"仙遇\"，点击下载",
        ])
        self.assertIs(verdict, Verdict.ABORT)
    def test_do(self):
        self.assertEqual(feasibility(["截图上传"], reward=1.0), (Verdict.DO, None))
    def test_region_beats_survey_in_feasibility(self):
        self.assertEqual(feasibility(["完成一份调查"], allowed_regions=["泰国"]),
                         (Verdict.ABORT, AbortReason.REGION_REJECTED))
    def test_low_reward_does_not_override_unknown_steps(self):
        self.assertEqual(feasibility(["待核"], reward=0.13),
                         (Verdict.ABORT, AbortReason.UNKNOWN_STEPS))
    def test_low_reward_does_not_override_wechat(self):
        self.assertEqual(feasibility(["微信扫码"], reward=0.17),
                         (Verdict.ABORT, AbortReason.NEEDS_WECHAT))
    def test_low_reward_when_no_other_reason(self):
        self.assertEqual(feasibility(["截图上传"], reward=0.17),
                         (Verdict.ABORT, AbortReason.LOW_REWARD))
    def test_vpn_beats_low_reward(self):
        self.assertEqual(feasibility(["ip调到北京"], reward=0.17),
                         (Verdict.ABORT, AbortReason.REQUIRES_VPN))
    def test_alipay_before_wechat(self):
        # 特异词优先：「支付宝扫码」先命中支付宝，不被通用的「扫码」抢先。
        self.assertEqual(feasibility(["打开支付宝扫码"]), (Verdict.ABORT, AbortReason.NEEDS_ALIPAY))
    def test_scanner_before_wechat(self):
        self.assertEqual(feasibility(["保存图片后扫码"]), (Verdict.ABORT, AbortReason.NEEDS_SCANNER))
    def test_third_party_app_name_table(self):
        # 「复制口令打开得物弹窗」没有「下载」字样，靠 App 名表兜底；
        # 不带「助力/打卡」，否则会先命中隐性登录，测不到 App 名表。
        self.assertEqual(feasibility(["复制口令打开得物弹窗"]),
                         (Verdict.ABORT, AbortReason.NEEDS_THIRD_PARTY_APP))
    def test_open_non_browser_app_pattern(self):
        self.assertEqual(feasibility(["打开星巴克小程序"]),
                         (Verdict.ABORT, AbortReason.NEEDS_THIRD_PARTY_APP))
    def test_open_link_is_not_third_party_app(self):
        self.assertEqual(feasibility(["打开链接填写信息"]), (Verdict.DO, None))


class TwoPhasePreviewTest(unittest.TestCase):
    """大厅预览（steps_incomplete）只给 1 步时不能下可行性结论。"""

    def test_single_step_preview_is_deferred_not_do(self):
        verdict, reason = feasibility(["截图上传"], steps_incomplete=True)
        self.assertIs(verdict, Verdict.DEFERRED)
        self.assertIsNot(verdict, Verdict.DO)
        self.assertIsNone(reason)

    def test_no_steps_preview_is_deferred(self):
        # 列表页抓不到步骤也属于「预览不完整」，不能永久判 UNKNOWN_STEPS。
        self.assertEqual(feasibility([], steps_incomplete=True), (Verdict.DEFERRED, None))

    def test_vague_single_step_preview_is_deferred(self):
        # 预览只有一句套话，报名后可能补出可执行动作，不能按 UNKNOWN_STEPS 拒掉。
        self.assertEqual(feasibility(["按页面提示操作"], steps_incomplete=True),
                         (Verdict.DEFERRED, None))

    def test_preview_with_enough_steps_judges_normally(self):
        # 条件只在有效步骤 <= 1 时生效；4 步预览仍按既有规则判 DO。
        steps = ["打开链接填写信息", "截图上传", "复制文字", "提交截图"]
        self.assertEqual(feasibility(steps, steps_incomplete=True), (Verdict.DO, None))

    def test_complete_single_step_still_do(self):
        # 方向测试：steps_incomplete=False 时 1 步行为与改动前一致。
        self.assertEqual(feasibility(["截图上传"], steps_incomplete=False), (Verdict.DO, None))

    def test_complete_four_steps_still_do(self):
        steps = ["打开链接填写信息", "截图上传", "复制文字", "提交截图"]
        self.assertEqual(feasibility(steps, steps_incomplete=False), (Verdict.DO, None))

    def test_complete_vague_single_step_still_unknown(self):
        self.assertEqual(feasibility(["按页面提示操作"], steps_incomplete=False),
                         (Verdict.ABORT, AbortReason.UNKNOWN_STEPS))

    def test_preview_keeps_ethics_region_abort(self):
        # 地区来自结构化字段，不受步骤完整性影响，仍应先拒。
        self.assertEqual(feasibility(["截图上传"], steps_incomplete=True,
                                     allowed_regions=["泰国"]),
                         (Verdict.ABORT, AbortReason.REGION_REJECTED))

    def test_preview_keeps_platform_keyword_abort(self):
        # 预览步骤是完整步骤的子集，已出现的平台门槛不会因步骤变多而消失。
        self.assertEqual(feasibility(["打开支付宝"], steps_incomplete=True),
                         (Verdict.ABORT, AbortReason.NEEDS_ALIPAY))

    def test_preview_keeps_low_reward_abort(self):
        # 赏金是列表页字段事实，低赏金结论不依赖步骤完整性，照常先判。
        self.assertEqual(feasibility(["截图上传"], reward=0.17, steps_incomplete=True),
                         (Verdict.ABORT, AbortReason.LOW_REWARD))


class SchemaTest(unittest.TestCase):
    def test_dict_round_trip(self):
        bounty = make_bounty(["截图上传"], reward=0.5, allowed_regions=["云南"],
                             type="新用户", limite="一个手机号一次")
        self.assertEqual(Bounty.from_dict(bounty.to_dict()), bounty)
        unknown = Bounty.from_dict(dict(id="u", title="未知", reward=None, steps=["签到"],
                                        allowed_regions=None, forbidden_regions=None))
        self.assertEqual((unknown.reward, unknown.allowed_regions, unknown.forbidden_regions),
                         (None, None, None))
    def test_from_dict_legacy_restricted_regions_is_allowed(self):
        bounty = Bounty.from_dict({
            "id": "old", "title": "旧数据", "reward": 1.0,
            "steps": ["签到"], "restricted_regions": ["泰国"],
        })
        self.assertEqual(bounty.allowed_regions, ["泰国"])
        self.assertEqual(bounty.forbidden_regions, [])
    def test_steps_incomplete_defaults_false_and_round_trips(self):
        # 旧数据没有该字段：必须按 False（步骤完整）处理，不能改变既有判定。
        legacy = Bounty.from_dict({"id": "old", "title": "旧", "reward": 1.0,
                                   "steps": ["截图上传"]})
        self.assertFalse(legacy.steps_incomplete)
        preview = make_bounty(["截图上传"], steps_incomplete=True)
        self.assertTrue(Bounty.from_dict(preview.to_dict()).steps_incomplete)
