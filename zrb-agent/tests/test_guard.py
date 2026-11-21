"""守卫层与数据模型的单元测试（标准库 unittest）。"""

import unittest

from zrb_agent.guard.ethics import DEVICE_REGION, check_ethics
from zrb_agent.guard.feasibility import check_feasibility
from zrb_agent.schema import AbortReason, Bounty, Verdict


def make_bounty(steps, reward=1.0, regions=None):
    """构造测试任务，默认奖励 1 元、无地区限制。"""
    return Bounty("t1", "测试任务", reward, list(steps), list(regions or []))


def ethics(steps, **kwargs):
    return check_ethics(make_bounty(steps, **kwargs))


def feasibility(steps, **kwargs):
    return check_feasibility(make_bounty(steps, **kwargs))


class EthicsGuardTest(unittest.TestCase):
    def test_fabricated_identity(self):
        steps = ["填写姓名", "输入手机号", "输入验证码", "填写地址"]
        self.assertEqual(ethics(steps), AbortReason.ETHICS_FABRICATED_IDENTITY)
        self.assertIsNone(ethics(["填写姓名"]))
    def test_fake_survey_by_survey_word(self):
        self.assertEqual(ethics(["完成一份调查"]), AbortReason.ETHICS_FAKE_SURVEY)
    def test_fake_survey_by_standard_answer(self):
        self.assertEqual(ethics(["按标准答案作答"]), AbortReason.ETHICS_FAKE_SURVEY)
    def test_region_rejected(self):
        # 地区名单是任务的「允许地区」：名单非空且不含本机所在省份即地区不匹配。
        self.assertEqual(ethics(["点每日打卡"], regions=["新疆", "北京"]), AbortReason.REGION_REJECTED)
        self.assertEqual(DEVICE_REGION, "云南")
        self.assertEqual(ethics(["签到"], regions=["新疆"]), AbortReason.REGION_REJECTED)
        self.assertIsNone(ethics(["签到"], regions=["新疆", "云南"]))
        self.assertIsNone(ethics(["签到"]))
    def test_region_before_survey(self):
        # P743 类：既是问卷又限地区，地区是客观事实，应归因为地区不匹配。
        self.assertEqual(ethics(["完成一份调查"], regions=["泰国"]), AbortReason.REGION_REJECTED)


class FeasibilityGuardTest(unittest.TestCase):
    def test_ethics_runs_first(self):
        self.assertEqual(feasibility(["填写姓名和手机号", "下载 App"]),
                         (Verdict.ABORT, AbortReason.ETHICS_FABRICATED_IDENTITY))
    def test_needs_wechat(self):
        self.assertEqual(feasibility(["长按识别图中二维码"]), (Verdict.ABORT, AbortReason.NEEDS_WECHAT))
    def test_needs_alipay(self):
        self.assertEqual(feasibility(["打开支付宝"]), (Verdict.ABORT, AbortReason.NEEDS_ALIPAY))
    def test_needs_scanner(self):
        self.assertEqual(feasibility(["保存图片"]), (Verdict.ABORT, AbortReason.NEEDS_SCANNER))
    def test_needs_third_party_app(self):
        self.assertEqual(feasibility(["下载 App"]), (Verdict.ABORT, AbortReason.NEEDS_THIRD_PARTY_APP))
    def test_low_reward(self):
        self.assertEqual(feasibility(["点每日打卡"], reward=0.17), (Verdict.ABORT, AbortReason.LOW_REWARD))
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
    def test_do(self):
        self.assertEqual(feasibility(["点每日打卡", "签到"], reward=1.0), (Verdict.DO, None))
    def test_region_beats_survey_in_feasibility(self):
        self.assertEqual(feasibility(["完成一份调查"], regions=["泰国"]),
                         (Verdict.ABORT, AbortReason.REGION_REJECTED))
    def test_low_reward_does_not_override_unknown_steps(self):
        self.assertEqual(feasibility(["待核"], reward=0.13),
                         (Verdict.ABORT, AbortReason.UNKNOWN_STEPS))
    def test_low_reward_does_not_override_wechat(self):
        self.assertEqual(feasibility(["微信扫码"], reward=0.17),
                         (Verdict.ABORT, AbortReason.NEEDS_WECHAT))
    def test_low_reward_when_no_other_reason(self):
        self.assertEqual(feasibility(["点每日打卡", "签到"], reward=0.17),
                         (Verdict.ABORT, AbortReason.LOW_REWARD))
    def test_alipay_before_wechat(self):
        # 特异词优先：「支付宝扫码」先命中支付宝，不被通用的「扫码」抢先。
        self.assertEqual(feasibility(["打开支付宝扫码"]), (Verdict.ABORT, AbortReason.NEEDS_ALIPAY))
    def test_scanner_before_wechat(self):
        self.assertEqual(feasibility(["保存图片后扫码"]), (Verdict.ABORT, AbortReason.NEEDS_SCANNER))
    def test_third_party_app_name_table(self):
        # 「复制口令打开得物弹窗助力打卡」没有「下载」字样，靠 App 名表兜底。
        self.assertEqual(feasibility(["复制口令打开得物弹窗助力打卡"]),
                         (Verdict.ABORT, AbortReason.NEEDS_THIRD_PARTY_APP))
    def test_open_non_browser_app_pattern(self):
        self.assertEqual(feasibility(["打开星巴克小程序"]),
                         (Verdict.ABORT, AbortReason.NEEDS_THIRD_PARTY_APP))
    def test_open_link_is_not_third_party_app(self):
        self.assertEqual(feasibility(["打开链接填写信息"]), (Verdict.DO, None))


class SchemaTest(unittest.TestCase):
    def test_dict_round_trip(self):
        bounty = make_bounty(["签到"], reward=0.5, regions=["云南"])
        self.assertEqual(Bounty.from_dict(bounty.to_dict()), bounty)
