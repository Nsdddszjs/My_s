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

# 详情页字段（实测 378735G 详情页）。真机 dump 的完整 id 形如
# com.jianzhiku.zhongrenbang:id/mission_groupname，匹配时只取最后一段。
RID_MISSION_GROUP = "mission_groupname"   # 任务组名，常带【】与截断省略号
RID_MISSION_TITLE = "mission_title"       # 任务标题（如「简单」）
RID_MISSION_MONEY = "mission_money"       # 赏金，形如「赏2.13元」
RID_MISSION_DETAIL = "mission_detail"     # 任务说明/类型标签
RID_LIMITE = "limite"                     # 报名条件与限制正文
RID_STEP_CAP = "step_detail_cap"          # 该步需要截图证据
RID_STEP_NOCAP = "step_detail_nocap"      # 该步不需要截图
RID_STEP_CNT_CAP = "setpcount_cap"        # 步骤序号（与 _cap 步骤配对）
RID_STEP_CNT_NOCAP = "setpcount_nocap"    # 步骤序号（与 _nocap 步骤配对；拼写就是 setp）
RID_STEP_TXT = "step_txt"                 # 步骤行内文本输入框
RID_BTN_ADD = "btn_add"                   # 「立即报名」/「提交（剩余…分钟）」
RID_MAIN_BTN = "main_btn"                 # 链接/主操作按钮

# 步骤类型：cap 要提交截图证据，nocap 不要截图（但仍要执行，不等于已完成）。
STEP_TYPE_CAP = "cap"
STEP_TYPE_NOCAP = "nocap"

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_REWARD_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*元")
# 编号行必须有分隔符；「378735G畅享套餐h」以数字开头但不是步骤（#37）。
_STEP_NUMBER_RE = re.compile(r"^\s*\d{1,2}\s*[.、．]\s*")

# 「禁止地区：A，B」与「不能做的地区：A、B」都表示这些地区做不了。
# 「禁止」与「地区」之间可能有换行（真机文本是「禁止&#10;地区：…」）。
_FORBIDDEN_LIST_RE = re.compile(
    r"(?:禁止|限制)\s*地区\s*[：:]\s*([^\n]+)"
    r"|不能做的?地区\s*[：:]\s*([^\n]+)"
)
# 「北京，西藏这两个手机号地区不能做」没有冒号，单独处理。
# 非贪婪 + 可选「这」是为了不把「西藏这」当成一个地区名。
_SHORT_FORBIDDEN_RE = re.compile(
    r"([\u4e00-\u9fa5]{2,8}(?:[、,，]\s*[\u4e00-\u9fa5]{2,8})*?)"
    r"\s*(?:这)?两个?手机号地区不能做"
)
# 「必须到指定地区：A、B」这种白名单句式；只有明确列出名单时才抽取。
_ALLOWED_LIST_RE = re.compile(r"必须到(?:指定|以下)地区\s*[：:]\s*([^\n]+)")
# 「仅限广州/东莞/…」也是白名单；要求至少两个地区，避免把「仅限新用户」
# 这种人群限制误当地区名。
_ONLY_ALLOWED_RE = re.compile(
    r"(?:仅限|只限)\s*([\u4e00-\u9fa5]{2,8}(?:[、,，/／]\s*[\u4e00-\u9fa5]{2,8})+)"
)
# 单个地区只在带「IP/地区」后缀时才认，处理「仅限泰国IP」。
_ONLY_SINGLE_ALLOWED_RE = re.compile(
    r"(?:仅限|只限)\s*([\u4e00-\u9fa5]{2,8})\s*(?:[Ii][Pp]|地区)"
)
_REGION_SPLIT_RE = re.compile(r"[、,，/／\s…]+")
# 名单后面常跟一句说明（如「手机号跟ip是这些地区的不要做」），按词过滤掉。
_REGION_NOISE = ("手机", "ip", "不要", "不能", "地区", "条件", "报名", "限制",
                 "如下", "例如", "其中", "之一", "任意", "即可", "打开", "链接",
                 "流程", "重新", "每次")
# 页面上提到地区/IP 控制却给不出名单时，不能把空列表当「确定无限制」。
_REGION_CONCEPT_RE = re.compile(r"地区|区域|省份|ip\s*控制", re.IGNORECASE)
# 报名条件字段里的脏数据：平台用「！」占位，等同于没读到。
_LIMIT_PLACEHOLDERS = ("", "！", "!")

# 详情页独有的 resource-id；大厅列表的 item_title/bb_money 不算。
_DETAIL_RIDS = frozenset({
    RID_MISSION_GROUP, RID_MISSION_TITLE, RID_MISSION_MONEY, RID_MISSION_DETAIL,
    RID_LIMITE, RID_BTN_ADD, RID_STEP_CAP, RID_STEP_NOCAP, RID_STEP_CNT_CAP,
    RID_STEP_CNT_NOCAP, RID_STEP_TXT,
})


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


def _text(element: UiElement) -> str:
    """节点文本：反转义并去掉首尾空白。"""
    return html.unescape(element.text).strip()


def _first_text(elements: list[UiElement], resource_id: str) -> str | None:
    """取第一个非空字段文本；没有该字段时返回 None。"""
    for element in elements:
        if _rid(element) == resource_id:
            text = _text(element)
            if text:
                return text
    return None


def _all_texts(elements: list[UiElement], resource_id: str) -> list[str]:
    """收集某个 resource-id 的所有非空文本。"""
    return [text for element in elements
            if _rid(element) == resource_id and (text := _text(element))]


def _step_type(resource_id: str) -> str:
    return STEP_TYPE_CAP if resource_id == RID_STEP_CAP else STEP_TYPE_NOCAP


def _step_number(text: str) -> int | None:
    """setpcount_* 的序号文本转整数；不是纯数字时返回 None。"""
    try:
        return int(text.strip())
    except (TypeError, ValueError):
        return None


def extract_steps(elements: list[UiElement]) -> list[dict]:
    """按 setpcount_cap / setpcount_nocap 的序号配对 step_detail_cap / _nocap 正文。

    返回 ``[{"index": 1, "text": "...", "type": "cap"|"nocap"}, ...]``：

    - ``index`` 优先取前面最近的、尚未配对的 setpcount 序号；
    - 真机滚动后可能只留下 step_detail、序号已回收出屏幕，此时按出现顺序补号；
    - ``type`` 以正文节点为准：``step_detail_cap`` 需要截图证据，``_nocap`` 不需要；
    - 正文里万一带「1.」序号前缀（旧 dump 有过），剥掉，序号只由 index 表达。
    """
    steps: list[dict] = []
    pending_numbers: list[int | None] = []
    next_index = 1
    for element in elements:
        resource_id = _rid(element)
        if resource_id in (RID_STEP_CNT_CAP, RID_STEP_CNT_NOCAP):
            pending_numbers.append(_step_number(_text(element)))
            continue
        if resource_id not in (RID_STEP_CAP, RID_STEP_NOCAP):
            continue
        # 即使正文为空也要消费序号，否则后面的步骤会错配到这个序号上。
        index = pending_numbers.pop(0) if pending_numbers else None
        text = _STEP_NUMBER_RE.sub("", _text(element)).strip()
        if not text:
            continue
        if index is None:
            index = next_index
        next_index = max(next_index, index + 1)
        steps.append({"index": index, "text": text,
                      "type": _step_type(resource_id)})
    return steps


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


def _matches(texts: list[str], patterns) -> list[str]:
    """按顺序套用地区名单正则，返回去重后的 token 列表。"""
    tokens: list[str] = []
    for line in texts:
        for pattern in patterns:
            for match in pattern.finditer(line):
                captured = next((group for group in match.groups() if group), None)
                if not captured:
                    continue
                for token in _region_tokens(captured):
                    if token not in tokens:
                        tokens.append(token)
    return tokens


def extract_forbidden_regions(texts: list[str]) -> list[str]:
    """抽取「禁止/不能做」黑名单地区；抽不到返回空列表。"""
    return _matches(texts, (_FORBIDDEN_LIST_RE, _SHORT_FORBIDDEN_RE))


def extract_allowed_regions(texts: list[str]) -> list[str]:
    """抽取「仅限/必须到」白名单地区；抽不到返回空列表。"""
    return _matches(texts, (_ALLOWED_LIST_RE, _ONLY_ALLOWED_RE,
                            _ONLY_SINGLE_ALLOWED_RE))


def extract_region_hints(texts: list[str], *, known: bool
                         ) -> tuple[list[str] | None, list[str] | None]:
    """返回 ``(allowed_hint, forbidden_hint)``，地区语义用 None / [] 分开。

    - ``None``：没读到限制字段（或读到了却提到地区/IP 控制、但解析不出名单）→ 未知；
    - ``[]``：限制字段已读且没有该方向的名单 → 确定无；
    - 非空列表：抽到的地区名。

    ``known`` 表示 mission_detail / limite 至少有一个被读到（非「！」占位）。
    只要任一方向真抽到名单，即使限制字段被滚动回收也按已知处理。
    """
    allowed = extract_allowed_regions(texts)
    forbidden = extract_forbidden_regions(texts)
    if allowed or forbidden:
        return allowed, forbidden
    if known and not any(_REGION_CONCEPT_RE.search(text) for text in texts):
        return [], []
    return None, None


def classify_detail_page(page: PageState) -> dict:
    """按 resource-id 识别悬赏详情页，不再靠文本形状猜。

    返回字段与语义：

    - ``is_detail``：出现任一详情页独有 resource-id 即详情页（滚动后标题被回收
      仍认得出，不依赖「报名条件」「立即报名」这些文本）。
    - ``title``：``mission_groupname`` + ``mission_title``；都没读到为 ``None``。
    - ``reward``：``mission_money`` 里的金额；没读到为 ``None``（不用 0.0 代偿）。
    - ``detail``：``mission_detail`` 原文；没读到为 ``None``。
    - ``limite``：``limite``（报名条件/限制）原文；没读到为 ``None``。
    - ``steps``：``setpcount_*`` 序号配对 ``step_detail_*`` 的步骤序列，每步含
      ``index`` / ``text`` / ``type``（cap=需要截图，nocap=不需要截图）。
    - ``has_text_input`` / ``text_input_hint``：页面是否存在 ``step_txt`` 输入框
      及其 hint（hint 为空时仍为 ``True``，hint 为 ``None``）。
    - ``primary_button``：``btn_add`` 文本（「立即报名」/「提交（剩余…分钟）」）。
    - ``link_button``：``main_btn`` 文本。
    - ``allowed_regions_hint`` / ``forbidden_regions_hint``：从 ``mission_detail``、
      ``limite`` 与步骤正文抽取（真机 378735G 把「禁止地区」写在第 1 步）。``None``
      表示未知，``[]`` 表示确定无，**不能互相代偿**。
    """
    elements = page.elements
    steps = extract_steps(elements)

    title_parts = [part for rid in (RID_MISSION_GROUP, RID_MISSION_TITLE)
                   if (part := _first_text(elements, rid))]
    title = " ".join(title_parts) if title_parts else None
    detail = _first_text(elements, RID_MISSION_DETAIL)
    limite_texts = _all_texts(elements, RID_LIMITE)
    limite = " ".join(limite_texts) if limite_texts else None

    reward = None
    money = _first_text(elements, RID_MISSION_MONEY)
    if money is not None and (matched := _REWARD_RE.search(money)):
        reward = float(matched.group(1))

    # 限制字段被读到且不是「！」占位，才可能给出「确定无」的结论。
    known_region_fields = any(text not in _LIMIT_PLACEHOLDERS
                              for text in ([detail] if detail else []) + limite_texts)
    region_sources = [text for text in
                      ([detail] if detail else []) + limite_texts
                      + [step["text"] for step in steps]
                      if text and text not in _LIMIT_PLACEHOLDERS]
    allowed_regions, forbidden_regions = (
        extract_region_hints(region_sources, known=known_region_fields)
        if region_sources else (None, None))

    text_inputs = [_text(element) for element in elements
                   if _rid(element) == RID_STEP_TXT]
    has_text_input = bool(text_inputs)

    return {
        "is_detail": any(_rid(element) in _DETAIL_RIDS for element in elements),
        "title": title,
        "reward": reward,
        "detail": detail,
        "limite": limite,
        "steps": steps,
        "has_text_input": has_text_input,
        "text_input_hint": next((text for text in text_inputs if text), None),
        "primary_button": _first_text(elements, RID_BTN_ADD),
        "link_button": _first_text(elements, RID_MAIN_BTN),
        "allowed_regions_hint": allowed_regions,
        "forbidden_regions_hint": forbidden_regions,
    }


SUBMIT_SUCCESS_ACTIVITY = "MissionSubmitSuccess"


def is_submit_success(focus_activity: str, page_state: PageState) -> bool:
    """判定提交是否真的成功；只弹 toast 不算成功。

    实测成功信号只有两种：前台活动变为
    `com.jianzhiku.activity.MissionSubmitSuccess`（页面「提交成功 / 等待悬赏主审核 /
    24 小时内」），或页面文本同时出现「提交成功」与「等待…审核」。
    漏填内容时点提交只弹 700ms toast「有内容没有填写...」，页面完全不变，
    因此绝不能把 toast 当作提交成功。
    """
    activities = f"{focus_activity}\n{page_state.activity}".lower()
    if SUBMIT_SUCCESS_ACTIVITY.lower() in activities:
        return True
    joined = "\n".join(page_state.texts)
    return "提交成功" in joined and "等待" in joined and "审核" in joined


def has_approved_entry(page_state: PageState, bounty_id: str) -> bool:
    """「我的 → 已提交 → 已通过」列表里是否出现指定悬赏的条目。

    必须同时满足：页面处于「已通过」视图，且条目文本包含 bounty_id。
    只出现「已提交 / 审核中」不算通过。调用方应在提交前记录列表基线，
    提交后用本函数做 FINISH(result=done) 前的终局校验。
    """
    bounty_id = str(bounty_id).strip()
    if not bounty_id:
        raise ValueError("bounty_id 不能为空")
    if "已通过" not in "\n".join(page_state.texts):
        return False
    return any(bounty_id in text for text in page_state.texts)
