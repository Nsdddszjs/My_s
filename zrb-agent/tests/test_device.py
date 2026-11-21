"""device.py 的单元测试，所有 adb 调用均被 mock。"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zrb_agent.device import Device, denormalize


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

    def test_open_url(self):
        with patch.object(self.device, "_run") as run:
            self.device.open_url("https://example.com")
        args = run.call_args.args[0]
        self.assertIn("android.intent.action.VIEW", args)
        self.assertIn("https://example.com", args)

    def test_screen_size(self):
        with patch.object(
            self.device, "_run", return_value="Physical size: 1080x1920"
        ) as run:
            self.assertEqual(self.device.screen_size(), (1080, 1920))
        run.assert_called_once_with(["shell", "wm", "size"])

    def test_denormalize(self):
        self.assertEqual(denormalize(0.5, 0.5, 1080, 1920), (540, 960))

    def test_input_text_non_ascii_uses_base64(self):
        with patch.object(self.device, "_run") as run:
            self.device.input_text("你好")
        args = run.call_args.args[0]
        self.assertIn("base64", args)
        self.assertIn("-d", args)
        self.assertIn("5L2g5aW9", args)


if __name__ == "__main__":
    unittest.main()
