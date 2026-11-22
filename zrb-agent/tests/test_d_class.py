"""D 类安装模板的单测：把三个真机坑写成断言（不碰 adb）。"""
from __future__ import annotations

import unittest

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