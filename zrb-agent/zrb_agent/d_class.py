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

两条通道：

* **商店通道** ``run_install(device, app_name)``：`market://search` → 商店搜索
  结果页挑行 → 商店免责弹窗（可选）→ 系统安装器 → 两次确认。
* **外链直下通道** ``run_apk_link(device, url)``：``open_url`` 一个 .apk 直链
  → 系统下载器 → **直接**弹系统安装器 → 一次确认。全程没有浏览器窗口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import quote, urlsplit

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
    # 外链直下 APK 通道专用：链接已经打开，但安装器还没出现（系统下载器在拉
    # 文件）。和 INSTALLING 的区别是「连页面都还没到」，不是「点了没反应」。
    DOWNLOADING = "DOWNLOADING"
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


INSTALLER_PACKAGE = "com.android.packageinstaller"


def reset_installer(device) -> None:
    """开跑前清掉可能残留的系统安装器窗口。

    实测：上一次安装结束停在 `InstallSuccess`，那个 Activity 会一直活着；
    即使按 HOME 回到桌面，下一次 `open_url` 之后它又会抢回焦点。
    于是本次一次都没装东西，`current_focus()` 却报 `InstallSuccess` ——
    只看页面判成功就会假成功（20.5 秒「装好」但 `pm list` 里没有）。
    """
    try:
        device._run(["shell", "am", "force-stop", INSTALLER_PACKAGE])
    except RuntimeError:
        pass


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

    **成功必须由「新包」证明，不能只看 InstallSuccess 页面**：
    上一次运行结束时若停在 `InstallSuccess`，本次第一次 dump 就会看到它，
    于是什么都没做也报成功。实测踩过 —— 20.5 秒「装好」但 `pm list` 里没有。
    """
    driver = InstallDriver(want=app_name)
    reset_installer(device)
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

        # 页面停在 InstallSuccess 但本次一次都没点过 → 是上一次运行残留，
        # 不能当成功；跳出去重新进入搜索页。
        if ("InstallSuccess" in activity
                and not any(driver.tapped.values())):
            activity = ""

        state, target = driver.step(parse_ui_xml(xml_text), activity)
        trail.append(f"{state.value}@{int(now() - started)}s")

        if state is InstallState.SUCCESS:
            break
        if target is not None:
            device.tap(*target.center)
        # 每轮直接查包：装完后焦点常常停在商店页/桌面，activity 不再是
        # InstallSuccess，只靠页面判成功会空转到超时。
        if installed_packages(device) - before:
            trail.append(f"NEW_PACKAGE@{int(now() - started)}s")
            break
        # 无论点没点都要等一轮：不点的时候若也不 sleep，循环会空转，
        # 超时判断基于 wall clock 就永远不前进（写单测时直接死循环，实测）。
        sleep(poll_s)

    new = installed_packages(device) - before
    ok = bool(new)
    if new:
        detail = f"新增包：{', '.join(sorted(new))}"
        final_state = InstallState.SUCCESS
    elif driver.done:
        detail = "页面显示安装成功但未检测到新包（可能是上一次运行留下的 InstallSuccess）"
        final_state = driver.history[-1] if driver.history else InstallState.UNKNOWN
    else:
        detail = "未检测到新包"
        final_state = driver.history[-1] if driver.history else InstallState.UNKNOWN
    return InstallOutcome(ok=ok, state=final_state,
                          elapsed_s=round(now() - started, 1),
                          trail=trail, detail=detail)

APK_SUFFIX = ".apk"
# 出现这些字样说明系统在问「是否允许此来源安装应用」，属于设备安全设置，
# 必须 ask_human，不能自己点允许。
_UNKNOWN_SOURCES_MARKERS = (
    "安装未知应用", "未知来源", "允许来自此来源", "unknown sources",
)


def is_apk_link(url: str) -> bool:
    """链接本身是不是一个 APK 直链（忽略 query 与大小写）。"""
    return url.split("?", 1)[0].split("#", 1)[0].lower().endswith(APK_SUFFIX)


def apk_file_name(url: str) -> str:
    """URL 里最后一段路径 —— 也就是系统下载器存盘用的文件名。"""
    path = urlsplit(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


DOWNLOAD_DIR = "/sdcard/Download"


def download_exists(device, name: str) -> bool:
    """下载目录里是否已经有同名文件。

    实测：有同名文件时系统下载器**不会**再弹安装器，页面停在无字黑页，
    模板会一直等到超时（实测 182.7 秒 45 轮全 DOWNLOADING）。
    所以要提前查，而不是等超时才发现。
    """
    if not name:
        return False
    try:
        listing = device._run(["shell", "ls", DOWNLOAD_DIR])
    except RuntimeError:
        return False
    return name in listing.split()


def classify_apk_link(
    elements: list[UiElement], activity: str = ""
) -> tuple[InstallState, UiElement | None]:
    """外链直下通道的状态判定（纯函数）。

    比商店通道少一个 SEARCH 阶段：没有搜索结果页要挑行，链接点了就是等
    安装器出现。`UNKNOWN` 在这里的含义是「既没看到安装器、也没有下载中
    的字样」—— 可能是还在下载，也可能是落到了别的页面，交给上层继续观察。
    """
    if "InstallSuccess" in activity:
        return InstallState.SUCCESS, None

    if any("InstallInstalling" in activity for _ in (0,)):
        return InstallState.INSTALLING, None

    joined = " ".join(_label(element) for element in elements if _label(element))
    if any(marker in joined for marker in _UNKNOWN_SOURCES_MARKERS):
        # 交给上层 ask_human：这是设备级安全设置，不是任务步骤
        return InstallState.UNKNOWN, None
    if any(marker in joined for marker in _INSTALLING_MARKERS):
        return InstallState.INSTALLING, None

    installer = _find(elements, RID_INSTALL_OK)
    if installer is not None:
        return InstallState.INSTALLER, installer

    alert = _find(elements, RID_ALERT_TITLE)
    ok = _find(elements, RID_ALERT_OK)
    if alert is not None and ok is not None:
        return InstallState.DISCLAIMER, ok

    return InstallState.DOWNLOADING, None


@dataclass
class ApkLinkDriver:
    """外链直下通道的驱动器：每个可动作状态只推进一次。

    坑与商店通道同源：`InstallSuccess` 会残留抢焦点，安装器确认页也可能
    停留多轮。所以「点过一次就不再点」，剩下交给 `pm list packages` 判定。
    """

    tapped: dict[InstallState, int] = field(default_factory=dict)
    history: list[InstallState] = field(default_factory=list)
    installer_ref: str | None = None

    def step(
        self, elements: list[UiElement], activity: str = ""
    ) -> tuple[InstallState, UiElement | None]:
        state, target = classify_apk_link(elements, activity)
        self.history.append(state)
        if target is None:
            return state, None
        # 同一个安装器页面（同一个 app_name）只点一次
        key = self._key(elements, state)
        if self.tapped.get(state, 0) >= 1 and key == self.installer_ref:
            return state, None
        self.tapped[state] = self.tapped.get(state, 0) + 1
        self.installer_ref = key
        return state, target

    @staticmethod
    def _key(elements: list[UiElement], state: InstallState) -> str | None:
        if state is not InstallState.INSTALLER:
            return None
        for element in elements:
            if _short_rid(element) == "app_name" and _label(element):
                return _label(element)
        return None

    @property
    def done(self) -> bool:
        return bool(self.history) and self.history[-1] is InstallState.SUCCESS


def run_apk_link(
    device,
    url: str,
    *,
    dump_path: str = "d_class_apk.xml",
    timeout_s: float = 180.0,
    poll_s: float = 2.0,
    sleep=__import__("time").sleep,
    now=__import__("time").monotonic,
) -> InstallOutcome:
    """跑外链直下 APK 的安装链路：`open_url` → 系统安装器 → 一次确认。

    真机事实（服务本机 APK 实测）：VIEW 打开 `.apk` 直链**不经过浏览器**，
    系统下载器拉完直接弹 `PackageInstallerActivity`，点 `install_confirm_ok`
    即装好；全程只有一次确认，也没有「安装未知应用」授权弹窗。

    与 `run_install` 相同的两条纪律：开跑前 `reset_installer`，
    **成功只由新包证明**。
    """
    if not is_apk_link(url):
        raise ValueError(f"不是 APK 直链：{url}")

    driver = ApkLinkDriver()
    reset_installer(device)

    stale = apk_file_name(url)
    if download_exists(device, stale):
        # 不自动删用户文件：删下载目录是不可逆操作，且这属于「环境不满足」，
        # 应当报出来让人清理，而不是替人清。
        return InstallOutcome(
            ok=False, state=InstallState.DOWNLOADING, elapsed_s=0.0, trail=[],
            detail=(f"下载目录已有同名文件 {stale}；系统下载器不会再弹安装提示，"
                    f"请先清理 {DOWNLOAD_DIR}/{stale} 再重试"))

    before = installed_packages(device)
    started = now()
    trail: list[str] = []
    dump_failures = 0

    device.open_url(url)
    sleep(poll_s)

    while now() - started < timeout_s:
        try:
            device.dump_ui(dump_path)
            with open(dump_path, encoding="utf-8", errors="replace") as handle:
                xml_text = handle.read()
            dump_failures = 0
        except (RuntimeError, OSError) as exc:
            dump_failures += 1
            trail.append(f"dump 失败第 {dump_failures} 次：{exc}")
            if dump_failures >= 3:
                trail.append("连续 3 次 dump 失败，提前结束")
                break
            sleep(poll_s)
            continue

        activity = ""
        try:
            activity = device.current_focus()
        except RuntimeError:
            pass

        # 一次都没点过就看到 InstallSuccess → 上一次运行残留，不能算成功
        if "InstallSuccess" in activity and not any(driver.tapped.values()):
            activity = ""

        state, target = driver.step(parse_ui_xml(xml_text), activity)
        trail.append(f"{state.value}@{int(now() - started)}s")

        if state is InstallState.SUCCESS:
            break
        if target is not None:
            device.tap(*target.center)
        # 每轮直接查包：装完后焦点常常回到浏览器黑页，activity 不再是
        # InstallSuccess，只靠页面判成功会空转到超时（实测空转 170 秒）。
        if installed_packages(device) - before:
            trail.append(f"NEW_PACKAGE@{int(now() - started)}s")
            break
        sleep(poll_s)

    new = installed_packages(device) - before
    ok = bool(new)
    if new:
        detail = f"新增包：{', '.join(sorted(new))}"
        final_state = InstallState.SUCCESS
    elif driver.done:
        detail = "页面显示安装成功但未检测到新包（可能是上一次运行留下的 InstallSuccess）"
        final_state = driver.history[-1] if driver.history else InstallState.UNKNOWN
    else:
        detail = "未检测到新包"
        final_state = driver.history[-1] if driver.history else InstallState.UNKNOWN
    return InstallOutcome(ok=ok, state=final_state,
                          elapsed_s=round(now() - started, 1),
                          trail=trail, detail=detail)
