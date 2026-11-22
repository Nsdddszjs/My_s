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
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_REWARD_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*元")
_STEP_PREFIX_RE = re.compile(r"^\s*\d")
_STEP_KEYWORDS = ("截图", "打开", "下载", "填写")


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


def classify_detail_page(page: PageState) -> dict:
    """纯规则识别悬赏详情页 8 段结构。"""
    joined = "\n".join(page.texts)
    is_detail = ("报名条件" in joined or "操作步骤" in joined) and "立即报名" in joined
    reward = None
    for line in page.texts:
        if "赏" in line and (matched := _REWARD_RE.search(line)):
            reward = float(matched.group(1))
            break
    steps = [line for line in page.texts if
             _STEP_PREFIX_RE.match(line)
             or (len(line) > 8 and any(k in line for k in _STEP_KEYWORDS))]
    return {"is_detail": is_detail, "reward": reward, "steps_text": steps,
            "restricted_regions_hint": []}


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
