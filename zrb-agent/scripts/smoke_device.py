#!/usr/bin/env python3
"""真机冒烟：验证 device 层在真实设备上的不变量。

手动运行，不进 CI。运行前先打开一个带已聚焦输入框的页面：

    python3 scripts/smoke_device.py --adb /path/to/adb.exe

相册选图检查需要先在 App 里打开相册选择器（标题「相机胶卷」），再运行：

    python3 scripts/smoke_device.py --adb /path/to/adb.exe --gallery

每项输出一行 PASS/FAIL <检查名> <实测值>；任一 FAIL 退出码为 1。
"""
import argparse, os, sys, tempfile, time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zrb_agent.device import Device, denormalize


def png_size(path):
    """独立读取 PNG IHDR 宽高，作为 screen_size 的对照基准。"""
    with open(path, "rb") as handle:
        head = handle.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"不是 PNG 文件：{path!r}")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def focused_text(device, dump_path):
    """dump UI 树，返回当前焦点节点的文本。"""
    device.dump_ui(dump_path)
    for node in ET.parse(dump_path).iter("node"):
        if node.get("focused") == "true":
            return node.get("text", "") or ""
    return ""


def main():
    parser = argparse.ArgumentParser(description="真机冒烟")
    parser.add_argument("--adb", default="adb", help="adb 可执行文件路径")
    parser.add_argument("--gallery", action="store_true",
                        help="只跑相册选图检查；需先打开 App 的相册选择器（相机胶卷）")
    args = parser.parse_args()
    device = Device(args.adb)
    workdir = tempfile.mkdtemp(prefix="zrb-smoke-")
    probe, dump = (os.path.join(workdir, name) for name in ("probe.png", "ui.xml"))
    results = []

    def check(name, func):
        try:
            ok, actual = func()
        except Exception as exc:  # 冒烟脚本：异常也算 FAIL，继续跑完其它项
            ok, actual = False, f"{type(exc).__name__}: {exc}"
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {actual}")

    def portrait():
        width, height = device.screen_size(local_path=os.path.join(workdir, "probe2.png"))
        return width < height, f"{width}x{height}"

    def png_agrees():
        device.screencap(probe)
        pixels = png_size(probe)
        reported = device.screen_size(local_path=os.path.join(workdir, "probe2.png"))
        return reported == pixels, f"screen_size={reported} png={pixels}"

    def centre_inside():
        width, height = device.screen_size(local_path=os.path.join(workdir, "probe2.png"))
        x, y = denormalize(0.5, 0.5, width, height)
        return x < width and y < height, f"({x},{y}) in {width}x{height}"

    def ascii_input():
        device.input_text("test")
        text = focused_text(device, dump)
        return "test" in text, repr(text)

    def cjk_input():
        try:
            device.input_text("测试")
        except ValueError:
            return True, "ValueError（不静默）"
        text = focused_text(device, dump)
        return "测试" in text, repr(text)

    def gallery_pick():
        """连续截 5 张后，最早那张仍必须按 name 选中，而不是点第 1 张。"""
        name = f"zrb_smoke_{int(time.time())}"
        try:
            for index in range(5):
                device.capture_to_gallery(f"{name}_{index}")
                time.sleep(0.4)
            time.sleep(1.5)
            picked = device.pick_from_gallery(f"{name}_0")
            return picked.endswith(f"/{name}_0.png"), picked
        finally:
            device.clean_gallery(f"{name}_*")

    if args.gallery:
        check("连续截 5 张后仍按 name 选中证据图", gallery_pick)
        return 0 if all(results) else 1

    check("screen_size() 竖屏（宽 < 高）", portrait)
    check("screen_size() 与截图 PNG 头一致", png_agrees)
    check("denormalize(0.5, 0.5) 落在屏幕内", centre_inside)
    check('input_text("test") 焦点框含 test', ascii_input)
    check('input_text("测试") 不静默失败', cjk_input)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
