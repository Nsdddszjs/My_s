"""守卫层评测脚本：在固定种子集上统计判定准确率、归因准确率与混淆明细。

用法（在 zrb-agent 目录下运行）：

    python3 scripts/eval_guard.py
    python3 scripts/eval_guard.py --seed evals/feasibility_seed_v2.jsonl
    python3 scripts/eval_guard.py --json

退出码：全部正确 0；有假阳性 2（最危险）；仅归因错位或假阴性 1；
种子集读取失败 3。这样可以直接接 CI。
"""

import argparse
import json
import re
import sys
from pathlib import Path

# 允许直接以 `python3 scripts/eval_guard.py` 运行，无需先安装本包。
_ZRB_AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(_ZRB_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_ZRB_AGENT_ROOT))

from zrb_agent.guard.feasibility import check_feasibility  # noqa: E402
from zrb_agent.schema import Bounty, Verdict  # noqa: E402

DEFAULT_SEED = _ZRB_AGENT_ROOT / "evals" / "feasibility_seed_v2.jsonl"
# 只认「1. xxx」这种编号行；标题行、报名条件、备注都不是步骤。
_STEP_LINE_RE = re.compile(r"^\s*(\d+)\s*[.、]\s*(.+)$")
_REQUIRED_FIELDS = ("id", "title", "reward", "verdict", "reason", "page_text")


def load_seed(path):
    """逐行读取 JSONL 种子集，返回样本列表；空行跳过。"""
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"种子集第 {line_number} 行不是合法 JSON：{exc}") from exc
            missing = [key for key in _REQUIRED_FIELDS if key not in row]
            if missing:
                raise ValueError(f"种子集第 {line_number} 行缺少字段：{', '.join(missing)}")
            if row["verdict"] not in ("do", "abort"):
                raise ValueError(f"种子集第 {line_number} 行 verdict 非法：{row['verdict']!r}")
            rows.append(row)
    return rows


def build_steps(page_text):
    """只取「1. xxx」「1、xxx」这种编号行；标题行、报名条件、备注都不算步骤。

    序号前缀要剥掉：守卫层做的是关键词匹配，序号留在里面不影响判定，但存进
    数据集会污染以后的训练样本。页面原文怎么切成 steps 和守卫层实现一样容易
    出错，所以这个口径由 tests/test_eval_guard.py 锁住。
    """
    steps = []
    for line in page_text.split("\n"):
        match = _STEP_LINE_RE.match(line.strip())
        if match:
            steps.append(match.group(2).strip())
    return steps


def build_bounty(row):
    """把一条种子样本还原为 Bounty；兼容旧字段 restricted_regions（按 allowed 处理）。"""
    reward = row["reward"]
    allowed = row.get("allowed_regions", row.get("restricted_regions", []))
    forbidden = row.get("forbidden_regions", [])
    return Bounty(
        id=row["id"],
        title=row["title"],
        reward=None if reward is None else float(reward),
        steps=build_steps(row["page_text"]),
        allowed_regions=None if allowed is None else list(allowed),
        forbidden_regions=None if forbidden is None else list(forbidden),
    )


def evaluate(rows):
    """逐条调用 check_feasibility 并汇总统计。

    返回的字典包含 JSON 的五个字段，另外带上分子分母方便展示：
    total / verdict_correct / verdict_acc / reason_total / reason_correct /
    do_total / reason_acc / false_positive / false_negative / mismatch。
    归因只统计标注为 abort 的样本；标注为 do 的样本不参与归因统计。
    """
    total = len(rows)
    verdict_correct = 0
    reason_total = 0
    reason_correct = 0
    do_total = 0
    false_positive = []
    false_negative = []
    mismatch = []

    for row in rows:
        verdict, reason = check_feasibility(build_bounty(row))
        label_do = row["verdict"] == "do"
        predicted_do = verdict is Verdict.DO

        if predicted_do == label_do:
            verdict_correct += 1

        if label_do:
            do_total += 1
            if not predicted_do:
                false_negative.append(row["id"])
            continue

        reason_total += 1
        if predicted_do:
            # 标注 abort 却放行，是最危险的假阳性；它没有归因可比较。
            false_positive.append(row["id"])
        elif reason is not None and reason.value == row["reason"]:
            reason_correct += 1
        else:
            mismatch.append({
                "id": row["id"],
                "expected": row["reason"],
                "actual": reason.value if reason is not None else None,
            })

    return {
        "total": total,
        "verdict_correct": verdict_correct,
        "verdict_acc": round(verdict_correct / total, 3) if total else 0.0,
        "reason_total": reason_total,
        "reason_correct": reason_correct,
        "do_total": do_total,
        "reason_acc": round(reason_correct / reason_total, 3) if reason_total else 0.0,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "mismatch": mismatch,
    }


def exit_code(result):
    """假阳性最危险，优先返回 2；其余不完美返回 1；全部正确返回 0。"""
    if result["false_positive"]:
        return 2
    if result["mismatch"] or result["false_negative"]:
        return 1
    return 0


def _percent(numerator, denominator):
    """把比例格式化为百分比；分母为 0 时显示 n/a。"""
    if not denominator:
        return "n/a"
    return f"{numerator / denominator * 100:.1f}%"


def format_report(result):
    """生成人类可读的中文评测报告。"""
    lines = [
        "判定 {}/{} = {} | 归因 {}/{} = {} | FP={} FN={}".format(
            result["verdict_correct"], result["total"],
            _percent(result["verdict_correct"], result["total"]),
            result["reason_correct"], result["reason_total"],
            _percent(result["reason_correct"], result["reason_total"]),
            len(result["false_positive"]), len(result["false_negative"]),
        ),
        f"（归因只统计标注为 abort 的 {result['reason_total']} 条，"
        f"标注为 do 的 {result['do_total']} 条不参与）",
        "",
        "假阳性（标注 abort 但被判 DO，最危险）：",
    ]
    lines.extend(f"  - {sample_id}" for sample_id in result["false_positive"])
    if not result["false_positive"]:
        lines.append("  无")

    lines.append("假阴性（标注 do 但被判 ABORT）：")
    lines.extend(f"  - {sample_id}" for sample_id in result["false_negative"])
    if not result["false_negative"]:
        lines.append("  无")

    lines.append("归因错位：")
    lines.extend(
        f"  {item['id']}: 期望 {item['expected']} 实际 {item['actual']}"
        for item in result["mismatch"]
    )
    if not result["mismatch"]:
        lines.append("  无")
    return "\n".join(lines)


def parse_args(argv=None):
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="评测守卫层在固定种子集上的判定与归因准确率。")
    parser.add_argument(
        "--seed", type=Path, default=DEFAULT_SEED,
        help=f"种子集 JSONL 路径（默认 {DEFAULT_SEED}）",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON，便于 CI 解析。")
    return parser.parse_args(argv)


def main(argv=None):
    """命令行入口：读种子集、跑评测、输出报告并返回退出码。"""
    args = parse_args(argv)
    if not args.seed.is_file():
        print(f"找不到种子集：{args.seed}", file=sys.stderr)
        return 3
    rows = load_seed(args.seed)
    result = evaluate(rows)
    if args.json:
        payload = {
            key: result[key]
            for key in ("verdict_acc", "reason_acc", "false_positive",
                        "false_negative", "mismatch")
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))
    return exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
