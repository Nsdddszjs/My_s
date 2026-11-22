"""主循环状态机：守卫 → 进详情 → 报名 → 逐步执行 → 收尾。

依赖全部注入；不信任感知层返回值：restricted_regions 可能为空/None，坐标每步现算，不缓存
screen_size。硬约束：0.3~0.9 秒随机节流，同一坐标最多连点 2 次，动作数 ≤ max_steps。
"""
from __future__ import annotations

import random
import time
import xml.etree.ElementTree as ET
from enum import Enum
from pathlib import Path

from zrb_agent.ledger import Ledger, LedgerEntry
from zrb_agent.schema import Verdict
from zrb_agent.schema_action import Action, ActionType


class Phase(Enum):
    BOOT = "BOOT"
    SCAN_HALL = "SCAN_HALL"
    SCREEN = "SCREEN"
    PREFLIGHT = "PREFLIGHT"
    ENROLL = "ENROLL"
    EXECUTE_STEP = "EXECUTE_STEP"
    COLLECT_EVIDENCE = "COLLECT_EVIDENCE"
    SUBMIT = "SUBMIT"
    VERIFY_SUBMITTED = "VERIFY_SUBMITTED"
    REPORT = "REPORT"
    ABORTED = "ABORTED"
    DONE = "DONE"


# App 把步骤完成状态编码在 resource-id 里：cap=已截图，nocap=未截图。
_DONE_RIDS = {"step_detail_cap": True, "step_detail_nocap": False,
              "setpcount_cap": True, "setpcount_nocap": False}


def _done_flags(xml_text: str) -> list[bool]:
    """按出现顺序抽 _cap/_nocap 完成位；不是该模板时返回空列表。"""
    try:
        nodes = ET.fromstring(xml_text).iter("node")
        return [_DONE_RIDS[rid] for node in nodes
                if (rid := (node.get("resource-id") or "").rsplit("/", 1)[-1]) in _DONE_RIDS]
    except ET.ParseError:
        return []


def default_verify(expect: str, before_xml: str, after_xml: str) -> bool:
    """能用 _cap/_nocap 判 done 就用它，否则退回“页面变了”（不做截图 diff）。"""
    before, after = _done_flags(before_xml), _done_flags(after_xml)
    return sum(after) > sum(before) if before and after else before_xml != after_xml


class Runner:
    """单次悬赏状态机；device/perceive/plan_fn/guard_fn 全部注入。"""

    def __init__(self, device, perceive, plan_fn, guard_fn, ledger: Ledger,
                 max_steps: int = 40, dry_run: bool = True, verify_fn=None,
                 sleep_fn=None, xml_path: str = "ui.xml") -> None:
        self.device, self.perceive = device, perceive
        self.plan_fn, self.guard_fn, self.ledger = plan_fn, guard_fn, ledger
        self.max_steps, self.dry_run = max_steps, dry_run
        self.verify_fn, self.sleep_fn = verify_fn or default_verify, sleep_fn or time.sleep
        self.xml_path = xml_path
        self.phase, self.actions = Phase.BOOT, 0
        self._recent_taps: list[tuple[int, int]] = []

    def run(self, bounty) -> dict:
        """跑一次任务；守卫否决时返回 ABORTED 且不碰设备。"""
        verdict, reason = self.guard_fn(bounty)
        if verdict is Verdict.ABORT:
            return self._abort(getattr(reason, "value", reason) or "ABORT")
        page, _ = self._top()
        enroll = next((el for el in page.elements if el.text == "立即报名"
                       or "btn_apply" in el.resource_id), None)
        self.phase = Phase.PREFLIGHT
        if self.dry_run:
            return {"phase": "PREFLIGHT_OK", "would_enroll": enroll is not None}
        if enroll is None:
            return self._abort("ENROLL_NOT_FOUND")
        self.phase = Phase.ENROLL
        self._pace()
        self.device.tap(*enroll.center)
        self._recent_taps.append(enroll.center)
        self.actions += 1
        self._log(Action("点立即报名", ActionType.TAP, {"x": enroll.center[0],
                     "y": enroll.center[1]}, "进入步骤页"), 0, True, "已点击报名")
        history: list[Action] = []
        for index, step in enumerate(bounty.steps, 1):
            if (result := self._step(index, step, bounty, history)) is not None:
                return result
        self.phase = Phase.REPORT
        return {"phase": "DONE"}

    def _step(
        self,
        index: int,
        step,  # schema.Step：text / needs_capture / has_text_input
        bounty,
        history: list[Action],
    ) -> dict | None:
        failures = 0
        while failures < 2:
            if self.actions >= self.max_steps:
                return self._finish(index, "MAX_STEPS")
            page, before = self._screen()
            # step 可能是 Step，也可能是被调用方直接塞进来的纯字符串。
            step_text = step.text if hasattr(step, 'text') else str(step)
            action = self.plan_fn(page, step_text, history, bounty.title)
            if action.validate():
                return self._abort("INVALID_ACTION")
            if action.action is ActionType.FINISH:
                return self._finish(index, action)
            if action.action in (ActionType.ASK_HUMAN, ActionType.PICK_FROM_GALLERY):
                self._log(action, index, False, "需要人工或执行层支持")
                return self._abort(action.action.value)
            history.append(action)
            if action.action is ActionType.TAP:
                params = action.params
                target = ((int(params["x"]), int(params["y"])) if "x" in params
                          else next((el.center for el in page.elements
                                     if el.ref == params.get("ref")), None))
                if target is None:
                    return self._abort("TAP_TARGET_MISSING")
                recent = self._recent_taps
                if len(recent) >= 2 and recent[-1] == recent[-2] == target:
                    self._log(action, index, False, "同一坐标连续点击超过 2 次")
                    return self._abort("STUCK")
                self._pace()
                self.device.tap(*target)
                self._recent_taps.append(target)
                prefix = None
            else:
                self._recent_taps.clear()
                self._pace()
                prefix = self._device_action(action)
            self.actions += 1
            self.device.dump_ui(self.xml_path)
            after = Path(self.xml_path).read_text(encoding="utf-8")
            ok = bool(self.verify_fn(action.expect, before, after))
            self._log(action, index, ok, "通过" if ok else "未通过", prefix)
            if ok:
                return None
            failures += 1
        return self._abort("STUCK")

    def _top(self) -> tuple:
        """进详情先滑到顶：滚动后标题/赏金节点会被回收。"""
        self.phase = Phase.SCREEN
        page, _ = self._screen()
        height = max((el.bounds[3] for el in page.elements), default=1920)
        width = max((el.bounds[2] for el in page.elements), default=1080)
        for _ in range(2):
            self._pace()
            self.device.swipe(width // 2, height // 5, width // 2, height * 4 // 5, 300)
        return self._screen()

    def _screen(self) -> tuple:
        self.device.dump_ui(self.xml_path)
        xml = Path(self.xml_path).read_text(encoding="utf-8")
        focus = getattr(self.device, "current_focus", None)
        return self.perceive.build_page_state(xml, focus() if callable(focus) else ""), xml

    def _device_action(self, action: Action) -> str | None:
        params = action.params
        if action.action is ActionType.SWIPE:
            self.device.swipe(*params["from"], *params["to"], 300)
        elif action.action is ActionType.INPUT_TEXT:
            self.device.input_text(params["text"])
        elif action.action is ActionType.BACK:
            self.device.back()
        elif action.action is ActionType.OPEN_URL:
            self.device.open_url(params["url"])
        elif action.action is ActionType.CAPTURE_EVIDENCE:
            self.device.capture_to_gallery(params["name"])
            return f"DCIM/Camera/{params['name']}"
        elif action.action is ActionType.WAIT:
            self._pace()
        return None

    def _pace(self) -> None:
        """动作间随机节流 0.3~0.9 秒：平台有行为风控，固定节奏更可疑。"""
        self.sleep_fn(random.uniform(0.3, 0.9))

    def _finish(self, index: int, payload) -> dict:
        if isinstance(payload, str):
            action = Action("动作数达到上限", ActionType.FINISH,
                            {"result": "aborted", "reason": payload}, "结束本次 run")
            self._log(action, index, False, "达到 max_steps")
            return self._abort(payload)
        self._log(payload, index, payload.params.get("result") == "done", "finish")
        if payload.params.get("result") == "done":
            self.phase = Phase.DONE
            return {"phase": "DONE"}
        return self._abort(str(payload.params.get("reason") or "FINISH_ABORTED"))

    def _abort(self, reason: str) -> dict:
        self.phase = Phase.ABORTED
        return {"phase": "ABORTED", "reason": reason}

    def _log(self, action: Action, step: int, success: bool, observed: str,
             prefix: str | None = None) -> None:
        self.ledger.append(LedgerEntry(
            step=step, thought=action.thought, action=action.action.value,
            params=dict(action.params), expect=action.expect, observed=observed,
            success=success, screenshot_prefix=prefix))
