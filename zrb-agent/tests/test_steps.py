"""步骤结构化：perceive 的 cap/nocap 类型必须一路保留到 Bounty（纯离线）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zrb_agent.guard.ethics import check_ethics  # noqa: E402
from zrb_agent.guard.feasibility import check_feasibility  # noqa: E402
from zrb_agent.perceive import build_page_state, classify_detail_page  # noqa: E402
from zrb_agent.schema import Bounty, Step, Verdict  # noqa: E402

RID = "com.jianzhiku.zhongrenbang:id/"

# 起点读书单的 4 步：1/3 步需要截图证据、2/4 步不需要；第 4 步行内挂着 step_txt。
# 真机 dump 不在仓库里，这里按 #68 实测的 resource-id 契约构造同形状夹具。
SAMPLE_XML = f"""<hierarchy>
  <node bounds="[35,180][1045,260]" text="【起点读书】看书得现金" resource-id="{RID}mission_groupname" />
  <node bounds="[35,280][1045,340]" text="赏金2.13元" resource-id="{RID}mission_money" />
  <node bounds="[35,360][1045,420]" text="打开链接" resource-id="{RID}step_detail_cap" />
  <node bounds="[35,440][1045,500]" text="打开起点读书搜索《剑来》" resource-id="{RID}step_detail_nocap" />
  <node bounds="[35,520][1045,580]" text="截图上传" resource-id="{RID}step_detail_cap" />
  <node bounds="[35,600][1045,660]" text="输入暗号1" resource-id="{RID}step_detail_nocap" />
  <node bounds="[35,680][1045,740]" text="请输入暗号" resource-id="{RID}step_txt" />
  <node bounds="[35,1821][1045,1905]" text="立即报名" resource-id="{RID}btn_add" />
</hierarchy>"""


class StepSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.detail = classify_detail_page(build_page_state(SAMPLE_XML, ".Detail"))
        self.bounty = Bounty("t1", "起点单", 2.13, self.detail["steps"])

    def test_perceive_type_survives_into_bounty(self) -> None:
        """中间层不再把 cap/nocap 拍平成字符串。"""
        self.assertEqual([step.needs_capture for step in self.bounty.steps],
                         [True, False, True, False])
        self.assertEqual(self.bounty.step_texts[1], "打开起点读书搜索《剑来》")

    def test_step_is_text_like_for_planner(self) -> None:
        self.assertEqual(f"当前步骤：{self.bounty.steps[0]}", "当前步骤：打开链接")

    def test_guards_accept_structured_steps(self) -> None:
        """守卫层只读原文：结构化步骤与旧字符串步骤判定必须一致，且不 TypeError。"""
        for texts in (["截图上传"], ["点签到"], ["打开支付宝"]):
            plain = Bounty("t", "t", 1.0, texts, [], [])
            structured = Bounty("t", "t", 1.0,
                                [{"text": text, "type": "cap"} for text in texts], [], [])
            self.assertEqual(check_feasibility(plain), check_feasibility(structured))
            self.assertEqual(check_ethics(plain), check_ethics(structured))
        self.assertEqual(check_feasibility(Bounty("t", "t", 1.0, ["截图上传"], [], []))[0],
                         Verdict.DO)

    def test_legacy_strings_and_roundtrip(self) -> None:
        bounty = Bounty("t1", "旧数据", 1.0, ["截图上传"])
        self.assertEqual(bounty.steps, [Step("截图上传")])
        self.assertFalse(bounty.steps[0].needs_capture)
        self.assertEqual(Bounty.from_dict(bounty.to_dict()), bounty)

    def test_dict_fields_map_to_step(self) -> None:
        step = Step.from_value({"text": "输入暗号", "type": "nocap",
                                "has_text_input": True, "input_hint": "请输入暗号"})
        self.assertEqual(step, Step("输入暗号", False, True, "请输入暗号"))
        self.assertTrue(Step.from_value({"text": "截图", "type": "cap"}).needs_capture)
        with self.assertRaises(TypeError):
            Step.from_value(123)

    def test_steps_incomplete_survives_structured_steps(self) -> None:
        preview = Bounty("t1", "预览", 2.13, self.detail["steps"][:1], [], [],
                         steps_incomplete=True)
        self.assertTrue(preview.steps_incomplete)
        self.assertEqual(check_feasibility(preview)[0], Verdict.DEFERRED)


if __name__ == "__main__":
    unittest.main()