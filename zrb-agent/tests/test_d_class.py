"""D 类安装模板的单测：把三个真机坑写成断言（不碰 adb）。"""
from __future__ import annotations

import unittest

from zrb_agent import d_class
from zrb_agent.d_class import (InstallDriver, InstallState, classify,
                               search_uri)
from zrb_agent.perceive import parse_ui_xml

PKG = "com.heytap.market"


def xml(rows: list[tuple[str, str]], extra: str = "") -> str:
    """拼一个商店/安装器的 UiAutomator 树。

    rows = [(应用名, 按钮 rid)]，按屏幕顺序；每行前面给一个名称节点，
    与真机一致（按钮自己的 text 是空的，名字在兄弟节点里）。
    """
    body = []
    y = 400
    for name, rid in rows:
        body.append(
            f'<node class="android.widget.TextView" text="{name}" '
            f'resource-id="" bounds="[100,{y}][900,{y + 80}]" />'
        )
        body.append(
            f'<node class="android.widget.Button" text="" resource-id="{PKG}:id/{rid}" '
            f'bounds="[1200,{y}][1350,{y + 80}]" clickable="true" />'
        )
        y += 150
    return (
        '<hierarchy rotation="0"><node class="android.widget.FrameLayout" '
        f'resource-id="android:id/content" bounds="[0,0][1440,2560]">'
        + "".join(body) + extra + "</node></hierarchy>"
    )


def elements(source: str):
    return parse_ui_xml(source)


class SearchUriTest(unittest.TestCase):
    def test_chinese_is_urlencoded(self):
        # 中文必须 urlencode：Android 14 的 input text 对非 ASCII 会 NPE
        self.assertEqual(search_uri("手心输入法"),
                         "market://search?q=%E6%89%8B%E5%BF%83%E8%BE%93%E5%85%A5%E6%B3%95")

    def test_ascii_and_space(self):
        self.assertEqual(search_uri("ai li"), "market://search?q=ai%20li")


class ClassifyTest(unittest.TestCase):
    def test_picks_target_row_not_first(self):
        # 坑 2：7 个 bt_multifunc，推荐位排在前面
        src = xml([("快手", "bt_multifunc"),
                   ("和平精英", "bt_multifunc"),
                   ("手心输入法", "bt_multifunc")])
        state, target = classify(elements(src), "手心输入法")
        self.assertIs(state, InstallState.SEARCH)
        self.assertIsNotNone(target)
        # 第三行的按钮中心：y = 400 + 2*150 + 40 = 740（第一行是 440）
        self.assertEqual(target.center, (1275, 740))

    def test_target_missing_returns_none(self):
        src = xml([("快手", "bt_multifunc")])
        state, target = classify(elements(src), "手心输入法")
        self.assertIs(state, InstallState.UNKNOWN)
        self.assertIsNone(target)

    def test_search_box_text_does_not_poison_first_row(self):
        # 现场实测：搜索「手心输入法」，第 1 行是广告「王者换肤」，第 2 行才是目标。
        # 顶部搜索框里也有「手心输入法」，回溯不能越过上一行的按钮，否则会点广告。
        src = (
            '<hierarchy rotation="0"><node class="android.widget.FrameLayout" '
            'resource-id="android:id/content" bounds="[0,0][1440,2560]">'
            f'<node class="android.widget.EditText" text="手心输入法" '
            f'resource-id="{PKG}:id/search_src_text" bounds="[300,150][1100,250]" />'
            '<node class="android.widget.TextView" text="王者换肤" bounds="[300,340][900,420]" />'
            f'<node class="android.widget.Button" text="" resource-id="{PKG}:id/bt_multifunc" '
            'bounds="[1200,340][1350,420]" clickable="true" />'
            '<node class="android.widget.TextView" text="手心输入法" bounds="[300,490][900,570]" />'
            f'<node class="android.widget.Button" text="" resource-id="{PKG}:id/bt_multifunc" '
            'bounds="[1200,490][1350,570]" clickable="true" />'
            "</node></hierarchy>"
        )
        state, target = classify(elements(src), "手心输入法")
        self.assertIs(state, InstallState.SEARCH)
        # 第二行的按钮中心 y = (490+570)/2 = 530，不是第一行的 380
        self.assertEqual(target.center, (1275, 530))

    def test_installer_beats_search(self):
        src = xml([("手心输入法", "bt_multifunc")],
                  extra=f'<node text="安装" resource-id="{PKG}:id/install_confirm_ok" '
                        'bounds="[400,1600][700,1700]" clickable="true" />')
        state, target = classify(elements(src), "手心输入法")
        self.assertIs(state, InstallState.INSTALLER)
        self.assertEqual(target.center, (550, 1650))

    def test_disclaimer_dialog(self):
        src = xml([], extra=(
            f'<node text="安装提示：该应用由三方网站提供" resource-id="{PKG}:id/alertTitle" '
            'bounds="[100,1000][1300,1100]" />'
            f'<node text="取消" resource-id="{PKG}:id/button2" bounds="[100,1400][600,1500]" />'
            f'<node text="安装" resource-id="{PKG}:id/button1" bounds="[700,1400][1300,1500]" '
            'clickable="true" />'))
        state, target = classify(elements(src), "手心输入法")
        self.assertIs(state, InstallState.DISCLAIMER)
        self.assertEqual(target.center, (1000, 1450))

    def test_installing_is_not_actionable(self):
        src = xml([("手心输入法", "bt_multifunc")],
                  extra='<node text="正在下载 63%" bounds="[100,2000][900,2100]" />')
        state, target = classify(elements(src), "手心输入法")
        self.assertIs(state, InstallState.INSTALLING)
        self.assertIsNone(target)

    def test_success_by_activity(self):
        state, target = classify(elements(xml([])), "手心输入法",
                                 "com.android.packageinstaller.InstallSuccess")
        self.assertIs(state, InstallState.SUCCESS)
        self.assertIsNone(target)


class RunInstallTest(unittest.TestCase):
    """run_install 的成功判定：必须由「新包」证明，不能只看 InstallSuccess。"""

    class FakeDevice:
        def __init__(self, packages: list[set[str]], xmls: list[str],
                     activities: list[str]):
            self._packages = list(packages)
            self._xmls = list(xmls)
            self._activities = list(activities)
            self._i = 0
            self.taps: list[tuple[int, int]] = []
            self.urls: list[str] = []

        def open_url(self, url):
            self.urls.append(url)

        def _run(self, args):
            if args[:3] == ["shell", "am", "force-stop"]:
                self.reset_calls = getattr(self, "reset_calls", 0) + 1
                return ""
            index = min(self._i, len(self._packages) - 1)
            return "\n".join(f"package:{p}" for p in self._packages[index])

        def dump_ui(self, path="ui.xml"):
            source = self._xmls[min(self._i, len(self._xmls) - 1)]
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(source)

        def current_focus(self):
            return self._activities[min(self._i, len(self._activities) - 1)]

        def tap(self, x, y):
            self.taps.append((x, y))
            self._i += 1

    def _run(self, device):
        from zrb_agent.d_class import run_install
        clock = {"t": 0.0}

        def fake_now():
            return clock["t"]

        def fake_sleep(seconds):
            clock["t"] += seconds

        return run_install(device, "手心输入法", poll_s=2.0, timeout_s=30,
                           sleep=fake_sleep, now=fake_now)

    def test_stale_install_success_page_is_not_success(self):
        # 上一次跑完停在 InstallSuccess：本次第一次 dump 就看到它，但什么都没点。
        # 修前会报 ok=True（实测 20.5s「装好」但 pm list 里没有）。
        dev = self.FakeDevice(
            packages=[set(), set()],
            xmls=[xml([("手心输入法", "bt_multifunc")])],
            activities=["com.android.packageinstaller.InstallSuccess"],
        )
        out = self._run(dev)
        self.assertFalse(out.ok, "没装到东西不能报成功")
        self.assertIn("未检测到新包", out.detail)

    def test_success_requires_new_package(self):
        dev = self.FakeDevice(
            packages=[set(), {"com.xinshuru.inputmethod"}],
            xmls=[xml([("手心输入法", "bt_multifunc")]),
                  xml([])],
            activities=["com.heytap.market.search.core.activity.SearchActivity",
                        "com.android.packageinstaller.InstallSuccess"],
        )
        out = self._run(dev)
        self.assertTrue(out.ok)
        self.assertIn("com.xinshuru.inputmethod", out.detail)
        self.assertIn("SEARCH@", out.trail[0])

    def test_opens_market_search_uri(self):
        dev = self.FakeDevice(packages=[set(), set()],
                              xmls=[xml([])], activities=[""])
        self._run(dev)
        self.assertEqual(dev.urls[0],
                         "market://search?q=%E6%89%8B%E5%BF%83%E8%BE%93%E5%85%A5%E6%B3%95")

    def test_resets_leftover_installer_window(self):
        # 上一次的 InstallSuccess 窗口会抢回焦点；开跑前必须 force-stop 掉它
        dev = self.FakeDevice(packages=[set(), set()],
                              xmls=[xml([])], activities=[""])
        self._run(dev)
        self.assertGreaterEqual(getattr(dev, "reset_calls", 0), 1)


class DriverTest(unittest.TestCase):
    def test_same_state_tapped_only_once(self):
        # 坑 1：下载期间按钮不变，连点会重复触发安装
        src = xml([("手心输入法", "bt_multifunc")])
        driver = InstallDriver(want="手心输入法")
        _, first = driver.step(elements(src))
        self.assertIsNotNone(first)
        for _ in range(3):
            _, again = driver.step(elements(src))
            self.assertIsNone(again, "同一状态第二次就不该再点")
        self.assertEqual(driver.history.count(InstallState.SEARCH), 4)

    def test_full_flow_reaches_done(self):
        driver = InstallDriver(want="手心输入法")
        search = elements(xml([("快手", "bt_multifunc"),
                               ("手心输入法", "bt_multifunc")]))
        driver.step(search)
        driver.step(search)                       # 下载中，页不变
        installer = elements(xml([], extra=(
            f'<node text="安装" resource-id="{PKG}:id/install_confirm_ok" '
            'bounds="[400,1600][700,1700]" clickable="true" />')))
        driver.step(installer)
        driver.step(elements(xml([])),
                    "com.android.packageinstaller.InstallSuccess")
        self.assertTrue(driver.done)
        self.assertEqual(driver.history,
                         [InstallState.SEARCH, InstallState.SEARCH,
                          InstallState.INSTALLER, InstallState.SUCCESS])

    def test_no_disclaimer_still_advances(self):
        # 坑 3：免责弹窗不是每次都有，没有也必须能推进
        driver = InstallDriver(want="手心输入法")
        driver.step(elements(xml([("手心输入法", "bt_multifunc")])))
        installer = elements(xml([], extra=(
            f'<node text="安装" resource-id="{PKG}:id/install_confirm_ok" '
            'bounds="[400,1600][700,1700]" clickable="true" />')))
        driver.step(installer)
        self.assertEqual(driver.tapped.get(InstallState.SEARCH), 1)
        self.assertEqual(driver.tapped.get(InstallState.INSTALLER), 1)
        self.assertNotIn(InstallState.DISCLAIMER, driver.tapped)


if __name__ == "__main__":
    unittest.main()

class ApkLinkTest(unittest.TestCase):
    """外链直下 APK 通道（D 类第二条通道）。

    三个真机事实决定了这组断言：不经浏览器、只有一次确认、没有未知来源弹窗。
    """

    def test_is_apk_link(self) -> None:
        self.assertTrue(d_class.is_apk_link("http://h/x.apk"))
        self.assertTrue(d_class.is_apk_link("https://h/x.APK?a=1"))
        self.assertFalse(d_class.is_apk_link("https://h/x.apk.zip"))
        self.assertFalse(d_class.is_apk_link("https://h/download"))
        self.assertFalse(d_class.is_apk_link("market://search?q=x"))

    def test_installer_page_is_installer(self) -> None:
        xml_text = (
            "<hierarchy><node text=\"\" resource-id=\"\" bounds=\"[0,0][1440,2560]\">"
            "<node text=\"微软必应\" "
            "resource-id=\"com.android.packageinstaller:id/app_name\" "
            "bounds=\"[700,1000][900,1030]\"/>"
            "<node text=\"安装\" clickable=\"true\" "
            "resource-id=\"com.android.packageinstaller:id/install_confirm_ok\" "
            "bounds=\"[510,1610][640,1700]\"/></node></hierarchy>"
        )
        state, target = d_class.classify_apk_link(parse_ui_xml(xml_text))
        self.assertIs(state, InstallState.INSTALLER)
        self.assertIsNotNone(target)
        self.assertEqual(target.center, (575, 1655))

    def test_success_only_by_activity(self) -> None:
        state, target = d_class.classify_apk_link(
            parse_ui_xml("<hierarchy><node text=\"取消\" /></hierarchy>"),
            "com.android.packageinstaller.InstallSuccess")
        self.assertIs(state, InstallState.SUCCESS)
        self.assertIsNone(target)

    def test_installing_and_downloading(self) -> None:
        state, target = d_class.classify_apk_link(
            parse_ui_xml("<hierarchy><node text=\"正在下载…\" "
                         "bounds=\"[100,200][1300,300]\">"
                         "<node text=\"1.2 MB\" "
                         "bounds=\"[100,320][600,400]\"/></node></hierarchy>"))
        self.assertIs(state, InstallState.INSTALLING)
        self.assertIsNone(target)
        state, target = d_class.classify_apk_link(
            parse_ui_xml("<hierarchy><node text=\"\"/></hierarchy>"))
        self.assertIs(state, InstallState.DOWNLOADING)
        self.assertIsNone(target)

    def test_unknown_sources_is_not_tapped(self) -> None:
        xml_text = (
            "<hierarchy><node text=\"允许来自此来源的应用\" "
            "bounds=\"[100,900][1300,1000]\">"
            "<node text=\"允许\" clickable=\"true\" "
            "resource-id=\"com.android.settings:id/button1\" "
            "bounds=\"[100,1100][1300,1200]\"/></node></hierarchy>"
        )
        state, target = d_class.classify_apk_link(parse_ui_xml(xml_text))
        self.assertIs(state, InstallState.UNKNOWN)
        self.assertIsNone(target, "给未知来源授权是设备安全设置，必须 ask_human")

    def test_disclaimer_still_handled(self) -> None:
        xml_text = (
            "<hierarchy><node text=\"安装提示\" "
            "resource-id=\"com.heytap.market:id/alertTitle\" "
            "bounds=\"[100,1500][1300,1600]\"/>"
            "<node text=\"安装\" clickable=\"true\" "
            "resource-id=\"com.heytap.market:id/button1\" "
            "bounds=\"[1000,2300][1100,2400]\"/></hierarchy>"
        )
        state, target = d_class.classify_apk_link(parse_ui_xml(xml_text))
        self.assertIs(state, InstallState.DISCLAIMER)
        self.assertEqual(target.center, (1050, 2350))

    def test_same_installer_tapped_once(self) -> None:
        xml_text = (
            "<hierarchy><node text=\"微软必应\" "
            "resource-id=\"com.android.packageinstaller:id/app_name\"/>"
            "<node text=\"安装\" clickable=\"true\" "
            "resource-id=\"com.android.packageinstaller:id/install_confirm_ok\" "
            "bounds=\"[510,1610][640,1700]\"/></hierarchy>"
        )
        elements = parse_ui_xml(xml_text)
        driver = d_class.ApkLinkDriver()
        first = driver.step(elements)
        second = driver.step(elements)
        self.assertIsNotNone(first[1])
        self.assertIsNone(second[1], "同一个安装器页面只点一次")

    def test_rejects_non_apk_url(self) -> None:
        with self.assertRaises(ValueError):
            d_class.run_apk_link(_NullDevice(), "https://h/download")


class _NullDevice:
    """只用来触发参数校验，不该被真正调用。"""

    def _run(self, *args: str) -> str:
        raise AssertionError("参数校验应该在触到设备之前就抛错")

    def open_url(self, url: str) -> None:
        raise AssertionError("不该走到这里")

    def dump_ui(self, path: str) -> None:
        raise AssertionError("不该走到这里")

    def current_focus(self) -> str:
        raise AssertionError("不该走到这里")

    def tap(self, x: int, y: int) -> None:
        raise AssertionError("不该走到这里")

class ApkPreconditionTest(unittest.TestCase):
    """同名残留文件必须先查出来，不能等超时。"""

    def test_apk_file_name(self) -> None:
        self.assertEqual(
            d_class.apk_file_name("http://h:8765/test.apk"), "test.apk")
        self.assertEqual(
            d_class.apk_file_name("https://h/a/b/x.apk?t=1#f"), "x.apk")
        self.assertEqual(d_class.apk_file_name("https://h/"), "")

    def test_download_exists(self) -> None:
        class Dev:
            def __init__(self, listing: str) -> None:
                self.listing = listing

            def _run(self, args: list[str]) -> str:
                return self.listing

        self.assertTrue(d_class.download_exists(
            Dev("bingchina.apk\ntest.apk\n"), "test.apk"))
        self.assertFalse(d_class.download_exists(
            Dev("bingchina.apk\n"), "test.apk"))

    def test_stale_download_fails_fast(self) -> None:
        """有同名文件时立刻返回，不要空转等超时（实测空转了 182.7 秒）。"""

        class Dev:
            def __init__(self) -> None:
                self.calls: list[list[str]] = []
                self.taps = 0

            def _run(self, args: list[str]) -> str:
                self.calls.append(args)
                if args[:2] == ["shell", "pm"]:
                    return ""
                if args[:2] == ["shell", "ls"]:
                    return "test.apk\n"
                return ""

            def open_url(self, url: str) -> None:
                raise AssertionError("前置条件不满足时不该真去下载")

            def dump_ui(self, path: str) -> None:
                raise AssertionError("不该 dump")

            def current_focus(self) -> str:
                raise AssertionError("不该取焦点")

            def tap(self, x: int, y: int) -> None:
                self.taps += 1

        dev = Dev()
        out = d_class.run_apk_link(dev, "http://h/test.apk")
        self.assertFalse(out.ok)
        self.assertEqual(out.elapsed_s, 0.0)
        self.assertIn("同名文件", out.detail)
        self.assertEqual(dev.taps, 0)
