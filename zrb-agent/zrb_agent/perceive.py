"""感知层：把 uiautomator 的 UI 树 XML 解析成结构化 PageState。

本层纯规则解析，不调用任何模型，也不读取截图像素。
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# 实测 resource-id（来源：悬赏大厅与详情页 uiautomator dump）
RID_HALL = "hall"
RID_JINGXUAN = "home_jingxuan"
RID_ITEM_TITLE = "item_title"
RID_ITEM_GONGZI = "item_gongzi"
RID_BB_TITLE = "bb_title"
RID_BB_MONEY = "bb_money"

# 详情页字段：真机 dump 的完整 id 形如
# com.jianzhiku.zhongrenbang:id/mission_groupname，匹配时只看最后一段。
RID_MISSION_GROUP = "mission_groupname"  # 标题，格式【App名】+描述
RID_MISSION_MONEY = "mission_money"      # 赏金，形如「赏2.13元」
RID_MISSION_DETAIL = "mission_detail"    # 类型标签（新用户/仅限新用户/来抢…）
RID_LIMITE = "limite"                    # 报名条件正文
RID_STEP_NOCAP = "step_detail_nocap"     # 未完成步骤正文
RID_STEP_CAP = "step_detail_cap"         # 已完成步骤正文
RID_CNT_NOCAP = "setpcount_nocap"        # 步骤序号（注意拼写是 setpcount）
RID_CNT_CAP = "setpcount_cap"
RID_BTN_ADD = "btn_add"                  # 立即报名

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_REWARD_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*元")
# 编号行：分隔符是必需的，「378735G畅享套餐h」以数字开头但不是编号行。
# 真机 step_detail_* 正文本身不带序号，这里只作防御性剥离。
_STEP_NUMBER_RE = re.compile(r"^\s*\d{1,2}\s*[.、．]\s*")

# 「禁止地区：A，B」与「不能做的地区：A、B」都表示这些地区做不了。
# 「禁止」与「地区」之间可能有换行（真机文本是「禁止&#10;地区：…」）。
_REGION_LIST_RE = re.compile(
    r"(?:禁止|限制)\s*地区\s*[：:]\s*([^\n]+)"
    r"|不能做的?地区\s*[：:]\s*([^\n]+)"
)
# 「北京，西藏这两个手机号地区不能做」没有冒号，单独处理。
# 非贪婪 + 可选「这」是为了不把「西藏这」当成一个地区名。
_SHORT_REGION_RE = re.compile(
    r"([\u4e00-\u9fa5]{2,8}(?:[、,，]\s*[\u4e00-\u9fa5]{2,8})*?)"
    r"\s*(?:这)?两个?手机号地区不能做"
)
# 「必须到指定地区：A、B」这种白名单句式；只有明确列出名单时才抽取。
_REGION_ALLOW_RE = re.compile(r"必须到(?:指定|以下)地区\s*[：:]\s*([^\n]+)")
_REGION_SPLIT_RE = re.compile(r"[、,，\s…]+")
# 名单后面常跟一句说明（如「手机号跟ip是这些地区的不要做」），按词过滤掉。
_REGION_NOISE = ("手机", "ip", "不要", "不能", "地区", "条件", "报名", "限制",
                 "如下", "例如", "其中", "之一", "任意", "即可", "打开", "链接",
                 "流程", "重新", "每次")

# 要求改 IP 才能继续的单属于红线（骗过平台校验），不是地区字段能表达的。
_VPN_RE = re.compile(r"[iI][pP]\s*调到|爱加速")
# 报名条件字段里的脏数据：平台用「！」占位，等同于没读到。
_LIMIT_PLACEHOLDERS = ("", "！", "!")


@dataclass
class UiElement:
    """一个可交互/可读的 UI 节点。"""

    ref: str
    text: str
    resource_id: str
    bounds: tuple[int, int, int, int]
    center: tuple[int, int]

    def norm_center(self, width: int, height: int) -> tuple[float, float]:
        """把像素中心点归一化到 [0,1]。"""
        if width <= 0 or height <= 0:
            raise ValueError("width 和 height 必须为正数")
        return (self.center[0] / width, self.center[1] / height)


@dataclass
class PageState:
    """一屏的状态：activity、可见元素、文本与截图路径。"""

    activity: str
    elements: list[UiElement] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    screenshot_path: str | None = None


def parse_ui_xml(xml_text: str) -> list[UiElement]:
    """解析 XML，仅保留有 text 或 resource-id 的节点，ref 按保留顺序编号。"""
    elements: list[UiElement] = []
    for node in ET.fromstring(xml_text).iter("node"):
        text = node.get("text", "") or ""
        resource_id = node.get("resource-id", "") or ""
        bounds = _BOUNDS_RE.search(node.get("bounds", "") or "")
        if (not text and not resource_id) or bounds is None:
            continue  # 纯布局容器或无法点击的节点丢弃
        x1, y1, x2, y2 = (int(v) for v in bounds.groups())
        elements.append(UiElement(
            ref=f"e{len(elements)}", text=text, resource_id=resource_id,
            bounds=(x1, y1, x2, y2), center=((x1 + x2) // 2, (y1 + y2) // 2),
        ))
    return elements


def build_page_state(xml_text: str, activity: str,
                     screenshot_path: str | None = None) -> PageState:
    """组合 XML、activity 与截图路径；文本统一做一次 HTML 实体反转义。"""
    elements = parse_ui_xml(xml_text)
    texts = [html.unescape(el.text) for el in elements if el.text]
    return PageState(activity, elements, texts, screenshot_path)


def find_elements(elements: list[UiElement], *, text: str | None = None,
                  resource_id: str | None = None,
                  contains: str | None = None) -> list[UiElement]:
    """按精确 text、精确 resource-id 或 text 子串查找（多条件取交集）。"""
    hits: list[UiElement] = []
    for el in elements:
        if text is not None and el.text != text:
            continue
        if resource_id is not None and el.resource_id != resource_id:
            continue
        if contains is not None and contains not in el.text:
            continue
        hits.append(el)
    return hits


def tap_target(elements: list[UiElement], *, text: str | None = None,
               contains: str | None = None) -> tuple[int, int] | None:
    """返回第一个命中元素的 center；未命中返回 None。"""
    hits = find_elements(elements, text=text, contains=contains)
    return hits[0].center if hits else None


def _rid(element: UiElement) -> str:
    """resource-id 只取最后一段，兼容「包名:id/字段」的完整写法。"""
    return element.resource_id.rsplit("/", 1)[-1]


def _region_tokens(text: str) -> list[str]:
    """把一段名单拆成地区名，丢掉句末说明与噪音 token。"""
    tokens: list[str] = []
    for raw in _REGION_SPLIT_RE.split(text):
        token = raw.strip().strip("。；;")
        # 「北京，西藏这两个…」里的「这」会被非贪婪正则粘在最后一个地区上。
        if token.endswith("这") and len(token) > 1:
            token = token[:-1]
        if not token or token in tokens:
            continue
        if re.search(r"[A-Za-z0-9]", token):
            continue
        if len(token) > 20:
            continue
        if any(noise in token.lower() for noise in _REGION_NOISE):
            continue
        tokens.append(token)
    return tokens


def extract_regions(texts: list[str]) -> list[str]:
    """从页面文本里抽取「不能做的地区」名单；抽不到返回空列表。

    TODO(#32): 空列表现在同时表示「页面明确无限制」与「没读到/抽取失败」。
    本层用 regions_known 先把「是否读到限制字段」区分出来，黑白名单语义统一
    留给 #32，不要把空列表当「无限制」用。
    """
    regions: list[str] = []
    for line in texts:
        for pattern in (_REGION_LIST_RE, _SHORT_REGION_RE, _REGION_ALLOW_RE):
            for match in pattern.finditer(line):
                # _REGION_LIST_RE 有两个分支，取实际命中的那个捕获组。
                captured = next((group for group in match.groups() if group), None)
                if not captured:
                    continue
                for token in _region_tokens(captured):
                    if token not in regions:
                        regions.append(token)
    return regions


def classify_detail_page(page: PageState) -> dict:
    """按 resource-id 识别悬赏详情页字段，不再靠文本形状猜。

    滚动位置会改变可见节点：同一张详情页顶部有标题与赏金，滚一屏后标题被
    回收。所以 is_detail 只看 mission_groupname / btn_add，不看「文本里像不像
    步骤」；需要完整字段时调用方必须先滚回顶部或做分页聚合。
    """
    elements = page.elements
    # 存在标题或「立即报名」按钮即为详情页——两者之一在滚动后仍可能可见。
    is_detail = any(_rid(el) in (RID_MISSION_GROUP, RID_BTN_ADD) for el in elements)

    reward = None
    for el in elements:
        if _rid(el) != RID_MISSION_MONEY:
            continue
        if matched := _REWARD_RE.search(el.text):
            reward = float(matched.group(1))
            break
    if reward is None:  # 老页面没有 mission_money 时的兜底：仍需带「赏」字。
        for line in page.texts:
            if "赏" in line and (matched := _REWARD_RE.search(line)):
                reward = float(matched.group(1))
                break

    steps: list[str] = []
    steps_done: list[bool] = []
    limit_texts: list[str] = []
    step_texts: list[str] = []
    for el in elements:
        rid = _rid(el)
        text = el.text.strip()
        if rid == RID_LIMITE and text:
            limit_texts.append(text)
        elif rid in (RID_STEP_NOCAP, RID_STEP_CAP):
            step_texts.append(text)
            # 序号只用于对齐，正文里不带序号；剥离只作防御，真机正文本就没有。
            body = _STEP_NUMBER_RE.sub("", text).strip()
            if body:
                steps.append(body)
                steps_done.append(rid == RID_STEP_CAP)

    regions = extract_regions(limit_texts + step_texts)
    # 页面出现了报名条件字段且不是「！」这种脏数据占位，就说明这一页对资格有
    # 明确表述（「无」也算明确）；没出现才是未知。regions_known=False 时不能
    # 把空列表当「没有任何限制」。
    regions_known = bool(regions) or any(
        text not in _LIMIT_PLACEHOLDERS for text in limit_texts)
    requires_vpn = any(_VPN_RE.search(line) for line in page.texts)
    return {"is_detail": is_detail, "reward": reward, "steps_text": steps,
            "steps_done": steps_done,
            "restricted_regions_hint": regions, "regions_known": regions_known,
            "requires_vpn": requires_vpn,
            "limite_text": " ".join(limit_texts) if limit_texts else None}
