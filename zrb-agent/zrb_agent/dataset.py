"""轨迹数据集工具：把 ledger 产出的 jsonl 转成可训练样本，并做统计（纯标准库）。"""
import json
import random
from dataclasses import asdict, dataclass

@dataclass
class TrajectorySample:
    """一条轨迹样本：某一屏的可见内容 + 动作 + 结果。"""
    bounty_id: str
    step_index: int
    page_texts: list[str]
    page_elements: list[dict]
    screenshot: str | None
    action: str
    params: dict
    expect: str
    success: bool
    label: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TrajectorySample":
        """从字典还原样本，缺失的页面字段用空值。"""
        return cls(
            data["bounty_id"], int(data["step_index"]),
            list(data.get("page_texts") or []), list(data.get("page_elements") or []),
            data.get("screenshot"), data["action"], dict(data.get("params") or {}),
            data["expect"], bool(data["success"]), data.get("label"))

def load_jsonl(path: str) -> tuple[list[dict], list[str]]:
    """逐行解析 jsonl；坏行跳过不抛异常，返回 (成功条目, 失败原因列表)。"""
    entries, errors = [], []
    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"第 {lineno} 行: JSON 解析失败: {exc}")
                continue
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                errors.append(f"第 {lineno} 行: schema_version 缺失或不为 1")
                continue
            entries.append(data)
    return entries, errors

def entries_to_samples(entries: list[dict], bounty_id: str) -> list[TrajectorySample]:
    """把 ledger 条目转成样本；旧格式没有页面字段时用空列表。"""
    return [TrajectorySample(
        bounty_id, int(entry.get("step", 0)),
        list(entry.get("page_texts") or []), list(entry.get("page_elements") or []),
        entry.get("screenshot") or entry.get("screenshot_prefix"),
        str(entry.get("action", "")), dict(entry.get("params") or {}),
        str(entry.get("expect", "")), bool(entry.get("success", False)),
        entry.get("label")) for entry in entries]

def split_by_bounty(samples: list[TrajectorySample],
                    ratios: tuple[float, float, float] = (0.8, 0.1, 0.1),
                    seed: int = 42) -> tuple[list, list, list]:
    """按 bounty_id 整组划分 train/val/test。

    同一悬赏的步骤共享页面与流程，按单条样本划分会让同一悬赏同时进入训练集
    和验证/测试集，造成数据泄漏；故先按悬赏分组，再打乱、按比例切分，seed 可复现。
    """
    groups: dict[str, list[TrajectorySample]] = {}
    for sample in samples:
        groups.setdefault(sample.bounty_id, []).append(sample)
    bounty_ids = list(groups)
    random.Random(seed).shuffle(bounty_ids)
    total = float(sum(ratios))
    n_train = int(len(bounty_ids) * ratios[0] / total)
    n_val = int(len(bounty_ids) * (ratios[0] + ratios[1]) / total)
    parts = (bounty_ids[:n_train], bounty_ids[n_train:n_val], bounty_ids[n_val:])
    return tuple([s for bid in part for s in groups[bid]] for part in parts)

def summarize(samples: list[TrajectorySample]) -> dict:
    """统计总数、动作分布、成功率、悬赏数与 ASK_HUMAN 占比。"""
    total = len(samples)
    by_action: dict[str, int] = {}
    for sample in samples:
        by_action[sample.action] = by_action.get(sample.action, 0) + 1
    return {
        "total": total, "by_action": by_action,
        "success_rate": sum(s.success for s in samples) / total if total else 0.0,
        "unique_bounties": len({s.bounty_id for s in samples}),
        "fallback_ratio": by_action.get("ASK_HUMAN", 0) / total if total else 0.0}

def export_feasibility_set(samples: list[TrajectorySample], path: str) -> int:
    """只导出带 label 的样本为 {"text", "label"} jsonl，返回导出条数。"""
    labeled = [s for s in samples if s.label is not None]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps({"text": "\n".join(s.page_texts),
                                 "label": s.label}, ensure_ascii=False) + "\n"
                     for s in labeled)
    return len(labeled)
