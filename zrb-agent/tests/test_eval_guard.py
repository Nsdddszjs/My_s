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


def make_row(ident, page_text, verdict="abort", reason=None, reward=1.0,
             allowed_regions=None, forbidden_regions=None):
    """构造一条内联种子样本。"""
    row = {
        "id": ident,
        "title": ident,
        "reward": reward,
        "verdict": verdict,
        "reason": reason,
        "page_text": page_text,
    }
    if allowed_regions is not None:
        row["allowed_regions"] = allowed_regions
    if forbidden_regions is not None:
        row["forbidden_regions"] = forbidden_regions
    return row


# 一条必然判对（步骤含「问卷」→ ETHICS_FAKE_SURVEY）。
CORRECT_ABORT_ROW = make_row(
    "必对-调查",
    "必对-调查 赏金1.00元\n操作步骤：\n1.打开问卷链接",
    reason="ETHICS_FAKE_SURVEY",
)
# 一条必然判错：步骤没有关键词，守卫会放行，但标注是 NEEDS_THIRD_PARTY_APP。
WRONG_ROW = make_row(
    "必错-步骤",
    "必错-步骤 赏金1.50元\n操作步骤：\n1.复制口令",
    reason="NEEDS_THIRD_PARTY_APP",
)
# 一条必然判对的可做样本（DO）。不能用「签到/打卡」：它们按账号计，
# 会命中隐式登录规则，不再是可做样本。
CORRECT_DO_ROW = make_row(
    "必对-截图",
    "必对-截图 赏金1.00元\n操作步骤：\n1.截图上传",
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

    def test_only_region_samples_carry_region_fields(self):
        rows = eval_guard.load_seed(SEED_PATH)
        allowed = {row["id"]: row["allowed_regions"] for row in rows if row.get("allowed_regions")}
        forbidden = {row["id"]: row["forbidden_regions"] for row in rows if row.get("forbidden_regions")}
        self.assertEqual(set(allowed), {"P743号调查-泰国", "食品调查2"})
        self.assertEqual(allowed["P743号调查-泰国"], ["泰国"])
        self.assertEqual(set(forbidden), {"378735G畅享套餐h"})
        self.assertIn("云南", forbidden["378735G畅享套餐h"])
        for row in rows:
            bounty = eval_guard.build_bounty(row)
            self.assertEqual((bounty.allowed_regions, bounty.forbidden_regions),
                             (row.get("allowed_regions") or [], row.get("forbidden_regions") or []))

    def test_build_steps_only_takes_numbered_lines(self):
        # 标题行、报名条件、备注都不算步骤，序号也要剥掉。
        page_text = "标题行 赏金2.50元\n操作步骤：\n1.按页面提示操作"
        self.assertEqual(eval_guard.build_steps(page_text), ["按页面提示操作"])
        self.assertEqual(
            eval_guard.build_steps("1.打开链接\n2.截图上传"),
            ["打开链接", "截图上传"],
        )
        self.assertEqual(
            eval_guard.build_steps("1、中文顿号也要认"),
            ["中文顿号也要认"],
        )

    def test_build_bounty_passes_steps_incomplete(self):
        # 预览样本可在 JSONL 里标注 steps_incomplete，评测口径与守卫层一致。
        preview_row = make_row("预览", "1.截图上传", verdict="do")
        preview_row["steps_incomplete"] = True
        self.assertTrue(eval_guard.build_bounty(preview_row).steps_incomplete)
        self.assertFalse(eval_guard.build_bounty(
            make_row("详情", "1.截图上传", verdict="do")).steps_incomplete)


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
        # 判定正确但归因错位：步骤含「问卷」被判成虚假调研，标注却是未知步骤。
        wrong_reason_row = make_row(
            "必错-归因问卷",
            "必错-归因问卷 赏金1.50元\n操作步骤：\n1.打开问卷链接",
            reason="UNKNOWN_STEPS",
        )
        result = eval_guard.evaluate([CORRECT_ABORT_ROW, wrong_reason_row])
        self.assertEqual(result["verdict_correct"], 2)
        self.assertEqual(result["false_positive"], [])
        self.assertEqual(result["false_negative"], [])
        self.assertEqual(result["mismatch"], [{
            "id": "必错-归因问卷",
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
