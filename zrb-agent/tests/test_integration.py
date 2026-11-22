"""生产口径集成测试：用真机 dump / PNG 头把 perceive → guard 走通。

不 mock 任何内部逻辑：地区名单只从感知层来，不手填；步骤也只用感知层抽出的文本。
"""

import inspect, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zrb_agent import device as device_module
from zrb_agent.guard.feasibility import check_feasibility
from zrb_agent.perceive import build_page_state, classify_detail_page
from zrb_agent.schema import AbortReason, Bounty, Verdict

RID = "com.jianzhiku.zhongrenbang:id/"

# 三个夹具文本逐字来自真机；resource-id 用真机完整 id，按 id 取字段时不会被误判。
REGION_LIMITED_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node bounds="[35,180][1045,260]" text="食品调查2" resource-id="{RID}mission_groupname" />
  <node bounds="[35,280][1045,340]" text="赏金1.50元" resource-id="{RID}mission_money" />
  <node bounds="[35,380][1045,440]" text="剩余名额 288" resource-id="" />
  <node bounds="[35,520][1045,600]" text="报名条件" resource-id="{RID}view_limit" />
  <node bounds="[35,620][1045,700]" text="有IP控制，仅限广州/东莞/南宁/武汉/长沙/南昌/宁波" resource-id="{RID}limite" />
  <node bounds="[35,760][1045,820]" text="操作步骤：" resource-id="" />
  <node bounds="[35,840][1045,920]" text="1.打开链接填写问卷" resource-id="{RID}step_detail_nocap" />
  <node bounds="[35,940][1045,1020]" text="2.完成后截图上传" resource-id="{RID}step_detail_nocap" />
  <node bounds="[35,1821][1045,1905]" text="立即报名" resource-id="{RID}btn_add" />
</hierarchy>"""

NUMERIC_TITLE_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node bounds="[35,180][1045,260]" text="378735G畅享套餐h" resource-id="{RID}mission_groupname" />
  <node bounds="[35,280][1045,340]" text="赏金2.13元" resource-id="{RID}mission_money" />
  <node bounds="[35,760][1045,820]" text="操作步骤：" resource-id="" />
  <node bounds="[35,840][1045,920]" text="1.禁止地区：新疆 甘肃 海南 云南 北京 上海" resource-id="{RID}step_detail_nocap" />
  <node bounds="[35,940][1045,1020]" text="2.打开百度搜索ip，截图保存" resource-id="{RID}step_detail_nocap" />
  <node bounds="[35,1821][1045,1905]" text="立即报名" resource-id="{RID}btn_add" />
</hierarchy>"""

VAGUE_STEPS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node bounds="[35,180][1045,260]" text="A-97990号调查" resource-id="{RID}mission_groupname" />
  <node bounds="[35,280][1045,340]" text="赏金1.50元" resource-id="{RID}mission_money" />
  <node bounds="[35,760][1045,820]" text="操作步骤：" resource-id="" />
  <node bounds="[35,840][1045,920]" text="1.按页面提示操作" resource-id="{RID}step_detail_nocap" />
  <node bounds="[35,1821][1045,1905]" text="立即报名" resource-id="{RID}btn_add" />
</hierarchy>"""


def classify(xml_text: str, activity: str = ".DetailActivity") -> dict:
    return classify_detail_page(build_page_state(xml_text, activity))


def run_pipeline(xml_text: str, activity: str = ".DetailActivity"):
    """把原始 UI dump 走完 perceive → guard，返回 (Verdict, AbortReason | None)。"""
    return check_feasibility(to_bounty(xml_text, activity))


def to_bounty(xml_text: str, activity: str = ".DetailActivity") -> Bounty:
    """按新契约把感知层输出接成 Bounty。

    地区字段的 None 表示未知、[] 表示确定无：夹具里完全没有限制字段时（例如只
    测步骤的样本），本测试按「已知无限制」喂给守卫层，避免 UNKNOWN_REGIONS 抢在
    目标断言之前；真实生产接线必须保留 None，不能这样降级。
    """
    page = build_page_state(xml_text, activity)
    detail = classify_detail_page(page)
    if not detail["is_detail"]:
        raise AssertionError("夹具不是详情页，测试本身写错了")
    allowed = detail["allowed_regions_hint"]
    forbidden = detail["forbidden_regions_hint"]
    if allowed is None and forbidden is None:
        allowed, forbidden = [], []
    return Bounty(
        id="fixture", title=detail["title"] or "真实详情页",
        reward=detail["reward"],
        steps=[step["text"] for step in detail["steps"]],
        allowed_regions=allowed, forbidden_regions=forbidden,
        type=detail["detail"], limite=detail["limite"])


class PerceiveToGuardTest(unittest.TestCase):
    def test_region_limited_aborts(self):
        """地区白名单：感知层必须抽出地区，守卫层必须拒。"""
        self.assertEqual(run_pipeline(REGION_LIMITED_XML),
                         (Verdict.ABORT, AbortReason.REGION_REJECTED))

    def test_region_extracted_at_all(self):
        """单独断言抽取，失败时能立刻定位是抽取问题还是判定问题。"""
        detail = classify(REGION_LIMITED_XML)
        self.assertNotEqual(detail["allowed_regions_hint"], [],
                            "感知层没抽到地区，REGION_REJECTED 永远不会触发")
        self.assertEqual(detail["forbidden_regions_hint"], [])
        for region in ("广州", "东莞", "南宁", "武汉", "长沙", "南昌", "宁波"):
            self.assertIn(region, detail["allowed_regions_hint"])

    def test_forbidden_region_from_steps_aborts(self):
        """真机把「禁止地区」写在第 1 步；黑名单含本机地区必须拒。"""
        detail = classify(NUMERIC_TITLE_XML)
        self.assertIn("云南", detail["forbidden_regions_hint"])
        self.assertEqual(run_pipeline(NUMERIC_TITLE_XML),
                         (Verdict.ABORT, AbortReason.REGION_REJECTED))

    def test_numeric_title_is_not_a_step(self):
        """标题以数字开头，但不能进 steps。"""
        steps = [step["text"] for step in classify(NUMERIC_TITLE_XML)["steps"]]
        self.assertNotIn("378735G畅享套餐h", steps)
        self.assertTrue(all(not step[:1].isdigit() for step in steps),
                        f"steps 里还有序号前缀：{steps}")

    def test_vague_steps_abort(self):
        """平台只写「按页面提示操作」时必须判 UNKNOWN_STEPS，不能放行。"""
        self.assertEqual(run_pipeline(VAGUE_STEPS_XML),
                         (Verdict.ABORT, AbortReason.UNKNOWN_STEPS))

    def test_bounty_keeps_unknown_region_semantics(self):
        """没有限制字段时，生产接线应保留 None，守卫层据此判 UNKNOWN_REGIONS。"""
        detail = classify(VAGUE_STEPS_XML)
        self.assertIsNone(detail["allowed_regions_hint"])
        self.assertIsNone(detail["forbidden_regions_hint"])
        bounty = Bounty(id="fixture", title=detail["title"],
                        reward=detail["reward"],
                        steps=[step["text"] for step in detail["steps"]])
        self.assertEqual(check_feasibility(bounty),
                         (Verdict.ABORT, AbortReason.UNKNOWN_REGIONS))


class CoordinateSpaceTest(unittest.TestCase):
    """坐标系必须和 uiautomator bounds、截图 PNG 同一个空间。"""

    def test_png_header_reads_correctly(self):
        png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
               b"\x00\x00\x04\x38\x00\x00\x07\x80"      # 1080 x 1920
               b"\x08\x02\x00\x00\x00")
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.write(png); handle.close()
        self.addCleanup(os.unlink, handle.name)
        self.assertEqual(device_module._png_size(handle.name), (1080, 1920))

    def test_wm_size_is_not_the_source_of_truth(self):
        """守卫约定：screen_size 不允许解析 wm size。"""
        source = inspect.getsource(device_module.Device.screen_size)
        self.assertNotIn('["shell", "wm", "size"]', source,
                         "screen_size 不能依赖 wm size：它报面板物理方向，与 UI 树坐标系不一致")