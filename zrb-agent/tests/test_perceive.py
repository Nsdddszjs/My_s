"""感知层单元测试：全部使用内联最小 XML，不依赖真机或截图文件。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zrb_agent.perceive import (  # noqa: E402
    UiElement,
    build_page_state,
    classify_detail_page,
    find_elements,
    has_approved_entry,
    is_submit_success,
    parse_ui_xml,
    tap_target,
)

BASE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,1920]" class="android.widget.FrameLayout" text="" resource-id="">
    <node bounds="[35,100][1045,200]" text="赏金任务" resource-id="item_title" />
    <node bounds="[35,1821][1045,1905]" text="立即报名" resource-id="btn_apply" />
  </node>
</hierarchy>"""

DETAIL_XML = """<hierarchy>
  <node bounds="[35,100][1045,200]" text="赏金 2.13元" resource-id="bb_money" />
  <node bounds="[35,300][1045,400]" text="报名条件" resource-id="bb_title" />
  <node bounds="[35,1800][1045,1900]" text="立即报名" resource-id="btn_apply" />
</hierarchy>"""

ENTITY_XML = (
    '<hierarchy><node bounds="[0,0][100,100]" '
    'text="A&amp;B" resource-id="x" /></hierarchy>'
)

SUCCESS_XML = """<hierarchy>
  <node bounds="[0,0][1080,200]" text="提交成功" resource-id="tv_title" />
  <node bounds="[0,200][1080,300]" text="等待悬赏主审核" resource-id="tv_desc" />
  <node bounds="[0,300][1080,400]" text="24小时内" resource-id="tv_tip" />
</hierarchy>"""

APPROVED_XML = """<hierarchy>
  <node bounds="[0,0][1080,100]" text="已通过" resource-id="tab_approved" />
  <node bounds="[0,100][1080,200]" text="悬赏 ID：378735" resource-id="item_bounty_id" />
  <node bounds="[0,200][1080,300]" text="赏金已发放" resource-id="item_state" />
</hierarchy>"""


class PerceiveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.elements = parse_ui_xml(BASE_XML)

    def test_parse_ui_xml_drops_container(self) -> None:
        self.assertEqual(len(self.elements), 2)
        self.assertEqual([e.ref for e in self.elements], ["e0", "e1"])

    def test_bounds_and_center(self) -> None:
        self.assertEqual(self.elements[1].bounds, (35, 1821, 1045, 1905))
        self.assertEqual(self.elements[1].center, (540, 1863))

    def test_norm_center(self) -> None:
        el = UiElement("e0", "x", "", (0, 0, 1080, 1920), (540, 960))
        self.assertEqual(el.norm_center(1080, 1920), (0.5, 0.5))

    def test_find_elements_contains(self) -> None:
        self.assertEqual(len(find_elements(self.elements, contains="报名")), 1)

    def test_tap_target_hit(self) -> None:
        self.assertEqual(tap_target(self.elements, contains="立即报名"), (540, 1863))

    def test_tap_target_miss(self) -> None:
        self.assertIsNone(tap_target(self.elements, contains="不存在的东西"))

    def test_classify_detail_page(self) -> None:
        result = classify_detail_page(build_page_state(DETAIL_XML, ".Detail"))
        self.assertTrue(result["is_detail"])
        self.assertEqual(result["reward"], 2.13)

    def test_unescape_entities(self) -> None:
        self.assertEqual(parse_ui_xml(ENTITY_XML)[0].text, "A&B")
        self.assertEqual(build_page_state(ENTITY_XML, ".Main").texts, ["A&B"])


class SubmitSuccessTest(unittest.TestCase):
    """提交成功的可验证闭环：toast 不算，活动变更/成功页/已通过列表才算。"""

    def test_toast_only_is_not_success(self) -> None:
        page = build_page_state(BASE_XML, ".Detail")
        page.texts.append("有内容没有填写...")  # 700ms toast，页面本身不变
        self.assertFalse(is_submit_success(
            "mCurrentFocus=Window{abc u0 com.jianzhiku.activity.BountyDetail}", page))

    def test_mission_submit_success_activity(self) -> None:
        page = build_page_state(BASE_XML, ".Detail")
        self.assertTrue(is_submit_success(
            "mCurrentFocus=Window{abc u0 com.jianzhiku.activity.MissionSubmitSuccess}",
            page))

    def test_success_page_text_without_activity_change(self) -> None:
        page = build_page_state(SUCCESS_XML, ".Main")
        self.assertTrue(is_submit_success("mCurrentFocus=Window{abc u0 .Main}", page))

    def test_activity_from_page_state_is_also_accepted(self) -> None:
        page = build_page_state(BASE_XML, "com.jianzhiku.activity.MissionSubmitSuccess")
        self.assertTrue(is_submit_success("", page))

    def test_approved_entry_requires_approved_tab_and_bounty_id(self) -> None:
        page = build_page_state(APPROVED_XML, ".Mine")
        self.assertTrue(has_approved_entry(page, "378735"))
        self.assertFalse(has_approved_entry(page, "999999"))

    def test_pending_entry_is_not_approved(self) -> None:
        page = build_page_state(
            BASE_XML.replace("赏金任务", "审核中"), ".Mine")
        page.texts.extend(["悬赏 ID：378735", "已提交"])
        self.assertFalse(has_approved_entry(page, "378735"))

    def test_empty_bounty_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            has_approved_entry(build_page_state(APPROVED_XML, ".Mine"), " ")


if __name__ == "__main__":
    unittest.main()
