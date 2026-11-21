"""轨迹数据集工具单元测试：只用 tempfile 与内联数据，不依赖真实 ledger。"""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zrb_agent.dataset import (  # noqa: E402
    TrajectorySample, entries_to_samples, export_feasibility_set,
    load_jsonl, split_by_bounty, summarize)

def make_sample(bounty_id, step=0, action="TAP", success=True, label=None, texts=None):
    return TrajectorySample(
        bounty_id, step, ["页面"] if texts is None else texts,
        [{"ref": "e0", "text": "按钮", "resource_id": "btn", "center": [1, 2]}],
        "shots/1.png", action, {"x": 1}, "页面变化", success, label)

class DatasetTest(unittest.TestCase):
    def test_load_jsonl(self):
        good = json.dumps({"schema_version": 1, "step": 1, "action": "TAP"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            path.write_text(good + "\n{坏 json\n" + json.dumps({"step": 2}) + "\n")
            entries, errors = load_jsonl(str(path))
        self.assertEqual((len(entries), len(errors)), (1, 2))

    def test_old_format_and_roundtrip(self):
        old = entries_to_samples([{"step": 3, "action": "ASK_HUMAN"}], "b1")[0]
        self.assertEqual((old.bounty_id, old.step_index, old.page_texts,
                          old.page_elements, old.screenshot), ("b1", 3, [], [], None))
        sample = make_sample("b1", label="do")
        self.assertEqual(TrajectorySample.from_dict(sample.to_dict()), sample)

    def test_split_by_bounty_no_leak_and_reproducible(self):
        samples = [make_sample(f"b{i}", j) for i in range(10) for j in range(3)]
        train, val, test = split_by_bounty(samples)
        sets = [{s.bounty_id for s in part} for part in (train, val, test)]
        self.assertFalse(sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])
        self.assertEqual(len(set().union(*sets)), 10)
        self.assertEqual((len(train), len(val), len(test)), (24, 3, 3))
        self.assertEqual(split_by_bounty(samples, seed=7),
                         split_by_bounty(samples, seed=7))

    def test_summarize(self):
        stats = summarize([
            make_sample("b1", action="TAP", success=True),
            make_sample("b1", action="TAP", success=False),
            make_sample("b2", action="ASK_HUMAN", success=False),
            make_sample("b2", action="FINISH", success=True)])
        self.assertEqual((stats["total"], stats["success_rate"], stats["fallback_ratio"],
                          stats["unique_bounties"]), (4, 0.5, 0.25, 2))
        self.assertEqual(stats["by_action"], {"TAP": 2, "ASK_HUMAN": 1, "FINISH": 1})
        self.assertEqual(summarize([])["success_rate"], 0.0)

    def test_export_feasibility_set(self):
        samples = [make_sample("b1", label="do", texts=["甲", "乙"]),
                   make_sample("b1", label=None), make_sample("b2", label="abort:X")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.jsonl"
            self.assertEqual(export_feasibility_set(samples, str(path)), 2)
            rows = [json.loads(x) for x in path.read_text().splitlines()]
        self.assertEqual(rows, [{"text": "甲\n乙", "label": "do"},
                                {"text": "页面", "label": "abort:X"}])

if __name__ == "__main__":
    unittest.main()
