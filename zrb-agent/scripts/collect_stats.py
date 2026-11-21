#!/usr/bin/env python3
"""统计 ledger jsonl：打印轨迹数据集概况，可选写出 stats.json。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zrb_agent.dataset import entries_to_samples, load_jsonl, summarize  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="统计 zrb-agent 轨迹数据集")
    parser.add_argument("ledger", help="ledger.py 产出的 jsonl 文件")
    parser.add_argument("--out", help="把统计结果写成 json 文件")
    parser.add_argument("--bounty-id", help="悬赏 id，默认取 ledger 文件名")
    args = parser.parse_args(argv)
    entries, errors = load_jsonl(args.ledger)
    bounty_id = args.bounty_id or Path(args.ledger).stem
    stats = summarize(entries_to_samples(entries, bounty_id))
    print(f"总样本数: {stats['total']}\n涉及悬赏数: {stats['unique_bounties']}"
          f"\n成功率: {stats['success_rate']:.1%}"
          f"\nASK_HUMAN 占比: {stats['fallback_ratio']:.1%}\n各动作分布:")
    for action, count in sorted(stats["by_action"].items()):
        print(f"  {action}: {count}")
    if errors:
        print(f"坏行数: {len(errors)}")
        print("\n".join(f"  - {reason}" for reason in errors[:3]))
    if args.out:
        Path(args.out).write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
