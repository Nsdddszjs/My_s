"""决策层单元测试：全部离线，llm_call 由假函数注入。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zrb_agent.perceive import PageState, UiElement  # noqa: E402
from zrb_agent.planner import InvalidActionError, parse_action, plan  # noqa: E402
from zrb_agent.schema_action import Action, ActionType  # noqa: E402

PAGE = PageState("Detail", [UiElement("e12", "立即报名", "btn", (0, 0, 9, 9), (4, 4))])
LEGAL = '{"thought":"点报名","action":"TAP","params":{"ref":"e12"},"expect":"出现弹窗"}'


def fake(*replies):
    calls = []
    def call(messages):
        calls.append(messages)
        return replies[min(len(calls), len(replies)) - 1]
    return call, calls


class PlannerTest(unittest.TestCase):
    def test_valid_action(self):
        action = Action("点报名", ActionType.TAP, {"ref": "e12"}, "出现弹窗")
        self.assertEqual([], action.validate())
        self.assertEqual(action.to_dict(), Action.from_dict(action.to_dict()).to_dict())

    def test_invalid_actions(self):
        cases = (Action("x", ActionType.TAP, {"text": "y"}, "z"),
                 Action("x", ActionType.FINISH, {"result": "ok"}, "z"),
                 Action("x", ActionType.TAP, {"ref": "e12"}, "z", "high"))
        self.assertTrue(all(action.validate() for action in cases))

    def test_parse_tolerates_fence_and_prose(self):
        for raw in (f"```json\n{LEGAL}\n```", f"好的：{LEGAL} 请执行"):
            self.assertEqual("e12", parse_action(raw).params["ref"])
        with self.assertRaises(InvalidActionError) as ctx:
            parse_action("完全不是 json")
        self.assertEqual("完全不是 json", ctx.exception.raw)

    def test_plan_scenarios(self):
        call, calls = fake(LEGAL)
        self.assertEqual(ActionType.TAP, plan(PAGE, "点报名", [], "任务", call).action)
        self.assertEqual(1, len(calls))
        call, calls = fake("垃圾", LEGAL)
        self.assertEqual(ActionType.TAP, plan(PAGE, "点报名", [], "任务", call).action)
        self.assertEqual(2, len(calls))
        self.assertIn("不合法", calls[1][-1]["content"])
        call, _ = fake("垃圾")
        self.assertEqual(ActionType.ASK_HUMAN, plan(PAGE, "点报名", [], "任务", call).action)
