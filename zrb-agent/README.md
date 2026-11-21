# zrb-agent

视觉驱动的 Android 众包悬赏执行 Agent 骨架：通过截图理解界面，代替人工完成可安全执行的小额悬赏。当前只实现骨架与**守卫层纯逻辑**（任务数据模型、伦理红牌、可行性判定），不包含 adb 设备控制与 VLM 视觉推理，不会真实执行任何任务。

## 守卫层

- `check_ethics(bounty)`：按「禁止地区 / 允许地区 → 改 IP → 伪造身份 → 虚假调研 → 地区未知」的优先级返回 `AbortReason`。`forbidden_regions` 是黑名单（含本机地区即拒），`allowed_regions` 是白名单（非空且不含本机地区即拒）。
- `check_feasibility(bounty)`：先过伦理守卫，再拦截微信/支付宝/扫码/第三方 App/未知步骤/未知赏金/低奖励，返回 `(Verdict, AbortReason)`。
- `None` 语义：`reward`、`allowed_regions`、`forbidden_regions` 的 `None` 表示「没读到」，不是 0 元或空名单。地区未知返回 `UNKNOWN_REGIONS`，赏金未知返回 `UNKNOWN_REWARD`，都不许按「无限制」或「低赏金」处理；空列表才表示页面明确没有该项限制。已废弃的 `restricted_regions` 在 `from_dict` 中按 `allowed_regions` 兼容，两个地区字段同时非空是数据错误（`ValueError`）。
- `DEVICE_REGION = "云南"`：本机公网 IP 归属地为中国云南昆明，**换机器时必须按实际 IP 归属地修改**，否则地区限制判断会失效。

测试：`cd zrb-agent && python -m unittest discover -s tests`

## 明确不做

不做改 IP 绕过地区限制；不做自动注册小号；不做伪造身份或伪造调研答案。
