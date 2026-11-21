"""Android 设备控制层。

这一层是“手”：只负责把结构化命令翻译成 adb 调用，不含业务判断，也不做模型调用。
"""

import base64
import re
import subprocess
import time


def denormalize(x_norm: float, y_norm: float, width: int, height: int) -> tuple[int, int]:
    """把 0~1 的归一化坐标还原成像素坐标。

    所有落库坐标都是 0~1，归一化换算在别的模块完成，这里只负责还原。
    """
    return round(x_norm * width), round(y_norm * height)


class Device:
    """基于 adb 的 Android 设备控制层。"""

    def __init__(self, adb_path: str = "adb", serial: str = "emulator-5554"):
        self.adb_path = adb_path
        self.serial = serial
        self._last_stderr = ""

    def _run(self, args: list[str]) -> str:
        """执行 adb 命令并返回 stdout；stderr 留给调用方检查。"""
        completed = subprocess.run(
            [self.adb_path, "-s", self.serial] + args, capture_output=True, text=True
        )
        self._last_stderr = completed.stderr or ""
        return completed.stdout or ""

    def tap(self, x: int, y: int) -> str:
        """点击像素坐标；坐标换算由调用方负责。"""
        return self._run(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        """从 (x1, y1) 滑到 (x2, y2)，duration_ms 为滑动时长。"""
        return self._run(
            ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)]
        )

    def keyevent(self, code: int) -> str:
        """发送按键事件。"""
        return self._run(["shell", "input", "keyevent", str(code)])

    def back(self) -> str:
        """返回键（keyevent 4）。"""
        return self.keyevent(4)

    def input_text(self, text: str) -> str:
        """输入文本。

        纯 ASCII 直接走 input text；中文等非 ASCII 字符先转 UTF-8 再 base64，
        由设备端解码后交给 input text，避免 shell 编码问题。
        """
        if text.isascii():
            return self._run(["shell", "input", "text", text])
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        return self._run(
            ["shell", "echo", encoded, "|", "base64", "-d", "|", "input", "text"]
        )

    def screencap(self, local_path: str, remote_path: str = "/sdcard/_shot.png") -> str:
        """截图并拉回本地。"""
        self._run(["shell", "screencap", "-p", remote_path])
        return self._run(["pull", remote_path, local_path])

    def dump_ui(self, local_path: str = "ui.xml") -> str:
        """导出 UI 层级并拉回本地。

        设备未进入空闲状态时 uiautomator 会失败，最多重试 2 次，每次间隔 800ms。
        """
        remote_path = "/sdcard/ui.xml"
        for attempt in range(3):
            self._run(["shell", "uiautomator", "dump", remote_path])
            if "could not get idle state" not in self._last_stderr:
                break
            if attempt < 2:
                time.sleep(0.8)
        else:
            raise RuntimeError("uiautomator dump 失败：设备始终未进入空闲状态")
        return self._run(["pull", remote_path, local_path])

    def capture_to_gallery(self, name: str) -> str:
        """截屏保存到相册；不先建目录时 screencap 会静默失败。"""
        remote_path = f"/sdcard/DCIM/Camera/{name}.png"
        self._run(["shell", "mkdir", "-p", "/sdcard/DCIM/Camera"])
        self._run(["shell", "screencap", "-p", remote_path])
        return self._run(
            [
                "shell", "am", "broadcast",
                "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                "-d", f"file://{remote_path}",
            ]
        )

    def open_url(self, url: str) -> str:
        """用系统默认浏览器打开链接。"""
        return self._run(
            ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url]
        )

    def screen_size(self) -> tuple[int, int]:
        """读取屏幕分辨率，解析 wm size 的 Physical size（兼容 Override size）。"""
        output = self._run(["shell", "wm", "size"])
        match = re.search(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", output)
        if not match:
            raise ValueError(f"无法解析屏幕尺寸：{output!r}")
        return int(match.group(1)), int(match.group(2))

    def current_focus(self) -> str:
        """返回 dumpsys window 中 mCurrentFocus= 所在的那一行。"""
        for line in self._run(["shell", "dumpsys", "window"]).splitlines():
            if "mCurrentFocus=" in line:
                return line.strip()
        return ""
