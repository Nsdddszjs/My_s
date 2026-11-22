"""D 类（下载装 App）执行模板：`market://search` → 商店安装 → 系统安装器。

为什么单独成模块：D 类在 51 条真机语料里占可做金额的大头，但踩过三个
「看起来能点，其实不该点」的坑，纯靠 planner 每次推理必然重复犯错：

1. **下载期间搜索结果页不变**。`bt_multifunc` 不消失、rid 与 bounds 都不变，
   于是「看见安装按钮就点」会连点同一个按钮（实测连点 3 次），行为未定义。
2. **搜索结果页有 7 个 `bt_multifunc`**（目标 1 个 + 「精选应用」推荐位 6 个）。
   「点第一个」只在目标恰好排第一时成立。
3. **商店「三方来源」免责弹窗不是每次都有**（ai荔枝那次有，手心输入法没有）。

因此本模块把「当前处在哪个状态、这一次该点哪里」写成纯函数 + 一个
「每个状态只推进一次」的驱动器，先在没有设备的情况下可断言，再交给
`device` 执行。真实链路（手心输入法，37.7 秒装完）已真机验证过。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import quote

from .perceive import UiElement, parse_ui_xml

MARKET_SEARCH = "market://search?q={}"

# 商店搜索结果行（文字在子节点里，节点自身 text 为空）
RID_SEARCH_ROW = "bt_multifunc"
# 商店「安装提示：该应用由三方网站提供…」弹窗
RID_ALERT_TITLE = "alertTitle"
RID_ALERT_OK = "button1"
# 系统安装器
RID_INSTALL_OK = "install_confirm_ok"

# 搜结果行往上回溯多少个节点能覆盖「图标 / 名称 / 评分 / 安装量 / 简介」
_CONTEXT_LOOKBACK = 18
# 这些字样的行说明还在下载/安装，不能重复点
_INSTALLING_MARKERS = ("正在下载", "下载中", "正在安装", "安装中", "等待下载", "已暂停")


class InstallState(Enum):
    """一次 dump 能识别的安装阶段。"""

    SEARCH = "SEARCH"          # 商店搜索结果页，需要挑目标那一行
    DISCLAIMER = "DISCLAIMER"  # 商店自己的三方来源免责弹窗
    INSTALLER = "INSTALLER"    # 系统 PackageInstaller 确认页
    INSTALLING = "INSTALLING"  # 下载/安装进行中（点不出新东西）
    SUCCESS = "SUCCESS"        # 已在 InstallSuccess 页或目标包已装上
    UNKNOWN = "UNKNOWN"        # 既无可动作项也不在进行中，继续等


def search_uri(app_name: str) -> str:
    """商店搜索深链。中文必须 urlencode —— Android 14 的 `input text` 对非 ASCII 会 NPE。"""
    return MARKET_SEARCH.format(quote(app_name, safe=""))


def _short_rid(element: UiElement) -> str:
    """只取 resource-id 最后一段：真机形态是 `包名:id/字段名`。"""
    return element.resource_id.rsplit("/", 1)[-1]


def _label(element: UiElement) -> str:
    return element.text or element.desc


def _find(elements: list[UiElement], rid: str) -> UiElement | None:
    for element in elements:
        if _short_rid(element) == rid:
            return element
    return None


def _target_row(elements: list[UiElement], want: str) -> UiElement | None:
    """在搜索结果里找「名字离按钮最近」的那一行。

    只看按钮自己的 text 不行（实测为空），必须往上回溯 —— 那里才有
    「应用名 / 评分 / 安装量 / 一句话简介」。

    两个必须处理的污染源：

    * **顶部搜索框**里就有 `want`。若只按「上下文包含 want」判，
      第一行的上下文会一路回溯到搜索框，于是每一行都命中第一行 ——
      而现场第一行经常是广告位（实测搜索「手心输入法」，第 1 行是「王者换肤」广告）。
    * **上一行的按钮**也属于上一行的内容，回溯不能跨过去。

    因此这里用「**距离最近的匹配**」而不是「第一个匹配」：目标行的应用名
    紧贴在按钮上方（距离通常 1~2），搜索框与广告行都离得更远。
    """
    candidates: list[tuple[int, UiElement]] = []
    previous_row = -1
    for index, element in enumerate(elements):
        if _short_rid(element) != RID_SEARCH_ROW:
            continue
        start = max(previous_row + 1, index - _CONTEXT_LOOKBACK)
        previous_row = index
        for offset, prev in enumerate(elements[start:index], start=start):
            if want in _label(prev):
                candidates.append((index - offset, element))
                break
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def classify(
    elements: list[UiElement], want: str, activity: str = ""
) -> tuple[InstallState, UiElement | None]:
    """判定当前阶段，并给出**该点的那一个**元素（没有就是 None）。

    `activity` 只在判断 SUCCESS/INSTALLING 时使用；纯函数，方便单测。
    """
    if "InstallSuccess" in activity:
        return InstallState.SUCCESS, None

    installer = _find(elements, RID_INSTALL_OK)
    if installer is not None:
        return InstallState.INSTALLER, installer

    alert = _find(elements, RID_ALERT_TITLE)
    ok = _find(elements, RID_ALERT_OK)
    if alert is not None and ok is not None:
        return InstallState.DISCLAIMER, ok

    # 下载/安装标记要排在 SEARCH 之前：真机下载期间搜索结果页**不变**，
    # 行按钮还在，此时真实状态是「正在下载」而不是「可以点安装」。
    # 代价是万一把推荐位的「等待下载」字样当成进行中，也只是多等一轮（stall），
    # 不会点错东西 —— 比连点同一个安装按钮安全。
    joined = " ".join(_label(element) for element in elements if _label(element))
    if "InstallInstalling" in activity or any(
        marker in joined for marker in _INSTALLING_MARKERS
    ):
        return InstallState.INSTALLING, None

    row = _target_row(elements, want)
    if row is not None:
        return InstallState.SEARCH, row

    return InstallState.UNKNOWN, None


@dataclass
class InstallDriver:
    """每个可动作状态只推进一次。

    这是为了挡住坑 1：下载期间搜索结果页不变，若允许反复点就会连点同一个
    安装按钮。状态没变化就说明「上一次点击还没生效」，应当等待而不是再点。
    """

    want: str
    tapped: dict[InstallState, int] = field(default_factory=dict)
    history: list[InstallState] = field(default_factory=list)

    def step(self, elements: list[UiElement], activity: str = "") -> tuple[
        InstallState, UiElement | None
    ]:
        state, target = classify(elements, self.want, activity)
        self.history.append(state)
        if target is None:
            return state, None
        if self.tapped.get(state, 0) >= 1:
            return state, None
        self.tapped[state] = self.tapped.get(state, 0) + 1
        return state, target

    @property
    def done(self) -> bool:
        return bool(self.history) and self.history[-1] is InstallState.SUCCESS


@dataclass
class InstallOutcome:
    """一次安装的结局。"""

    ok: bool
    state: InstallState
    elapsed_s: float
    trail: list[str]
    detail: str = ""


def installed_packages(device) -> frozenset[str]:
    """`pm list packages -3` 的第三方包名集合（含本机预装的商店）。"""
    raw = device._run(["shell", "pm", "list", "packages", "-3"])
    return frozenset(
        line.split(":", 1)[1].strip()
        for line in raw.splitlines()
        if line.startswith("package:") and ":" in line
    )


def run_install(
    device,
    app_name: str,
    *,
    dump_path: str = "d_class.xml",
    timeout_s: float = 150.0,
    poll_s: float = 2.0,
    sleep=__import__("time").sleep,
    now=__import__("time").monotonic,
) -> InstallOutcome:
    """跑完整条 D 类链路：商店搜索 → 挑目标 → 装 → 系统安装器确认。

    只做「装 App」这一段。装完还要登录的（实测 21 条 D 类里 6 条是这样）
    不在本模板范围内 —— 那需要 OTP，必须由人给码，调用方拿到 `ok=True`
    之后应当再感知一次首启页，看到手机号登录墙就 `ask_human`。
    """
    driver = InstallDriver(want=app_name)
    before = installed_packages(device)
    started = now()
    trail: list[str] = []
    dump_failures = 0

    device.open_url(search_uri(app_name))
    sleep(poll_s)

    while now() - started < timeout_s:
        try:
            # dump_path 必须是**相对路径**：adb.exe 是 Windows 程序，
            # 传 /tmp/x.xml 会被当成 D:\tmp\x.xml，pull 直接失败（实测）。
            device.dump_ui(dump_path)
            with open(dump_path, encoding="utf-8", errors="replace") as handle:
                xml_text = handle.read()
            dump_failures = 0
        except (RuntimeError, OSError) as exc:
            dump_failures += 1
            trail.append(f"dump 失败第 {dump_failures} 次：{exc}")
            if dump_failures >= 3:
                # 连挂三次就没必要继续等满超时；返回现场让人看一眼
                trail.append("连续 3 次 dump 失败，提前结束")
                break
            sleep(poll_s)
            continue

        activity = ""
        try:
            activity = device.current_focus()
        except RuntimeError:
            pass

        state, target = driver.step(parse_ui_xml(xml_text), activity)
        trail.append(f"{state.value}@{int(now() - started)}s")

        if state is InstallState.SUCCESS:
            break
        if target is not None:
            device.tap(*target.center)
            sleep(poll_s)

    new = installed_packages(device) - before
    ok = driver.done or bool(new)
    detail = f"新增包：{', '.join(sorted(new))}" if new else "未检测到新包"
    return InstallOutcome(ok=ok, state=driver.history[-1] if driver.history
                          else InstallState.UNKNOWN,
                          elapsed_s=round(now() - started, 1),
                          trail=trail, detail=detail)