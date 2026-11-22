"""执行账本：把每一步动作与结果落成 jsonl。

这个 jsonl 就是日后训练数据的原始素材（trajectory），
字段名与含义不要随意改；每行都带 schema_version 便于以后演进。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class LedgerEntry:
    """一步执行记录；字段即 trajectory 的 schema。"""

    step: int
    thought: str
    action: str
    params: dict
    expect: str
    observed: str
    success: bool
    screenshot_prefix: str | None = None


class Ledger:
    """只追加的内存账本，可导出为带版本号的 jsonl。"""

    SCHEMA_VERSION = 1

    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def append(self, entry: LedgerEntry) -> None:
        self.entries.append(entry)

    def to_jsonl(self) -> str:
        """每行一个 JSON；中文不转义，便于人读与后续训练。"""
        lines = [
            json.dumps({"schema_version": self.SCHEMA_VERSION, **asdict(entry)},
                       ensure_ascii=False)
            for entry in self.entries
        ]
        return "\n".join(lines)

    def save(self, path: str | Path) -> None:
        """写入文件；空账本写空文件。"""
        Path(path).write_text(self.to_jsonl(), encoding="utf-8")
