"""主循环与账本测试：device / 模型全是手写 fake，不碰真实 adb 与 LLM。"""
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zrb_agent import perceive  # noqa: E402
from zrb_agent.cli import main  # noqa: E402
from zrb_agent.ledger import Ledger, LedgerEntry  # noqa: E402
from zrb_agent.schema import AbortReason, Bounty, Verdict  # noqa: E402
from zrb_agent.schema_action import Action, ActionType  # noqa: E402
from zrb_agent.state_machine import Phase, Runner, default_verify  # noqa: E402

ENROLL_XML = """<hierarchy>
  <node text="赏金 2.13元" resource-id="bb_money" bounds="[35,100][1045,200]" />
  <node text="立即报名" resource-id="btn_apply" bounds="[35,1800][1045,1900]" />
</hierarchy>"""

STEP_XML = """<hierarchy>
  <node text="1" resource-id="com.jianzhiku.zhongrenbang:id/setpcount_nocap"
        bounds="[85,215][143,267]" />
  <node text="浏览器，输入ip，搜索后截图"
        resource-id="com.jianzhiku.zhongrenbang:id/step_detail_nocap"
        bounds="[158,192][1030,764]" />
</hierarchy>"""

DONE_XML = STEP_XML.replace("nocap", "cap")


class FakeDevice:
    """记录调用的最小设备；dump_ui 只写本地文件。"""

    def __init__(self, xml: str = ENROLL_XML) -> None:
        self.xml = xml
        self.tap_calls: list[tuple[int, int]] = []
        self.swipes = 0

    def dump_ui(self, path: str = "ui.xml") -> str:
        Path(path).write_text(self.xml, encoding="utf-8")
        return ""

    def swipe(self, *args) -> str:
        self.swipes += 1
        return ""

    def tap(self, x: int, y: int) -> str:
        self.tap_calls.append((x, y))
        return ""

    def back(self) -> str:
        return ""

    def input_text(self, text: str) -> str:
        return ""

    def open_url(self, url: str) -> str:
        return ""

    def capture_to_gallery(self, name: str) -> str:
        return ""


def finish_done(*_args) -> Action:
    return Action("完成", ActionType.FINISH, {"result": "done"}, "结束")


def failing_tap(*_args) -> Action:
    return Action("点一下", ActionType.TAP, {"x": 10, "y": 20}, "页面变化")


def repeat_tap(*_args) -> Action:
    return Action("再点同一处", ActionType.TAP, {"x": 10, "y": 20}, "下一步")


class LoopTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Ledger()
        self.bounty = Bounty("b1", "测试悬赏", 2.0, ["步骤一"])
        self.device = FakeDevice()
        self.allow = lambda _bounty: (Verdict.DO, None)
        self.xml_path = os.path.join(self.tmp.name, "ui.xml")

    def make_runner(self, plan_fn, guard_fn=None, **kwargs) -> Runner:
        kwargs.setdefault("dry_run", False)
        kwargs.setdefault("sleep_fn", lambda _seconds: None)
        return Runner(self.device, perceive, plan_fn, guard_fn or self.allow,
                      self.ledger, xml_path=self.xml_path, **kwargs)

    def test_guard_abort_never_touches_device(self):
        result = self.make_runner(
            finish_done, lambda _b: (Verdict.ABORT, AbortReason.REGION_REJECTED)
        ).run(self.bounty)
        self.assertEqual(result["phase"], Phase.ABORTED.value)
        self.assertEqual(result["reason"], "REGION_REJECTED")
        self.assertEqual(self.device.tap_calls, [])

    def test_dry_run_stops_after_preflight(self):
        result = self.make_runner(finish_done, dry_run=True).run(self.bounty)
        self.assertEqual(result["phase"], "PREFLIGHT_OK")
        self.assertTrue(result["would_enroll"])
        self.assertEqual(self.device.tap_calls, [])

    def test_finish_done_returns_done_and_writes_ledger(self):
        result = self.make_runner(finish_done).run(self.bounty)
        self.assertEqual(result["phase"], "DONE")
        self.assertTrue(self.ledger.entries)
        self.assertEqual(json.loads(self.ledger.to_jsonl().splitlines()[0])["schema_version"], 1)

    def test_two_failures_abort_stuck(self):
        result = self.make_runner(
            failing_tap, verify_fn=lambda *_args: False
        ).run(self.bounty)
        self.assertEqual(result["phase"], "ABORTED")
        self.assertEqual(result["reason"], "STUCK")
        self.assertEqual(len(self.device.tap_calls), 3)  # 报名 + 两次失败点击

    def test_same_tap_coordinate_blocked_before_max_steps(self):
        self.bounty.steps = ["a", "b", "c", "d"]
        result = self.make_runner(
            repeat_tap, max_steps=20, verify_fn=lambda *_args: True
        ).run(self.bounty)
        self.assertEqual(result["phase"], "ABORTED")
        self.assertLess(len(self.device.tap_calls), 20)
        self.assertEqual(len(self.device.tap_calls), 3)  # 报名 + 两次同坐标

    def test_default_verify_prefers_cap_flags_over_diff(self):
        self.assertTrue(default_verify("x", STEP_XML, DONE_XML))
        self.assertFalse(default_verify("x", DONE_XML, STEP_XML))
        self.assertTrue(default_verify("x", "<a/>", "<b/>"))  # 无模板时退回页面变化

    def test_ledger_jsonl_roundtrip(self):
        self.ledger.append(LedgerEntry(1, "想法", "TAP", {"x": 1}, "预期", "观察", True))
        lines = self.ledger.to_jsonl().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["schema_version"], 1)
        path = os.path.join(self.tmp.name, "ledger.jsonl")
        self.ledger.save(path)
        self.assertEqual(Path(path).read_text(encoding="utf-8"), self.ledger.to_jsonl())


class CliTest(unittest.TestCase):
    def test_default_is_dry_run(self):
        out = StringIO()
        with redirect_stdout(out):
            code = main(["run", "--bounty-id", "b1", "--reward", "2", "--steps", "a,b"])
        self.assertEqual(code, 0)
        self.assertIn("dry-run", out.getvalue())

    def test_live_only_prints_warning(self):
        out = StringIO()
        with redirect_stdout(out):
            code = main(["run", "--bounty-id", "b1", "--reward", "2", "--live"])
        self.assertEqual(code, 0)
        self.assertIn("真实执行会消耗账号名额", out.getvalue())

    def test_dry_run_and_live_are_mutually_exclusive(self):
        with redirect_stdout(StringIO()), self.assertRaises(SystemExit):
            main(["run", "--bounty-id", "b1", "--reward", "2", "--dry-run", "--live"])


if __name__ == "__main__":
    unittest.main()
