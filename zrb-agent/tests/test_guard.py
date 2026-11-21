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
        self.assertEqual(ethics(["点每日打卡"], regions=["新疆", "云南"]), AbortReason.REGION_REJECTED)
        self.assertEqual(DEVICE_REGION, "云南")
        self.assertIsNone(ethics(["签到"], regions=["新疆"]))


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
    def test_do(self):
        self.assertEqual(feasibility(["点每日打卡", "签到"], reward=1.0), (Verdict.DO, None))


class SchemaTest(unittest.TestCase):
    def test_dict_round_trip(self):
        bounty = make_bounty(["签到"], reward=0.5, regions=["云南"])
        self.assertEqual(Bounty.from_dict(bounty.to_dict()), bounty)
