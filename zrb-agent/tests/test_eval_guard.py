"""守卫层评测脚本与种子集的单元测试（标准库 unittest，不连真机、不 import adb）。"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_ZRB_AGENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ZRB_AGENT_ROOT / "scripts"))

import eval_guard  # noqa: E402
from zrb_agent.schema import AbortReason  # noqa: E402

SEED_PATH = _ZRB_AGENT_ROOT / "evals" / "feasibility_seed_v2.jsonl"


def make_row(ident, page_text, verdict="abort", reason=None, reward=1.0, regions=None):
    """构造一条内联种子样本。"""
    row = {
        "id": ident,
        "title": ident,
        "reward": reward,
        "verdict": verdict,
        "reason": reason,
        "page_text": page_text,
    }
    if regions is not None:
        row["restricted_regions"] = regions
    return row


# 一条必然判对（标题含「调查」→ ETHICS_FAKE_SURVEY）。
CORRECT_ABORT_ROW = make_row(
    "必对-调查",
    "必对-调查 赏金1.00元\n操作步骤：\n1.打开问卷链接",
    reason="ETHICS_FAKE_SURVEY",
)
# 一条必然判错：步骤没有关键词，守卫会放行，但标注是 UNKNOWN_STEPS。
WRONG_ROW = make_row(
    "必错-步骤",
    "必错-步骤 赏金1.50元\n操作步骤：\n1.按页面提示操作",
    reason="UNKNOWN_STEPS",
)
# 一条必然判对的可做样本（DO）。
CORRECT_DO_ROW = make_row(
    "必对-签到",
    "必对-签到 赏金1.00元\n操作步骤：\n1.点签到",
    verdict="do",
    reason=None,
)


class EvalGuardCase(unittest.TestCase):
    """提供写临时种子集、运行 main 的辅助方法。"""

    def run_main(self, rows, *extra_args):
        """把内联种子写到临时文件后调用 eval_guard.main，返回 (退出码, 输出)。"""
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed.jsonl"
            seed_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = eval_guard.main(["--seed", str(seed_path), *extra_args])
            return code, captured.getvalue()


class SeedFileTest(EvalGuardCase):
    def test_seed_has_exactly_32_lines(self):
        raw_lines = SEED_PATH.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(raw_lines), 32)
        self.assertEqual(len(eval_guard.load_seed(SEED_PATH)), 32)

    def test_reasons_parse_except_pure_in_app(self):
        # PURE_IN_APP 只是标注用途，不是真正的 AbortReason。
        with self.assertRaises(ValueError):
            AbortReason("PURE_IN_APP")
        for row in eval_guard.load_seed(SEED_PATH):
            if row["reason"] is None:
                self.assertEqual(row["verdict"], "do")
                continue
            self.assertEqual(row["verdict"], "abort")
            try:
                AbortReason(row["reason"])
            except ValueError:
                # 唯一允许的例外就是 PURE_IN_APP。
                self.assertEqual(row["reason"], "PURE_IN_APP", row["id"])

    def test_only_region_samples_carry_restricted_regions(self):
        rows = eval_guard.load_seed(SEED_PATH)
        with_regions = {row["id"]: row["restricted_regions"] for row in rows
                        if row.get("restricted_regions")}
        self.assertEqual(set(with_regions), {"P743号调查-泰国", "食品调查2"})
        self.assertEqual(with_regions["P743号调查-泰国"], ["泰国"])

    def test_build_bounty_passes_restricted_regions(self):
        for row in eval_guard.load_seed(SEED_PATH):
            bounty = eval_guard.build_bounty(row)
            self.assertEqual(bounty.restricted_regions, row.get("restricted_regions") or [])

    def test_build_steps_drops_blank_and_header_lines(self):
        steps = eval_guard.build_steps("标题 赏金1.00元\n\n操作步骤：\n1.第一步\n2.第二步")
        self.assertEqual(steps, ["标题 赏金1.00元", "1.第一步", "2.第二步"])


class EvaluateTest(EvalGuardCase):
    def test_tiny_seed_stats_and_false_positive_exit_code(self):
        # 2 条内联种子：一条必然判对，一条必然判错（标注 abort 却被放行）。
        result = eval_guard.evaluate([CORRECT_ABORT_ROW, WRONG_ROW])
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["verdict_correct"], 1)
        self.assertEqual(result["verdict_acc"], 0.5)
        self.assertEqual(result["reason_total"], 2)
        self.assertEqual(result["reason_correct"], 1)
        self.assertEqual(result["reason_acc"], 0.5)
        self.assertEqual(result["false_positive"], ["必错-步骤"])
        self.assertEqual(result["false_negative"], [])
        self.assertEqual(result["mismatch"], [])
        self.assertEqual(eval_guard.exit_code(result), 2)

    def test_tiny_seed_exit_code_one_for_reason_mismatch(self):
        # 判定正确但归因错位：标题含「调查」的样本被标成 UNKNOWN_STEPS。
        wrong_reason_row = make_row(
            "必错-归因调查",
            "必错-归因调查 赏金1.50元\n操作步骤：\n1.按页面提示操作",
            reason="UNKNOWN_STEPS",
        )
        result = eval_guard.evaluate([CORRECT_ABORT_ROW, wrong_reason_row])
        self.assertEqual(result["verdict_correct"], 2)
        self.assertEqual(result["false_positive"], [])
        self.assertEqual(result["false_negative"], [])
        self.assertEqual(result["mismatch"], [{
            "id": "必错-归因调查",
            "expected": "UNKNOWN_STEPS",
            "actual": "ETHICS_FAKE_SURVEY",
        }])
        self.assertEqual(eval_guard.exit_code(result), 1)

    def test_tiny_seed_exit_code_zero_when_all_correct(self):
        result = eval_guard.evaluate([CORRECT_ABORT_ROW, CORRECT_DO_ROW])
        self.assertEqual(result["verdict_correct"], 2)
        self.assertEqual(result["reason_correct"], 1)
        self.assertEqual(result["do_total"], 1)
        self.assertEqual(eval_guard.exit_code(result), 0)

    def test_json_output_has_required_fields(self):
        code, output = self.run_main([CORRECT_ABORT_ROW, WRONG_ROW], "--json")
        payload = json.loads(output)
        self.assertEqual(
            set(payload),
            {"verdict_acc", "reason_acc", "false_positive", "false_negative", "mismatch"},
        )
        self.assertEqual(payload["false_positive"], ["必错-步骤"])
        self.assertEqual(code, 2)

    def test_human_report_lists_summary_and_confusions(self):
        code, output = self.run_main([CORRECT_ABORT_ROW, WRONG_ROW])
        self.assertIn("判定 1/2 = 50.0%", output)
        self.assertIn("归因 1/2 = 50.0%", output)
        self.assertIn("假阳性", output)
        self.assertIn("必错-步骤", output)
        self.assertIn("归因错位", output)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()