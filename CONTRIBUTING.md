Welcome contributions.

## 设备层改动

`zrb-agent/zrb_agent/device.py` 的行为改动，必须在真机上跑一次再合并：mock 单测只能验证命令拼装，验证不了设备返回的真实坐标系与编码行为（例如 `wm size` 报面板物理方向，而 UI 树和截图是旋转后的方向）。
