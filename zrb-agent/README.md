# zrb-agent

视觉驱动的 Android 众包悬赏执行 Agent 骨架：通过截图理解界面，代替人工完成可安全执行的小额悬赏。当前只实现骨架与**守卫层纯逻辑**（任务数据模型、伦理红牌、可行性判定），不包含 adb 设备控制与 VLM 视觉推理，不会真实执行任何任务。

## 守卫层

- `check_ethics(bounty)`：按「禁止地区 / 允许地区 → 改 IP → 伪造身份 → 虚假调研 → 地区未知」的优先级返回 `AbortReason`。`forbidden_regions` 是黑名单（含本机地区即拒），`allowed_regions` 是白名单（非空且不含本机地区即拒）。
- `check_feasibility(bounty)`：先过伦理守卫，再按旧优先级收集微信/支付宝/扫码/登录态/第三方 App 等全部门槛，返回 `(Verdict, list[AbortReason])`；`DO` / `DEFERRED` 返回空列表，多道门同时命中时全部保留，不再静默丢弃其余原因。`primary_reason(reasons)` 是兼容层，取列表首个（即旧版单值口径）。`AbortReason.kind` 把原因归为 `ENVIRONMENT` / `PLATFORM` / `RED_LINE` / `DATA` / `ECONOMIC`，上层可按组生成行动清单。
- 两阶段判定：`Bounty.steps_incomplete=True` 表示 `steps` 抓取自大厅列表预览（可能只给了第 1 步）。有效步骤 ≤1 时不再判 `DO` 或 `UNKNOWN_STEPS`，而是返回 `Verdict.DEFERRED`；伦理/地区红牌、微信/支付宝/登录/第三方 App 门槛和赏金结论（`UNKNOWN_REWARD`/`LOW_REWARD`）仍按原优先级先判。只要原因列表非空就返回 `ABORT`，不因预览不完整降级为 `DEFERRED`。`steps_incomplete` 默认 `False`，即旧行为完全不变。
- 登录态（`NEEDS_LOGIN`）三个来源：显式词（`账号`/`登录`/`手机号注册`/`绑定手机`）、隐性动作（`助力`/`关注`/`点赞`/`搜索`/`签到`/`打卡` 等只有账号才能追溯的动作）、人群限定（`新用户`/`老用户`/`回归`/`每个手机号一次`/`勿多账号` 等账号状态词，来自 `Bounty.type` / `Bounty.limite` 或步骤原文）。下载类步骤同时命中第三方 App 时，登录态优先归因——它比「装得上」更根本。
- `None` 语义：`reward`、`allowed_regions`、`forbidden_regions` 的 `None` 表示「没读到」，不是 0 元或空名单。地区未知返回 `UNKNOWN_REGIONS`，赏金未知返回 `UNKNOWN_REWARD`，都不许按「无限制」或「低赏金」处理；空列表才表示页面明确没有该项限制。已废弃的 `restricted_regions` 在 `from_dict` 中按 `allowed_regions` 兼容，两个地区字段同时非空是数据错误（`ValueError`）。
- `DEVICE_REGION = "云南"`：本机公网 IP 归属地为中国云南昆明，**换机器时必须按实际 IP 归属地修改**，否则地区限制判断会失效。

## 动作与参数

10 个动作见 `prompts/planner.md`。`PICK_FROM_GALLERY` 用 `{"name": ...}` 按文件名匹配，不用 index 参数——相册按 `date_added` 倒序，索引会随调试截图变化。

## 可做率与交付索引

「可做率」是判定规则与环境配置的函数，不是平台常量；历史「64 条全部判为不可做」是特定环境下的结论，不能当平台结论。分层说明、动作参数与已合并 PR 清单见根目录 `README-交付索引.md`。

测试：`cd zrb-agent && python -m unittest discover -s tests`

## 明确不做

不做改 IP 绕过地区限制；不做自动注册小号；不做伪造身份或伪造调研答案。
