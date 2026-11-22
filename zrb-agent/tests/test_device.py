"""device.py 的单元测试，所有 adb 调用均被 mock。"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zrb_agent.device import Device, denormalize

GALLERY_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<hierarchy rotation="0">
  <node class="android.widget.ImageView" clickable="true" bounds="[0,300][200,500]" />
  <node class="android.widget.ImageView" clickable="true" bounds="[200,300][400,500]" />
  <node class="android.widget.ImageView" clickable="true" bounds="[400,300][600,500]" />
</hierarchy>"""

MEDIA_ROWS = (
    "Row: 0 _id=8, _data=/storage/emulated/0/Download/ev1.png, date_added=100\n"
    "Row: 1 _id=9, _data=/storage/emulated/0/DCIM/Camera/ev1.png, date_added=200\n"
    "Row: 2 _id=10, _data=/storage/emulated/0/DCIM/Camera/newer.png, date_added=300\n"
)


class DeviceTest(unittest.TestCase):
    def setUp(self):
        self.device = Device()

    def test_tap(self):
        with patch.object(self.device, "_run") as run:
            self.device.tap(540, 960)
        run.assert_called_once_with(["shell", "input", "tap", "540", "960"])

    def test_swipe(self):
        with patch.object(self.device, "_run") as run:
            self.device.swipe(10, 20, 30, 40)
        run.assert_called_once_with(
            ["shell", "input", "swipe", "10", "20", "30", "40", "300"]
        )

    def test_back(self):
        with patch.object(self.device, "_run") as run:
            self.device.back()
        self.assertEqual(run.call_args.args[0], ["shell", "input", "keyevent", "4"])

    def test_capture_to_gallery(self):
        with patch.object(self.device, "_run") as run:
            self.device.capture_to_gallery("ev1")
        self.assertEqual(run.call_count, 3)
        first, second, third = [call.args[0] for call in run.call_args_list]
        self.assertIn("mkdir", first)
        self.assertIn("-p", first)
        self.assertIn("/sdcard/DCIM/Camera", first)
        self.assertEqual(second, ["shell", "screencap", "-p", "/sdcard/DCIM/Camera/ev1.png"])
        self.assertIn("MEDIA_SCANNER_SCAN_FILE", " ".join(third))
        self.assertIn("file:///sdcard/DCIM/Camera/ev1.png", third)

    def test_capture_to_gallery_controlled_name(self):
        with patch.object(self.device, "_run") as run:
            self.device.capture_to_gallery("ev1.png")
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["shell", "screencap", "-p", "/sdcard/DCIM/Camera/ev1.png"],
        )

    def test_capture_to_gallery_rejects_path_traversal(self):
        with patch.object(self.device, "_run") as run:
            with self.assertRaises(ValueError):
                self.device.capture_to_gallery("../evil")
        run.assert_not_called()

    def test_clean_gallery_only_matching_rows(self):
        rows = (
            "Row: 0 _id=7, _data=/sdcard/DCIM/Camera/_shot_debug.png\n"
            "Row: 1 _id=8, _data=/sdcard/DCIM/Camera/keep.png\n"
        )
        with patch.object(self.device, "_run", side_effect=[rows, "", ""]) as run:
            removed = self.device.clean_gallery("*_shot_*")
        self.assertEqual(["/sdcard/DCIM/Camera/_shot_debug.png"], removed)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertIn(
            ["shell", "content", "delete", "--uri",
             "content://media/external/images/media/7"], calls
        )
        self.assertIn(["shell", "rm", "-f", "/sdcard/DCIM/Camera/_shot_debug.png"], calls)
        self.assertNotIn(["shell", "rm", "-f", "/sdcard/DCIM/Camera/keep.png"], calls)

    def test_pick_from_gallery_missing_name_raises(self):
        with patch.object(self.device, "_run", return_value=MEDIA_ROWS) as run:
            with self.assertRaises(LookupError):
                self.device.pick_from_gallery("missing")
        self.assertFalse(
            any(call.args[0][:3] == ["shell", "input", "tap"] for call in run.call_args_list)
        )

    def test_pick_from_gallery_matches_name_to_grid_cell(self):
        def fake_dump(path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(GALLERY_XML)

        with patch.object(self.device, "_run", return_value=MEDIA_ROWS) as run, \
                patch.object(self.device, "dump_ui", side_effect=fake_dump):
            picked = self.device.pick_from_gallery("ev1.png")
        self.assertEqual("/storage/emulated/0/DCIM/Camera/ev1.png", picked)
        self.assertEqual(["shell", "input", "tap", "300", "400"], run.call_args.args[0])

    def test_open_url(self):
        with patch.object(self.device, "_run") as run:
            self.device.open_url("https://example.com")
        args = run.call_args.args[0]
        self.assertIn("android.intent.action.VIEW", args)
        self.assertIn("https://example.com", args)

    def test_screen_size_uses_png_not_wm_size(self):
        """wm size 报横屏 1920x1080 时，screen_size 必须返回截图/UI 树的竖屏尺寸。"""
        png_1080x1920 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x04\x38"  # width  = 1080
            b"\x00\x00\x07\x80"  # height = 1920
            b"\x08\x02\x00\x00\x00"
        )
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(png_1080x1920)
            path = handle.name
        self.addCleanup(os.unlink, path)
        with patch.object(
            self.device, "_run", side_effect=["Physical size: 1920x1080", ""]
        ) as run:
            self.assertEqual(self.device.screen_size(local_path=path), (1080, 1920))
        first, second = [call.args[0] for call in run.call_args_list]
        self.assertEqual(first, ["shell", "screencap", "-p", "/sdcard/_probe.png"])
        self.assertEqual(second, ["pull", "/sdcard/_probe.png", path])

    def test_screen_size_rejects_non_png(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(b"not a png")
            path = handle.name
        self.addCleanup(os.unlink, path)
        with patch.object(self.device, "_run"):
            with self.assertRaises(ValueError):
                self.device.screen_size(local_path=path)

    def test_denormalize_center_is_center(self):
        x, y = denormalize(0.5, 0.5, 1080, 1920)
        self.assertEqual((x, y), (540, 960))
        self.assertLess(x, 1080)
        self.assertLess(y, 1920)

    def test_input_text_ascii(self):
        with patch.object(self.device, "_run") as run:
            self.device.input_text("abc123")
        run.assert_called_once_with(["shell", "input", "text", "abc123"])

    def test_input_text_rejects_non_ascii(self):
        with patch.object(self.device, "_run") as run:
            with self.assertRaises(ValueError) as ctx:
                self.device.input_text("你好")
        message = str(ctx.exception)
        self.assertIn("ask_human", message)
        self.assertIn("NPE", message)
        self.assertIn("keymap", message)
        run.assert_not_called()

    def test_input_text_replaces_space(self):
        with patch.object(self.device, "_run") as run:
            self.device.input_text("aa bb")
        run.assert_called_once_with(["shell", "input", "text", "aa%sbb"])


if __name__ == "__main__":
    unittest.main()
