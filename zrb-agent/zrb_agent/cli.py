"""命令行入口：默认 dry-run，只有显式 --live 才会提示真实执行。

本单不接真实 adb / 模型：CLI 只解析参数并打印结论，
真正的设备与 plan_fn 接线留到后续执行层单。
"""
from __future__ import annotations

import argparse

from zrb_agent.schema import Bounty


def build_parser() -> argparse.ArgumentParser:
    """构建 argparse；--dry-run 与 --live 互斥且默认 dry-run。"""
    parser = argparse.ArgumentParser(prog="zrb-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="试运行一个众包悬赏")
    run.add_argument("--bounty-id", required=True)
    run.add_argument("--reward", type=float, required=True)
    run.add_argument("--steps", action="append", default=[],
                     help="步骤文本，逗号分隔，也可重复传入")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    mode.add_argument("--live", dest="dry_run", action="store_false")
    run.add_argument("--max-steps", type=int, default=40)
    return parser


def main(argv: list[str] | None = None) -> int:
    """入口；返回退出码。--live 只打印醒目提示就返回，不做交互确认。"""
    args = build_parser().parse_args(argv)
    if args.command != "run":
        return 2
    steps = [part.strip() for raw in args.steps
             for part in raw.split(",") if part.strip()]
    bounty = Bounty(args.bounty_id, args.bounty_id, args.reward, steps)
    if not args.dry_run:
        print("⚠️ LIVE：真实执行会消耗账号名额，确认后才会继续（本次仅提示，未执行）。")
        return 0
    print(f"dry-run：{bounty.id} 赏金 {bounty.reward:.2f} 元，"
          f"共 {len(steps)} 步，最多 {args.max_steps} 个动作；不触碰设备。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
