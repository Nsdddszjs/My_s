"""Android 设备控制层。

这一层是“手”：只负责把结构化命令翻译成 adb 调用，不含业务判断，也不做模型调用。
"""

import fnmatch
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

_GALLERY_DIR = "/sdcard/DCIM/Camera"
_MEDIA_IMAGES_URI = "content://media/external/images/media"
# 相对路径：WSL 下 adb.exe 会把 /tmp/x 解释成 Windows 的 D:\tmp\x。
_GALLERY_DUMP = f".zrb_gallery_{os.getpid()}.xml"
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def _evidence_filename(name: str) -> str:
    """把动作参数 name 规范成相册里的受控 PNG 文件名。

    只接受字母/数字/下划线/短横线/点（中文等 Unicode 字母可用），拒绝空白、
    路径分隔符和 `..`，避免转义出 DCIM/Camera 或被 adb shell 拆开；
    扩展名统一成 .png（重复传入不会翻倍）。
    """
    stem = str(name).strip()
    if stem.lower().endswith(".png"):
        stem = stem[:-4]
    if (
        not stem
        or stem.startswith(".")
        or ".." in stem
        or not re.fullmatch(r"[\w.-]+", stem)
    ):
        raise ValueError(
            f"证据文件名不合法：{name!r}；只允许字母、数字、_、-、.，不能含空白或路径分隔符"
        )
    return f"{stem}.png"


def denormalize(x_norm: float, y_norm: float, width: int, height: int) -> tuple[int, int]:
    """把 0~1 的归一化坐标还原成像素坐标。

    所有落库坐标都是 0~1，归一化换算在别的模块完成，这里只负责还原。
    """
    return round(x_norm * width), round(y_norm * height)


def _png_size(path: str) -> tuple[int, int]:
    """读取 PNG 文件 IHDR 里的宽高，避免引入图像库依赖。

    PNG 头固定为 8 字节签名 + 4 字节块长度 + 4 字节块类型 IHDR，
    随后 4 字节宽、4 字节高，均为大端序。
    """
    with open(path, "rb") as handle:
        head = handle.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError(f"不是 PNG 文件：{path!r}")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


class Device:
    """基于 adb 的 Android 设备控制层。"""

    def __init__(self, adb_path: str = "adb", serial: str = "emulator-5554"):
        self.adb_path = adb_path
        self.serial = serial
        self._last_stderr = ""

    def _run(self, args: list[str]) -> str:
        """执行 adb 命令并返回 stdout；返回码非零一律抛错。

        `adb pull` 失败时会在 stdout 报错、returncode=1 且 stderr 为空，
        只看 stderr 会把“adb 说失败”当成成功，所以这里必须检查返回码。
        """
        completed = subprocess.run(
            [self.adb_path, "-s", self.serial] + args, capture_output=True, text=True
        )
        self._last_stderr = completed.stderr or ""
        if completed.returncode != 0:
            message = (completed.stdout or completed.stderr or "").strip()
            raise RuntimeError(
                f"adb {' '.join(args)} 失败(rc={completed.returncode}): {message}"
            )
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
        """输入 ASCII 文本；空格写成 %s，非 ASCII 输入显式拒绝。

        `input text` 里字面空格会被截断，必须写成 `%s`。
        非 ASCII（中文、全角字符、emoji 等）在 Android 14 的
        InputShellCommand.sendText() 里会因 keymap 查不到字符返回 null 并 NPE，
        任何管道/脚本绕过都无效；与其静默失败，这里明确抛错，
        让调用方改用 ask_human 交由人处理。
        """
        if not text.isascii():
            raise ValueError(
                f"input_text 只支持 ASCII，收到非 ASCII 输入：{text!r}。"
                "原因：Android 14 的 `input text` 对非 ASCII 字符查不到 keymap，"
                "命令内部返回 null 并触发 NPE；base64、IME 广播等旁路未经真机验证，"
                "同样是死路。需要中文等非 ASCII 输入请改用 ask_human。"
            )
        return self._run(["shell", "input", "text", text.replace(" ", "%s")])

    def screencap(self, local_path: str, remote_path: str = "/sdcard/_shot.png") -> str:
        """截图并拉回本地。"""
        self._run(["shell", "screencap", "-p", remote_path])
        return self._run(["pull", remote_path, local_path])

    def dump_ui(self, local_path: str = "ui.xml") -> str:
        """导出 UI 层级并拉回本地。

        设备未进入空闲状态时 uiautomator 会失败，最多重试 2 次，每次间隔 800ms。
        `_run` 现在会对非零返回码抛错，因此这里把失败也纳入重试。
        """
        remote_path = "/sdcard/ui.xml"
        for attempt in range(3):
            try:
                self._run(["shell", "uiautomator", "dump", remote_path])
                if "could not get idle state" not in self._last_stderr:
                    break
            except RuntimeError:
                if attempt == 2:
                    raise
            if attempt < 2:
                time.sleep(0.8)
        else:
            raise RuntimeError("uiautomator dump 失败：设备始终未进入空闲状态")
        return self._run(["pull", remote_path, local_path])

    def capture_to_gallery(self, name: str) -> str:
        """截屏保存到相册；不先建目录时 screencap 会静默失败。

        证据图只写 `/sdcard/DCIM/Camera/`，文件名走 `_evidence_filename()`
        受控命名。相册按 date_added 倒序，刚写入的这张自然是第一张；
        不要往 `/sdcard` 根目录写调试截图再 broadcast，否则它会抢占第一位。
        """
        remote_path = f"{_GALLERY_DIR}/{_evidence_filename(name)}"
        self._run(["shell", "mkdir", "-p", _GALLERY_DIR])
        self._run(["shell", "screencap", "-p", remote_path])
        return self._run(
            [
                "shell", "am", "broadcast",
                "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                "-d", f"file://{remote_path}",
            ]
        )

    def _media_rows(self) -> list[tuple[str, str]]:
        """读 MediaStore 图片行，按 date_added 倒序返回 [(media_id, 路径)]。

        排序在 Python 侧做：adb shell 会把 `--sort "date_added DESC"` 拆成两个
        参数，不能依赖设备端排序；这里显式按 date_added、_id 倒序，与相册一致。
        """
        args = [
            "shell", "content", "query", "--uri", _MEDIA_IMAGES_URI,
            "--projection", "_id:_data:date_added",
        ]
        rows = []
        for line in self._run(args).splitlines():
            media_id = re.search(r"\b_id=(\d+)", line)
            data = re.search(r"_data=(.+?),\s*date_added=", line) or re.search(r"_data=(.+)$", line)
            added = re.search(r"date_added=(\d+)", line)
            if media_id and data:
                rows.append((
                    int(added.group(1)) if added else 0,
                    int(media_id.group(1)),
                    data.group(1).strip(),
                ))
        rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [(str(media_id), path) for _, media_id, path in rows]

    def clean_gallery(self, pattern: str) -> list[str]:
        """按文件名 glob（fnmatch）删除相册里的调试干扰图，返回被删路径。

        同时删 MediaStore 行和底层文件；pattern 可以匹配完整路径（含 `/`）
        或文件名。只处理 external storage 下的图片，避免误删其它媒体。
        """
        if not str(pattern).strip():
            raise ValueError("pattern 不能为空")
        removed = []
        for media_id, path in self._media_rows():
            filename = path.rsplit("/", 1)[-1]
            if not path.startswith(("/sdcard/", "/storage/")):
                continue
            if not (fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(filename, pattern)):
                continue
            self._run(["shell", "content", "delete", "--uri", f"{_MEDIA_IMAGES_URI}/{media_id}"])
            self._run(["shell", "rm", "-f", path])
            removed.append(path)
        return removed

    def _gallery_cells(self) -> list[tuple[int, int]]:
        """从相册选择器 UI 树里取出图片格子中心，按行优先（左上→右下）排序。"""
        local = _GALLERY_DUMP
        try:
            try:
                os.unlink(local)
            except OSError:
                pass
            self.dump_ui(local)
            if not os.path.isfile(local) or os.path.getsize(local) == 0:
                raise RuntimeError(f"dump_ui 未产生可读的相册 UI 树：{local}")
            root = ET.parse(local).getroot()
        finally:
            try:
                os.unlink(local)
            except OSError:
                pass

        parent = {child: node for node in root.iter() for child in node}
        found = []
        for node in root.iter("node"):
            resource_id = (node.get("resource-id") or "").lower()
            named = any(word in resource_id for word in ("image", "thumbnail", "picture"))
            if not named and not (node.get("class") or "").endswith("ImageView"):
                continue
            clickable = node
            while clickable is not None and clickable.get("clickable") != "true":
                clickable = parent.get(clickable)
            bounds_text = clickable.get("bounds") if clickable is not None else ""
            bounds = _BOUNDS_RE.search(bounds_text or "")
            if bounds is None:
                continue
            x1, y1, x2, y2 = (int(value) for value in bounds.groups())
            found.append(
                (0 if named else 1, x2 - x1, ((x1 + x2) // 2, (y1 + y2) // 2))
            )
        if not found:
            return []
        # 格子等宽；先按宽度丢掉顶栏图标等更窄的可点图片，再优先取带图片 id 的节点，
        # 最后按坐标排成阅读顺序（4 列网格即 date_added 倒序的格位）。
        widest = max(width for _, width, _ in found)
        wide = [(rank, center) for rank, width, center in found if width >= widest * 0.8]
        best = min(rank for rank, _ in wide)
        cells = {center for rank, center in wide if rank == best}
        return sorted(cells, key=lambda point: (point[1], point[0]))

    def pick_from_gallery(self, name: str) -> str:
        """在相册选择器里按文件名选中图片，返回被选中的媒体路径。

        选择器按 date_added 倒序、4 列网格排列；这里用同口径的 MediaStore
        排序把文件名换算成网格序号，再点当前 UI 树里对应格子的中心。
        文件名匹配失败或目标不在当前屏时抛错，绝不静默回退到「点第 1 个」。
        """
        filename = _evidence_filename(name)
        rows = self._media_rows()
        index = next(
            (
                i for i, (_, path) in enumerate(rows)
                if path.endswith(f"/DCIM/Camera/{filename}")
            ),
            None,
        )
        if index is None:
            raise LookupError(f"相册里找不到 {filename}；已拒绝静默回退到第 1 张")
        cells = self._gallery_cells()
        if not cells:
            raise RuntimeError("相册选择器里没有找到可点的图片格子")
        if index >= len(cells):
            raise LookupError(
                f"{filename} 排在第 {index + 1} 位，当前屏幕只有 {len(cells)} 个格子；"
                "需要滚动后再选，已拒绝盲点"
            )
        x, y = cells[index]
        self.tap(x, y)
        return rows[index][1]

    def open_url(self, url: str) -> str:
        """用系统默认浏览器打开链接。"""
        return self._run(
            ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url]
        )

    def screen_size(
        self, probe_path: str = "/sdcard/_probe.png", local_path: str = "_probe.png"
    ) -> tuple[int, int]:
        """读取当前屏幕像素尺寸（与 UI 树、截图同一坐标系）。

        不能用 `adb shell wm size`：它报的是面板物理方向（例如横屏 1920x1080），
        而 uiautomator 的 bounds 和截图都是旋转后的方向（例如竖屏 1080x1920）。
        这里截一张图、读 PNG 头里的真实像素宽高，三者只在同一坐标系下一致。
        本地旧文件会遮蔽本次截图，因此先删掉，并确认 adb pull 真的产生了非空文件。
        """
        local = Path(local_path)
        local.unlink(missing_ok=True)
        self._run(["shell", "screencap", "-p", probe_path])
        self._run(["pull", probe_path, str(local)])
        if not local.is_file() or local.stat().st_size == 0:
            raise RuntimeError(f"screencap 未产生本地文件：{local_path}")
        return _png_size(str(local))

    def current_focus(self) -> str:
        """返回 dumpsys window 中 mCurrentFocus= 所在的那一行。"""
        for line in self._run(["shell", "dumpsys", "window"]).splitlines():
            if "mCurrentFocus=" in line:
                return line.strip()
        return ""
