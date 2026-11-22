"""感知层单元测试：内联真机 dump 片段，不依赖真机或截图文件。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zrb_agent.perceive import (  # noqa: E402
    UiElement,
    build_page_state,
    classify_detail_page,
    extract_allowed_regions,
    extract_forbidden_regions,
    find_elements,
    has_approved_entry,
    is_submit_success,
    parse_ui_xml,
    tap_target,
)

RID = "com.jianzhiku.zhongrenbang:id/"

BASE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,1920]" class="android.widget.FrameLayout" text="" resource-id="">
    <node bounds="[35,100][1045,200]" text="赏金任务" resource-id="item_title" />
    <node bounds="[35,1821][1045,1905]" text="立即报名" resource-id="btn_apply" />
  </node>
</hierarchy>"""

DETAIL_XML = f"""<hierarchy>
  <node bounds="[35,180][1045,260]" text="【填问卷】" resource-id="{RID}mission_groupname" />
  <node bounds="[35,280][1045,340]" text="赏金2.13元" resource-id="{RID}mission_money" />
  <node bounds="[35,400][1045,460]" text="填写" resource-id="{RID}mission_detail" />
  <node bounds="[35,1821][1045,1905]" text="立即报名" resource-id="{RID}btn_add" />
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

# 378735G 详情页真机 dump 的完整 4 步形态。resource-id、标题/赏金/限制/步骤正文
# 逐字来自真机（#37 与 #44 记录），仓库外没有原始 XML 文件，故在此内联；
# step_txt 的 hint 取自 planner 记录的同一 App 真机输入框。
FOUR_STEP_XML = f"""<hierarchy rotation="0">
  <node bounds="[35,525][539,584]" text="【378735G畅享套餐h...】" resource-id="{RID}mission_groupname" />
  <node bounds="[554,525][642,584]" text="简单" resource-id="{RID}mission_title" />
  <node bounds="[800,630][1045,724]" text="赏2.13元" resource-id="{RID}mission_money" />
  <node bounds="[70,800][816,858]" text="填写" resource-id="{RID}mission_detail" />
  <node bounds="[70,1100][1045,1163]" text="报名条件/限制" resource-id="{RID}view_limit" />
  <node bounds="[70,1163][1045,1221]" text="北京，西藏这两个手机号地区不能做" resource-id="{RID}limite" />
  <node bounds="[85,1409][143,1461]" text="1" resource-id="{RID}setpcount_nocap" />
  <node bounds="[158,1386][1030,1821]" text="禁止&#10;地区：新疆，甘肃，海南，云南，北京，上海，澳门特别行政区、宁夏回族自治区、内蒙古自治区、香港特别行政区、西藏自治区、台湾省、青海省，湖南湘西土家族苗族自治州，吉林朝鲜族自治州，手机号跟ip是这些地区的不要做" resource-id="{RID}step_detail_nocap" />
  <node bounds="[85,1855][143,1907]" text="2" resource-id="{RID}setpcount_cap" />
  <node bounds="[158,1830][1030,1940]" text="浏览器，输入ip，搜索后截图" resource-id="{RID}step_detail_cap" />
  <node bounds="[85,1950][143,2002]" text="3" resource-id="{RID}setpcount_nocap" />
  <node bounds="[158,1940][1030,2050]" text="打开链接填写，姓名随意填写（姓名看着像人名）" resource-id="{RID}step_detail_nocap" />
  <node bounds="[158,2060][1030,2100]" text="按要求输入文字" resource-id="{RID}step_txt" />
  <node bounds="[85,2110][143,2162]" text="4" resource-id="{RID}setpcount_cap" />
  <node bounds="[158,2100][1030,2210]" text="填写完成后截图" resource-id="{RID}step_detail_cap" />
  <node bounds="[35,2221][1045,2305]" text="立即报名" resource-id="{RID}btn_add" />
  <node bounds="[35,2260][1045,2305]" text="打开链接" resource-id="{RID}main_btn" />
</hierarchy>"""

# 报名后同页按钮变成「提交（剩余…分钟）」；标题/赏金还在，main_btn 挂链接。
ENROLLED_XML = f"""<hierarchy>
  <node bounds="[35,180][1045,260]" text="【378735G畅享套餐h...】" resource-id="{RID}mission_groupname" />
  <node bounds="[35,280][1045,340]" text="赏2.13元" resource-id="{RID}mission_money" />
  <node bounds="[158,1400][1030,1500]" text="浏览器，输入ip，搜索后截图" resource-id="{RID}step_detail_cap" />
  <node bounds="[35,1821][1045,1905]" text="提交（剩余5分钟）" resource-id="{RID}btn_add" />
  <node bounds="[35,1960][1045,2040]" text="打开链接" resource-id="{RID}main_btn" />
</hierarchy>"""

# 滚一屏后标题被回收，只剩步骤、报名按钮与限制字段（真机形状）。
SCROLLED_XML = f"""<hierarchy>
  <node bounds="[85,215][143,267]" text="1" resource-id="{RID}setpcount_nocap" />
  <node bounds="[158,192][1030,764]" text="禁止&#10;地区：新疆，甘肃，海南，云南，北京，上海…手机号跟ip是这些地区的不要做" resource-id="{RID}step_detail_nocap" />
  <node bounds="[85,805][143,857]" text="2" resource-id="{RID}setpcount_cap" />
  <node bounds="[158,782][1030,892]" text="浏览器，输入ip，搜索后截图" resource-id="{RID}step_detail_cap" />
  <node bounds="[158,1814][1030,1821]" text="打开链接填写，姓名随意填写（姓名看着像人名）" resource-id="{RID}step_detail_nocap" />
  <node bounds="[35,1821][1045,1905]" text="立即报名" resource-id="{RID}btn_add" />
</hierarchy>"""

# 序号被回收，只剩步骤正文：仍要按出现顺序补号，不能丢步骤。
STEPS_WITHOUT_COUNTER_XML = f"""<hierarchy>
  <node bounds="[35,100][1045,160]" text="【红果免费短剧】" resource-id="{RID}mission_groupname" />
  <node bounds="[158,550][1030,660]" text="复制链接前往浏览器" resource-id="{RID}step_detail_nocap" />
  <node bounds="[158,670][1030,780]" text="再依次复制口令打开红果短剧搜索" resource-id="{RID}step_detail_nocap" />
  <node bounds="[158,790][1030,900]" text="助力所有，再右下角我的截图" resource-id="{RID}step_detail_nocap" />
</hierarchy>"""

NUMBERED_STEP_XML = f"""<hierarchy>
  <node bounds="[35,100][1045,200]" text="378735G畅享套餐h" resource-id="{RID}mission_groupname" />
  <node bounds="[35,580][1045,680]" text="1.禁止地区：新疆 甘肃 云南" resource-id="{RID}step_detail_nocap" />
  <node bounds="[35,1800][1045,1900]" text="立即报名" resource-id="{RID}btn_add" />
</hierarchy>"""


def classify(xml: str, activity: str = ".Detail") -> dict:
    return classify_detail_page(build_page_state(xml, activity))


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

    def test_hall_page_is_not_detail(self) -> None:
        self.assertFalse(classify(BASE_XML, ".Main")["is_detail"])

    def test_classify_detail_page_fields(self) -> None:
        result = classify(DETAIL_XML)
        self.assertTrue(result["is_detail"])
        self.assertEqual(result["title"], "【填问卷】")
        self.assertEqual(result["reward"], 2.13)
        self.assertEqual(result["detail"], "填写")
        self.assertEqual(result["primary_button"], "立即报名")
        self.assertIsNone(result["link_button"])

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
class RealDetailPageTest(unittest.TestCase):
    """378735G 真机详情页：字段与步骤类型。"""

    def test_title_group_and_title_are_combined(self) -> None:
        data = classify(FOUR_STEP_XML, ".NewMissionStart")
        self.assertIn("378735G畅享套餐h", data["title"])
        self.assertIn("简单", data["title"])

    def test_four_steps_with_types(self) -> None:
        steps = classify(FOUR_STEP_XML)["steps"]
        self.assertEqual([step["index"] for step in steps], [1, 2, 3, 4])
        self.assertEqual([step["type"] for step in steps],
                         ["nocap", "cap", "nocap", "cap"])
        self.assertEqual(steps[1]["text"], "浏览器，输入ip，搜索后截图")
        self.assertEqual(steps[3]["text"], "填写完成后截图")

    def test_text_input_hint(self) -> None:
        data = classify(FOUR_STEP_XML)
        self.assertTrue(data["has_text_input"])
        self.assertEqual(data["text_input_hint"], "按要求输入文字")

    def test_primary_button_text(self) -> None:
        self.assertEqual(classify(FOUR_STEP_XML)["primary_button"], "立即报名")
        enrolled = classify(ENROLLED_XML)
        self.assertEqual(enrolled["primary_button"], "提交（剩余5分钟）")
        self.assertEqual(enrolled["link_button"], "打开链接")

    def test_scrolled_page_still_detected_without_fake_reward(self) -> None:
        data = classify(SCROLLED_XML)
        self.assertTrue(data["is_detail"])
        self.assertIsNone(data["title"])
        self.assertIsNone(data["reward"])
        self.assertEqual([step["type"] for step in data["steps"]],
                         ["nocap", "cap", "nocap"])
        self.assertFalse(data["has_text_input"])

    def test_steps_without_counter_keep_order(self) -> None:
        steps = classify(STEPS_WITHOUT_COUNTER_XML)["steps"]
        self.assertEqual([step["index"] for step in steps], [1, 2, 3])
        self.assertEqual(steps[0]["text"], "复制链接前往浏览器")
        self.assertTrue(all(step["type"] == "nocap" for step in steps))

    def test_numbered_step_text_is_stripped(self) -> None:
        data = classify(NUMBERED_STEP_XML)
        self.assertEqual([step["text"] for step in data["steps"]],
                         ["禁止地区：新疆 甘肃 云南"])
        self.assertNotIn("378735G畅享套餐h", [step["text"] for step in data["steps"]])


class RegionExtractionTest(unittest.TestCase):
    def test_forbidden_regions_from_real_dump(self) -> None:
        data = classify(FOUR_STEP_XML)
        forbidden = data["forbidden_regions_hint"]
        self.assertIsNotNone(forbidden)
        for region in ("新疆", "甘肃", "海南", "云南", "北京", "上海", "西藏"):
            self.assertIn(region, forbidden)
        self.assertNotIn("手机号跟ip是这些地区的不要做", forbidden)
        self.assertEqual(data["allowed_regions_hint"], [])

    def test_allowed_regions_from_limite(self) -> None:
        xml = f"""<hierarchy>
          <node bounds="[0,0][10,10]" text="有IP控制，仅限广州/东莞/南宁/武汉/长沙/南昌/宁波" resource-id="{RID}limite" />
          <node bounds="[0,20][10,30]" text="立即报名" resource-id="{RID}btn_add" />
        </hierarchy>"""
        data = classify(xml)
        self.assertEqual(data["allowed_regions_hint"],
                         ["广州", "东莞", "南宁", "武汉", "长沙", "南昌", "宁波"])
        self.assertEqual(data["forbidden_regions_hint"], [])

    def test_forbidden_regions_from_condition_line(self) -> None:
        xml = f"""<hierarchy>
          <node bounds="[0,0][10,10]" text="北京、西藏 两个手机号地区不能做" resource-id="{RID}limite" />
          <node bounds="[0,20][10,30]" text="立即报名" resource-id="{RID}btn_add" />
        </hierarchy>"""
        self.assertEqual(classify(xml)["forbidden_regions_hint"], ["北京", "西藏"])

    def test_explicit_no_limit_is_known_empty(self) -> None:
        xml = f"""<hierarchy>
          <node bounds="[0,0][10,10]" text="无" resource-id="{RID}limite" />
          <node bounds="[0,20][10,30]" text="立即报名" resource-id="{RID}btn_add" />
        </hierarchy>"""
        data = classify(xml)
        self.assertEqual(data["allowed_regions_hint"], [])
        self.assertEqual(data["forbidden_regions_hint"], [])

    def test_unknown_is_none_not_empty(self) -> None:
        """没有限制字段时返回 None，不能用 [] 冒充「确定无地区限制」。"""
        data = classify(BASE_XML, ".Main")
        self.assertIsNone(data["allowed_regions_hint"])
        self.assertIsNone(data["forbidden_regions_hint"])

    def test_placeholder_limit_is_unknown(self) -> None:
        xml = f"""<hierarchy>
          <node bounds="[0,0][10,10]" text="！" resource-id="{RID}limite" />
          <node bounds="[0,20][10,30]" text="立即报名" resource-id="{RID}btn_add" />
        </hierarchy>"""
        data = classify(xml)
        self.assertIsNone(data["allowed_regions_hint"])
        self.assertIsNone(data["forbidden_regions_hint"])

    def test_unparsed_region_concept_is_unknown(self) -> None:
        """提到 IP 控制却解析不出名单时，宁可未知，也不报「确定无」。"""
        xml = f"""<hierarchy>
          <node bounds="[0,0][10,10]" text="有IP控制" resource-id="{RID}limite" />
          <node bounds="[0,20][10,30]" text="立即报名" resource-id="{RID}btn_add" />
        </hierarchy>"""
        data = classify(xml)
        self.assertIsNone(data["allowed_regions_hint"])
        self.assertIsNone(data["forbidden_regions_hint"])

    def test_helpers_extract_expected_lists(self) -> None:
        self.assertEqual(
            extract_forbidden_regions(
                ["禁止地区：新疆，甘肃…手机号跟ip是这些地区的不要做"]),
            ["新疆", "甘肃"])
        self.assertEqual(extract_allowed_regions(["必须到以下地区：北京、上海"]),
                         ["北京", "上海"])
        self.assertEqual(extract_allowed_regions(["仅限泰国IP"]), ["泰国"])
        self.assertEqual(extract_allowed_regions(["仅限新用户"]), [])


class ContentDescPerceiveTest(unittest.TestCase):
    """验证 parse_ui_xml 对 content-desc 节点的提取与查询能力 (#70)。"""

    PRIVACY_DIALOG_XML = """<hierarchy>
      <node bounds="[0,0][1080,1920]" class="android.widget.FrameLayout" text="" resource-id="">
        <node bounds="[115,441][276,603]" class="android.view.View" text="" content-desc="个人信息保护指引 " resource-id="" />
        <node bounds="[115,1383][1325,1516]" class="android.view.View" text="" content-desc="同意" clickable="true" resource-id="" />
        <node bounds="[115,1550][1325,1680]" class="android.view.View" text="" content-desc="不同意" clickable="true" resource-id="" />
      </node>
    </hierarchy>"""

    LOGIN_WALL_XML = """<hierarchy>
      <node bounds="[0,0][1080,1920]" class="android.widget.FrameLayout" text="" resource-id="">
        <node bounds="[50,100][1030,200]" class="android.view.View" text="" content-desc="手机号一键登录" resource-id="" />
        <node bounds="[50,250][1030,350]" class="android.view.View" text="" content-desc="发送验证码" clickable="true" resource-id="" />
        <node bounds="[50,400][1030,500]" class="android.view.View" text="其他登录方式" content-desc="" resource-id="tv_other" />
      </node>
    </hierarchy>"""

    def test_privacy_dialog_content_desc_elements(self) -> None:
        elements = parse_ui_xml(self.PRIVACY_DIALOG_XML)
        self.assertEqual(len(elements), 3)
        self.assertEqual(elements[0].desc, "个人信息保护指引 ")
        self.assertEqual(elements[1].text, "同意")
        self.assertEqual(elements[1].desc, "同意")
        self.assertEqual(elements[2].text, "不同意")
        self.assertEqual(elements[2].desc, "不同意")

    def test_tap_target_content_desc(self) -> None:
        elements = parse_ui_xml(self.PRIVACY_DIALOG_XML)
        target = tap_target(elements, text="同意")
        self.assertEqual(target, (720, 1449))

    def test_page_state_texts_includes_desc(self) -> None:
        state = build_page_state(self.LOGIN_WALL_XML, ".LoginActivity")
        self.assertIn("手机号一键登录", state.texts)
        self.assertIn("发送验证码", state.texts)
        self.assertIn("其他登录方式", state.texts)

    def test_find_elements_by_desc_and_contains(self) -> None:
        elements = parse_ui_xml(self.LOGIN_WALL_XML)
        self.assertEqual(len(find_elements(elements, contains="验证码")), 1)
        self.assertEqual(find_elements(elements, text="发送验证码")[0].desc, "发送验证码")


if __name__ == "__main__":
    unittest.main()