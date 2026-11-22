"""Step 结构化步骤：cap/nocap 语义不能在 Bounty 边界上蒸发。

这些用例对应真机踩过的坑：
- 起点读书那单第 2、4 步是 nocap，仍然必须执行（nocap != 已完成）；
- 第 4 步挂着 step_txt 输入框，不填就点提交只弹 toast「有内容没有填写...」；
- 51 条真机语料里 19 步是 cap（27.5%），执行层必须知道哪几步要留证据图。
"""

import unittest

from zrb_agent.schema import Bounty, Step


def make(**kwargs) -> Bounty:
    base = dict(id="t", title="t", reward=1.0, steps=["步骤A"])
    base.update(kwargs)
    return Bounty(**base)


class StepFromValueTest(unittest.TestCase):
    def test_string_becomes_step_without_capture(self):
        step = Step.from_value("复制浏览器打开下载")
        self.assertEqual(step.text, "复制浏览器打开下载")
        self.assertFalse(step.needs_capture)
        self.assertFalse(step.has_text_input)
        self.assertIsNone(step.input_hint)

    def test_dict_from_perceive_cap(self):
        # perceive.extract_steps() 的真实产出形状
        step = Step.from_value(
            {"index": 1, "text": "打开精选页面截图", "type": "cap"})
        self.assertEqual(step.text, "打开精选页面截图")
        self.assertTrue(step.needs_capture)

    def test_dict_from_perceive_nocap_still_executes(self):
        step = Step.from_value(
            {"index": 2, "text": "打开链接", "type": "nocap"})
        self.assertFalse(step.needs_capture)
        self.assertEqual(step.text, "打开链接")

    def test_dict_with_explicit_needs_capture_wins(self):
        step = Step.from_value({"text": "x", "needs_capture": True})
        self.assertTrue(step.needs_capture)

    def test_step_is_idempotent(self):
        original = Step("x", needs_capture=True)
        self.assertIs(Step.from_value(original), original)

    def test_unknown_type_raises(self):
        with self.assertRaises(TypeError):
            Step.from_value(42)

    def test_round_trip_to_dict(self):
        step = Step("按提示输入 1", has_text_input=True, input_hint="按要求输入文字")
        again = Step.from_value(step.to_dict())
        self.assertEqual(again, step)
        self.assertEqual(step.to_dict()["type"], "nocap")


class BountyStepsTest(unittest.TestCase):
    def test_plain_strings_still_work(self):
        # 旧数据 / 手写 bounty 必须零破坏
        bounty = make(steps=["a", "b"])
        self.assertEqual(bounty.step_texts, ["a", "b"])
        self.assertIsInstance(bounty.steps[0], Step)

    def test_perceive_dicts_are_normalized(self):
        bounty = make(steps=[
            {"index": 1, "text": "应用商店下载：起点读书", "type": "cap"},
            {"index": 2, "text": "打开链接", "type": "nocap"},
            {"index": 3, "text": "助力成功截图", "type": "cap"},
            {"index": 4, "text": "输入 1", "type": "nocap"},
        ])
        self.assertEqual(len(bounty.steps), 4)
        self.assertEqual(bounty.step_texts[0], "应用商店下载：起点读书")
        # 关键：cap/nocap 没有被抹平
        self.assertEqual([s.needs_capture for s in bounty.steps],
                         [True, False, True, False])

    def test_capture_indexes_are_one_based(self):
        bounty = make(steps=[
            {"text": "a", "type": "cap"},
            {"text": "b", "type": "nocap"},
            {"text": "c", "type": "cap"},
        ])
        self.assertEqual(bounty.capture_indexes(), [1, 3])

    def test_text_input_indexes(self):
        bounty = make(steps=[
            {"text": "a", "type": "nocap"},
            {"text": "b", "type": "nocap", "has_text_input": True,
             "input_hint": "按要求输入文字"},
        ])
        self.assertEqual(bounty.text_input_indexes(), [2])
        self.assertEqual(bounty.steps[1].input_hint, "按要求输入文字")

    def test_mixed_list_is_normalized(self):
        bounty = make(steps=["旧字符串", {"text": "新字典", "type": "cap"},
                             Step("已是Step", needs_capture=True)])
        self.assertEqual([s.text for s in bounty.steps],
                         ["旧字符串", "新字典", "已是Step"])
        self.assertEqual([s.needs_capture for s in bounty.steps],
                         [False, True, True])

    def test_empty_steps_ok(self):
        bounty = make(steps=[])
        self.assertEqual(bounty.steps, [])
        self.assertEqual(bounty.step_texts, [])
        self.assertEqual(bounty.capture_indexes(), [])

    def test_steps_must_be_list(self):
        with self.assertRaises(TypeError):
            make(steps="不是列表")

    def test_to_dict_serializes_steps(self):
        bounty = make(steps=[{"text": "a", "type": "cap"}])
        data = bounty.to_dict()
        self.assertEqual(data["steps"],
                         [{"text": "a", "type": "cap",
                           "has_text_input": False, "input_hint": None}])

    def test_from_dict_round_trip_keeps_capture(self):
        original = make(steps=[
            {"text": "a", "type": "cap"},
            {"text": "b", "type": "nocap", "has_text_input": True},
        ])
        again = Bounty.from_dict(original.to_dict())
        self.assertEqual([s.needs_capture for s in again.steps], [True, False])
        self.assertTrue(again.steps[1].has_text_input)


class GuardStillReadsTextTest(unittest.TestCase):
    """守卫层只关心原文：结构化之后判定结果必须与纯字符串完全一致。"""

    def test_guard_unchanged_for_same_text(self):
        from zrb_agent.guard.ethics import check_ethics
        from zrb_agent.guard.feasibility import check_feasibility

        texts = ["应用商店下载：起点读书，手机号登录，打开精选页面截图，"]
        as_str = make(steps=list(texts))
        as_dict = make(steps=[{"index": 1, "text": texts[0], "type": "cap"}])
        self.assertEqual(check_ethics(as_str), check_ethics(as_dict))
        self.assertEqual(check_feasibility(as_str), check_feasibility(as_dict))

    def test_no_typeerror_on_structured_steps(self):
        from zrb_agent.guard.feasibility import check_feasibility

        bounty = make(steps=[{"text": "复制浏览器打开下载", "type": "nocap"},
                             {"text": "正确答题", "type": "nocap"}])
        # 改造前这里是 TypeError: sequence item 0: expected str instance
        verdict, reasons = check_feasibility(bounty)
        self.assertIsNotNone(verdict)
        self.assertIsInstance(reasons, list)


if __name__ == "__main__":
    unittest.main()
