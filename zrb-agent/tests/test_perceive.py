"""感知层单元测试：全部使用内联最小 XML，不依赖真机或截图文件。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zrb_agent.guard.feasibility import check_feasibility  # noqa: E402
from zrb_agent.perceive import (  # noqa: E402
    UiElement,
    build_page_state,
    classify_detail_page,
    extract_regions,
    find_elements,
    parse_ui_xml,
    tap_target,
)
from zrb_agent.schema import AbortReason, Bounty, Verdict  # noqa: E402

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
  <node bounds="[35,1800][1045,1900]" text="立即报名" resource-id="btn_add" />
</hierarchy>"""

ENTITY_XML = (
    '<hierarchy><node bounds="[0,0][100,100]" '
    'text="A&amp;B" resource-id="x" /></hierarchy>'
)

# 真实详情页顶部（378735G 畅享套餐h，赏 2.13 元）。资源 id 与文本按真机 dump
# 内联，滚动前的标题/赏金/计数节点都在；测试不依赖仓库外的语料路径。
REAL_TOP_XML = """<hierarchy rotation="0">
  <node bounds="[35,525][539,584]" text="【378735G畅享套餐h...】" resource-id="com.jianzhiku.zhongrenbang:id/mission_groupname" />
  <node bounds="[554,525][642,584]" text="简单" resource-id="com.jianzhiku.zhongrenbang:id/mission_title" />
  <node bounds="[800,630][1045,724]" text="赏2.13元" resource-id="com.jianzhiku.zhongrenbang:id/mission_money" />
  <node bounds="[70,800][816,858]" text="填写" resource-id="com.jianzhiku.zhongrenbang:id/mission_detail" />
  <node bounds="[193,923][253,970]" text="248" resource-id="com.jianzhiku.zhongrenbang:id/checkleft" />
  <node bounds="[70,930][253,970]" text="6分钟" resource-id="com.jianzhiku.zhongrenbang:id/avgtime" />
  <node bounds="[500,930][700,970]" text="1931人" resource-id="com.jianzhiku.zhongrenbang:id/num_count" />
  <node bounds="[700,930][900,970]" text="5分钟" resource-id="com.jianzhiku.zhongrenbang:id/avgreview" />
  <node bounds="[900,930][1045,970]" text="24小时内" resource-id="com.jianzhiku.zhongrenbang:id/timeleft" />
  <node bounds="[70,1163][1045,1221]" text="北京，西藏这两个手机号地区不能做" resource-id="com.jianzhiku.zhongrenbang:id/limite" />
  <node bounds="[85,1409][143,1461]" text="1" resource-id="com.jianzhiku.zhongrenbang:id/setpcount_nocap" />
  <node bounds="[158,1386][1030,1821]" text="禁止&#10;地区：新疆，甘肃，海南，云南，北京，上海，澳门特别行政区、宁夏回族自治区、内蒙古自治区、香港特别行政区、西藏自治区、台湾省、青海省，湖南湘西土家族苗族自治州，吉林朝鲜族自治州，手机号跟ip是这些地区的不要做" resource-id="com.jianzhiku.zhongrenbang:id/step_detail_nocap" />
  <node bounds="[85,1855][143,1907]" text="2" resource-id="com.jianzhiku.zhongrenbang:id/setpcount_cap" />
  <node bounds="[158,1830][1030,1940]" text="浏览器，输入ip，搜索后截图" resource-id="com.jianzhiku.zhongrenbang:id/step_detail_cap" />
  <node bounds="[158,1990][1030,2050]" text="打开链接填写，姓名随意填写（姓名看着像人名）" resource-id="com.jianzhiku.zhongrenbang:id/step_detail_nocap" />
  <node bounds="[35,1821][1045,1905]" text="立即报名" resource-id="com.jianzhiku.zhongrenbang:id/btn_add" />
</hierarchy>"""

# 同一页面往下滚一屏：标题与赏金被回收出屏幕，只剩步骤和报名按钮。
REAL_SCROLLED_XML = """<hierarchy rotation="0">
  <node bounds="[85,215][143,267]" text="1" resource-id="com.jianzhiku.zhongrenbang:id/setpcount_nocap" />
  <node bounds="[158,192][1030,764]" text="禁止&#10;地区：新疆，甘肃，海南，云南，北京，上海…手机号跟ip是这些地区的不要做" resource-id="com.jianzhiku.zhongrenbang:id/step_detail_nocap" />
  <node bounds="[85,805][143,857]" text="2" resource-id="com.jianzhiku.zhongrenbang:id/setpcount_cap" />
  <node bounds="[158,782][1030,892]" text="浏览器，输入ip，搜索后截图" resource-id="com.jianzhiku.zhongrenbang:id/step_detail_cap" />
  <node bounds="[158,1814][1030,1821]" text="打开链接填写，姓名随意填写（姓名看着像人名）" resource-id="com.jianzhiku.zhongrenbang:id/step_detail_nocap" />
  <node bounds="[35,1821][1045,1905]" text="立即报名" resource-id="com.jianzhiku.zhongrenbang:id/btn_add" />
</hierarchy>"""

# 标题以数字开头：旧实现把它当编号步骤收进 steps。
TITLE_AND_NUMBERED_STEP_XML = """<hierarchy>
  <node bounds="[35,100][1045,200]" text="378735G畅享套餐h" resource-id="com.jianzhiku.zhongrenbang:id/mission_groupname" />
  <node bounds="[35,220][1045,320]" text="赏2.13元" resource-id="com.jianzhiku.zhongrenbang:id/mission_money" />
  <node bounds="[35,580][1045,680]" text="1.禁止地区：新疆 甘肃 云南" resource-id="com.jianzhiku.zhongrenbang:id/step_detail_nocap" />
  <node bounds="[35,1800][1045,1900]" text="立即报名" resource-id="com.jianzhiku.zhongrenbang:id/btn_add" />
</hierarchy>"""

# #37 真机语料里的四种页面片段。
JX_003_XML = """<hierarchy>
  <node bounds="[35,100][1045,200]" text="【创意宝进兜】" resource-id="com.jianzhiku.zhongrenbang:id/mission_groupname" />
  <node bounds="[35,220][1045,320]" text="赏1.02元" resource-id="com.jianzhiku.zhongrenbang:id/mission_money" />
  <node bounds="[35,580][1045,680]" text="复制网址到浏览器打开下载" resource-id="com.jianzhiku.zhongrenbang:id/step_detail_nocap" />
  <node bounds="[35,1800][1045,1900]" text="立即报名" resource-id="com.jianzhiku.zhongrenbang:id/btn_add" />
</hierarchy>"""

AUDIT_FAST_004_XML = """<hierarchy>
  <node bounds="[35,100][1045,200]" text="【手心输入法】" resource-id="com.jianzhiku.zhongrenbang:id/mission_groupname" />
  <node bounds="[35,220][1045,320]" text="赏0.43元" resource-id="com.jianzhiku.zhongrenbang:id/mission_money" />
  <node bounds="[35,580][1045,680]" text="应用市场搜索：手心输入法，下载安装，选择上方apk按键" resource-id="com.jianzhiku.zhongrenbang:id/step_detail_nocap" />
  <node bounds="[35,1800][1045,1900]" text="立即报名" resource-id="com.jianzhiku.zhongrenbang:id/btn_add" />
</hierarchy>"""

GUISHU_005_XML = """<hierarchy>
  <node bounds="[35,100][1045,200]" text="【鬼墟秘市】" resource-id="com.jianzhiku.zhongrenbang:id/mission_groupname" />
  <node bounds="[35,220][1045,320]" text="赏0.85元" resource-id="com.jianzhiku.zhongrenbang:id/mission_money" />
  <node bounds="[35,400][1045,500]" text="新用户 满18周岁 需要证件照片 认证绑卡分类" resource-id="com.jianzhiku.zhongrenbang:id/limite" />
  <node bounds="[35,580][1045,680]" text="浏览器打开链接进入" resource-id="com.jianzhiku.zhongrenbang:id/step_detail_nocap" />
  <node bounds="[35,700][1045,800]" text="邀请码截个图" resource-id="com.jianzhiku.zhongrenbang:id/step_detail_cap" />
  <node bounds="[35,1800][1045,1900]" text="立即报名" resource-id="com.jianzhiku.zhongrenbang:id/btn_add" />
</hierarchy>"""

WANLIAN_015_XML = """<hierarchy>
  <node bounds="[35,100][1045,200]" text="【万联摩尔】" resource-id="com.jianzhiku.zhongrenbang:id/mission_groupname" />
  <node bounds="[35,220][1045,320]" text="赏0.32元" resource-id="com.jianzhiku.zhongrenbang:id/mission_money" />
  <node bounds="[35,400][1045,500]" text="一个手机号一次" resource-id="com.jianzhiku.zhongrenbang:id/limite" />
  <node bounds="[35,1800][1045,1900]" text="立即报名" resource-id="com.jianzhiku.zhongrenbang:id/btn_add" />
</hierarchy>"""


def classify(xml: str, activity: str = ".Detail") -> dict:
    return classify_detail_page(build_page_state(xml, activity))


def run_pipeline(xml: str, activity: str = ".Detail"):
    """走生产链路：感知层字段 → Bounty → 守卫层。"""
    data = classify(xml, activity)
    bounty = Bounty(
        "real-page", "真实详情页",
        data["reward"] if data["reward"] is not None else 0.0,
        list(data["steps_text"]), list(data["restricted_regions_hint"]),
    )
    return check_feasibility(bounty)


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
        result = classify(DETAIL_XML)
        self.assertTrue(result["is_detail"])
        self.assertEqual(result["reward"], 2.13)

    def test_unescape_entities(self) -> None:
        self.assertEqual(parse_ui_xml(ENTITY_XML)[0].text, "A&B")
        self.assertEqual(build_page_state(ENTITY_XML, ".Main").texts, ["A&B"])


class RealDetailPageTest(unittest.TestCase):
    """378735G 真机页面：字段抽取与整条判定链路。"""

    def test_real_detail_page_is_detected(self) -> None:
        self.assertTrue(classify(REAL_TOP_XML, ".NewMissionStart")["is_detail"])

    def test_real_reward_parsed_from_mission_money(self) -> None:
        self.assertEqual(classify(REAL_TOP_XML)["reward"], 2.13)

    def test_real_steps_are_step_details_not_numbers(self) -> None:
        data = classify(REAL_TOP_XML)
        joined = " ".join(data["steps_text"])
        for counter in ("6分钟", "1931人", "5分钟", "24小时内", "248"):
            self.assertNotIn(counter, joined)
        self.assertIn("浏览器，输入ip，搜索后截图", joined)
        self.assertIn("姓名随意填写", joined)

    def test_real_regions_include_yunnan(self) -> None:
        regions = classify(REAL_TOP_XML)["restricted_regions_hint"]
        self.assertIn("云南", regions)
        for region in ("新疆", "甘肃", "北京", "西藏"):
            self.assertIn(region, regions)
        # 名单后的说明句不是地区名。
        self.assertNotIn("手机号跟ip是这些地区的不要做", regions)

    def test_real_page_aborts_on_production_path(self) -> None:
        verdict, reason = run_pipeline(REAL_TOP_XML, ".NewMissionStart")
        self.assertIs(verdict, Verdict.ABORT)
        self.assertIn(reason, (AbortReason.REGION_REJECTED,
                               AbortReason.ETHICS_FABRICATED_IDENTITY))

    def test_scrolled_page_still_is_detail(self) -> None:
        data = classify(REAL_SCROLLED_XML, ".NewMissionStart")
        self.assertTrue(data["is_detail"])
        # 标题与赏金已回收出屏幕，字段确实读不到，不能伪造 0.0。
        self.assertIsNone(data["reward"])

    def test_captured_steps_are_tracked(self) -> None:
        data = classify(REAL_SCROLLED_XML)
        self.assertEqual(len(data["steps_text"]), len(data["steps_done"]))
        done = dict(zip(data["steps_text"], data["steps_done"]))
        self.assertTrue(done["浏览器，输入ip，搜索后截图"])
        self.assertFalse(done["打开链接填写，姓名随意填写（姓名看着像人名）"])

    def test_limite_text_is_exposed(self) -> None:
        data = classify(REAL_TOP_XML)
        self.assertIn("西藏", data["limite_text"])
        self.assertTrue(data["regions_known"])

    def test_unread_region_is_unknown_not_unlimited(self) -> None:
        # 页面完全没出现地区/报名条件字段时，空列表表示「未知」。
        data = classify(BASE_XML)
        self.assertEqual(data["restricted_regions_hint"], [])
        self.assertFalse(data["regions_known"])

    def test_requires_vpn_is_flagged(self) -> None:
        xml = """<hierarchy>
          <node bounds="[35,100][1045,200]" text="【北京上海浪琴1121】" resource-id="com.jianzhiku.zhongrenbang:id/mission_groupname" />
          <node bounds="[35,220][1045,320]" text="赏0.17元" resource-id="com.jianzhiku.zhongrenbang:id/mission_money" />
          <node bounds="[35,580][1045,680]" text="各大商店搜索【爱加速】打开，ip调到以下地区" resource-id="com.jianzhiku.zhongrenbang:id/step_detail_nocap" />
          <node bounds="[35,1800][1045,1900]" text="立即报名" resource-id="com.jianzhiku.zhongrenbang:id/btn_add" />
        </hierarchy>"""
        self.assertTrue(classify(xml)["requires_vpn"])
        self.assertFalse(classify(REAL_TOP_XML)["requires_vpn"])


class StepExtractionTest(unittest.TestCase):
    def test_title_is_not_a_step(self) -> None:
        """标题以数字开头，但不是编号行，不能进 steps。"""
        data = classify(TITLE_AND_NUMBERED_STEP_XML)
        self.assertNotIn("378735G畅享套餐h", data["steps_text"])
        self.assertEqual(data["steps_text"], ["禁止地区：新疆 甘肃 云南"])

    def test_step_number_prefix_is_stripped(self) -> None:
        data = classify(TITLE_AND_NUMBERED_STEP_XML)
        self.assertEqual(data["steps_text"][0], "禁止地区：新疆 甘肃 云南")

    def test_only_step_detail_fields_are_steps(self) -> None:
        # 计数节点（avgtime/num_count/…）不是步骤，无论文本长短。
        data = classify(REAL_TOP_XML)
        for counter in ("6分钟", "1931人", "5分钟", "24小时内", "248", "1", "2"):
            self.assertNotIn(counter, data["steps_text"])


class RegionExtractionTest(unittest.TestCase):
    def test_forbidden_line_with_newline(self) -> None:
        regions = extract_regions([
            "禁止\n地区：新疆，甘肃，海南，云南，北京，上海，"
            "手机号跟ip是这些地区的不要做",
        ])
        for region in ("新疆", "甘肃", "海南", "云南", "北京", "上海"):
            self.assertIn(region, regions)
        self.assertNotIn("手机号跟ip是这些地区的不要做", regions)

    def test_condition_line_with_chinese_comma(self) -> None:
        xml = """<hierarchy>
          <node bounds="[0,0][10,10]" text="报名条件：北京、西藏 两个手机号地区不能做" resource-id="com.jianzhiku.zhongrenbang:id/limite" />
          <node bounds="[0,20][10,30]" text="立即报名" resource-id="com.jianzhiku.zhongrenbang:id/btn_add" />
        </hierarchy>"""
        result = classify(xml)
        self.assertEqual(result["restricted_regions_hint"], ["北京", "西藏"])

    def test_condition_line_with_ze(self) -> None:
        # 「北京，西藏这两个手机号地区不能做」里的「这」不能粘进地区名。
        xml = """<hierarchy>
          <node bounds="[0,0][10,10]" text="北京，西藏这两个手机号地区不能做" resource-id="com.jianzhiku.zhongrenbang:id/limite" />
          <node bounds="[0,20][10,30]" text="立即报名" resource-id="com.jianzhiku.zhongrenbang:id/btn_add" />
        </hierarchy>"""
        self.assertEqual(classify(xml)["restricted_regions_hint"], ["北京", "西藏"])

    def test_allowlist_line(self) -> None:
        regions = extract_regions(["必须到以下地区：北京、上海"])
        self.assertEqual(regions, ["北京", "上海"])

    def test_no_region_returns_empty(self) -> None:
        """页面没写地区限制时返回空列表（语义是「未知」，见注释 TODO）。"""
        self.assertEqual(classify(BASE_XML)["restricted_regions_hint"], [])

    def test_explicit_no_limit_is_known(self) -> None:
        # 「无」是平台明确说没有限制；「！」是脏数据，仍算未知。
        no_limit = """<hierarchy>
          <node bounds="[0,0][10,10]" text="无" resource-id="com.jianzhiku.zhongrenbang:id/limite" />
          <node bounds="[0,20][10,30]" text="立即报名" resource-id="com.jianzhiku.zhongrenbang:id/btn_add" />
        </hierarchy>"""
        junk_limit = no_limit.replace('text="无"', 'text="！"')
        known = classify(no_limit)
        self.assertTrue(known["regions_known"])
        self.assertEqual(known["restricted_regions_hint"], [])
        self.assertFalse(classify(junk_limit)["regions_known"])


class RealCorpusSnippetTest(unittest.TestCase):
    """#37 真机语料片段：资源 id 字段抽取正确，guard 读到的才是真步骤。"""

    def test_jx_003_steps_and_download(self) -> None:
        data = classify(JX_003_XML)
        self.assertIn("复制网址到浏览器打开下载", data["steps_text"])
        self.assertEqual(run_pipeline(JX_003_XML),
                         (Verdict.ABORT, AbortReason.NEEDS_THIRD_PARTY_APP))

    def test_audit_fast_004_steps_and_download(self) -> None:
        data = classify(AUDIT_FAST_004_XML)
        self.assertIn("应用市场搜索：手心输入法，下载安装，选择上方apk按键",
                      data["steps_text"])
        self.assertEqual(run_pipeline(AUDIT_FAST_004_XML),
                         (Verdict.ABORT, AbortReason.NEEDS_THIRD_PARTY_APP))

    def test_guishu_005_limite_has_certificate_photo(self) -> None:
        data = classify(GUISHU_005_XML)
        self.assertIsNotNone(data["limite_text"])
        self.assertIn("证件照片", data["limite_text"])
        # 步骤按 _nocap/_cap 顺序取，已截图的那条带 done。
        self.assertEqual(data["steps_text"], ["浏览器打开链接进入", "邀请码截个图"])
        self.assertEqual(data["steps_done"], [False, True])

    def test_wanlian_015_limite_kept(self) -> None:
        data = classify(WANLIAN_015_XML)
        self.assertEqual(data["limite_text"], "一个手机号一次")


if __name__ == "__main__":
    unittest.main()