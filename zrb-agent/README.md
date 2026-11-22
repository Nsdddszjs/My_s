# zrb-agent

视觉驱动的 Android 众包悬赏执行 Agent：截图 → 判定这单能不能做 →  Planner 逐步决定动作 → adb 执行 → 校验 → 记账。

做的事：把「这单能不能做、差什么条件、下一步点什么」从人脑里搬到可测试的代码里。
不做的事：不做通用 GUI 代理，不做无人值守刷单，不自带 VLM——视觉理解由外部的 planner 模型承担，本仓库只提供它需要的感知结果、动作空间与守卫。

## 架构与实现状态

| 层 | 职责 | 状态 |
|---|---|---|
| TaskSpec | `Bounty` / `Step` 数据模型，`None` 表示未知 | ✅ `schema.py` |
| DevicePort | 截图、dump、点击、输入、相册选图、证据入库 | ✅ `device.py` |
| Perceive | 按 `resource-id` 抽取详情页字段与步骤类型 | ✅ `perceive.py` |
| Planner | 受限动作空间 + 提示词约束 | ◐ `planner.py` + `prompts/planner.md`（决策靠外部模型） |
| Execute | 10 个动作落到 adb | ✅ `executor.py` |
| Verify | 提交结果按活动/列表校验，不信 toast | ◐ 约定写在提示词与 E2E 实录里 |
| Guard | 伦理红牌 + 可行性判定（多原因） | ✅ `guard/` |
| Ledger | 每步账本与状态机 | ◐ `ledger.py` / `state_machine.py` / `cli.py` |

两个已封装的**任务模板**：

- `d_class.py`：D 类（下载装 App）端到端安装链路 —— 商店搜索 → 认出目标行 → 商店/系统安装器两次确认 → 用「新增包」证明成功。
- 相册选图链路在 `device.pick_from_gallery`，按 `name` 选图，不按 index。

## 动作空间

10 个动作见 `prompts/planner.md`：`TAP` / `SWIPE` / `INPUT_TEXT` / `BACK` / `WAIT` / `OPEN_URL` / `CAPTURE_EVIDENCE` / `PICK_FROM_GALLERY` / `ASK_HUMAN` / `FINISH`。

`PICK_FROM_GALLERY` 用 `{"name": ...}` 按文件名匹配，不用 index —— 相册按 `date_added` 倒序，索引会随调试截图变化。

## 守卫层

- `check_ethics(bounty)`：按「禁止地区 / 允许地区 → 改 IP → 伪造身份 → 虚假调研 → 地区未知」的优先级返回 `AbortReason`。`forbidden_regions` 是黑名单（含本机地区即拒），`allowed_regions` 是白名单（非空且不含本机地区即拒）。
- `check_feasibility(bounty, env=None)`：先过伦理守卫，再按旧优先级收集微信/支付宝/扫码/登录态/第三方 App/完成条件等全部门槛，返回 `(Verdict, list[AbortReason])`；`DO` / `DEFERRED` 返回空列表，多道门同时命中时全部保留，不再静默丢弃其余原因。`primary_reason(reasons)` 是兼容层，取列表首个（即旧版单值口径）。`AbortReason.kind` 把原因归为 `ENVIRONMENT` / `PLATFORM` / `PREREQUISITE` / `RED_LINE` / `DATA` / `ECONOMIC`，上层可按组生成行动清单。
- 环境入参（`Environment`）：`installed` / `logged_in` 用包名，`account_is_new` 记录账号是否新号，`name_to_pkg` 把中文显示名映射到包名。传入后已装 App 不再判缺前置、任务目标 App 的下载安装属于任务本身、点名的 App 全部已登录则登录门槛满足、人工确认的新号满足人群门槛；`env=None` 时环境修正全部关闭。
- 前序依赖（`NEEDS_PREREQUISITE`）：正文（`title` / `type` / `limite` / `steps`）出现「第 N 天 / 做过的 / 后续赏金」等，说明这单要求先完成之前的活动；它不依赖环境，排在所有环境修正之前。
- 两段门槛（`COMPLETION_UNSPECIFIED`）：类型/报名条件里点名了 `试玩` / `助力` / `答题` / `看视频` / `进群` 等完成动作，而步骤里没有对应动作时，追加该原因；标题里的商家品牌名不是完成条件来源（品牌名带动作词会假阳性），只在步骤只剩下载安装时作为「还有后续动作」的线索。下载安装类悬赏「装得上」不等于「装完即完成」；只按步骤执行到末尾会静默漏做、做完也拿不到赏金，所以必须在执行前显式标出「完成条件未在步骤中说明」。
- 两阶段判定：`Bounty.steps_incomplete=True` 表示 `steps` 抓取自大厅列表预览（可能只给了第 1 步）。有效步骤 ≤1 时不再判 `DO` 或 `UNKNOWN_STEPS`，而是返回 `Verdict.DEFERRED`；伦理/地区红牌、微信/支付宝/登录/第三方 App 门槛和赏金结论（`UNKNOWN_REWARD`/`LOW_REWARD`）仍按原优先级先判。只要原因列表非空就返回 `ABORT`，不因预览不完整降级为 `DEFERRED`。`steps_incomplete` 默认 `False`，即旧行为完全不变。
- 登录态（`NEEDS_LOGIN`）三个来源：显式词（`账号`/`登录`/`手机号注册`/`绑定手机`）、隐性动作（`助力`/`关注`/`点赞`/`搜索`/`签到`/`打卡` 等只有账号才能追溯的动作）、人群限定（`新用户`/`老用户`/`回归`/`每个手机号一次`/`勿多账号` 等账号状态词，来自 `Bounty.type` / `Bounty.limite` 或步骤原文）。下载类步骤同时命中第三方 App 时，登录态优先归因——它比「装得上」更根本。
- `None` 语义：`reward`、`allowed_regions`、`forbidden_regions` 的 `None` 表示「没读到」，不是 0 元或空名单。地区未知返回 `UNKNOWN_REGIONS`，赏金未知返回 `UNKNOWN_REWARD`，都不许按「无限制」或「低赏金」处理；空列表才表示页面明确没有该项限制。已废弃的 `restricted_regions` 在 `from_dict` 中按 `allowed_regions` 兼容，两个地区字段同时非空是数据错误（`ValueError`）。
- `DEVICE_REGION = "云南"`：本机公网 IP 归属地为中国云南昆明，**换机器时必须按实际 IP 归属地修改**，否则地区限制判断会失效。

## 感知层

- `classify_detail_page(page)` 按真机 `resource-id` 抽取详情页：`title`（mission_groupname + mission_title）、`reward`、`detail`、`limite`、`steps`（setpcount 序号配对 step_detail，每步含 `index`/`text`/`type`，type=cap 需要截图/nocap 不需要）、`has_text_input`/`text_input_hint`、`primary_button`、`link_button`。
- 地区输出 `allowed_regions_hint` / `forbidden_regions_hint`：`None` 表示没读到（未知），`[]` 表示限制字段已读且确定无该方向名单，两者不能互相代偿；接线到 `Bounty` 时 `None` 必须保留，不能降级成空名单。
- 无障碍树读不到文本的两种情况不算缺陷，要走视觉兜底：Flutter 自绘页面（起点读书首页）、dump 时机不对拿到的空快照。

## 执行层

- `device.py` 的坐标系以截图为准，不用 `adb shell wm size`（它报面板物理方向，横竖会颠倒）。
- `input_text` 遇非 ASCII 直接拒绝：Android 14 `input text` 对中文必 NPE，`base64` / IME 广播等旁路实测都是死路；这类步骤一律 `ASK_HUMAN`。
- 安装类证据：`adb.exe` 是 Windows 程序，dump 路径必须用**相对路径**（传 `/tmp/x.xml` 会被当成 `D:\tmp\x.xml`）。
- 商店安装是**两次确认**（商店「三方来源」弹窗 + 系统 `PackageInstaller`），且「三方来源」弹窗不是每次都有；「装成功」只由 `pm list packages` 新增证明，`InstallSuccess` 页面会残留抢焦点，不能单独当证据。

## 评测数据

- `evals/feasibility_seed_v2.jsonl`：32 条**合成**种子（含 `page_text`），用于守卫层单元口径。
- 51 条**真机**页面语料（`hall_dumps/` + `jxdumps/`）在会话工作区，未入仓库：它们含真实商家名与真机 dump，不适合公开。

真实语料与合成种子的分布不同，**守卫层数字必须两套都报**，只报一套会得出相反结论（曾出现「种子集 100%」而真机归因只有 25%）。

## 快速开始

```bash
cd zrb-agent
python -m pytest tests -q          # 不要用 unittest discover：tests 无 __init__.py
```

真机冒烟（Windows 侧，adb 路径按实际改）：

```bash
python scripts/smoke_executor.py --adb /mnt/d/leidian/LDPlayer14/adb.exe --serial emulator-5554
```

## 明确不做

- 不做改 IP 绕过地区限制；不做自动注册小号；不做伪造身份或伪造调研答案；不点支付；不无人值守刷单。
- 不碰微信 / 扫码助力（模拟器环境已触发风控，且这类单依赖登录态与真实好友关系）。
- 不自动读短信验证码：OTP 必须由人给码，执行到登录墙就 `ASK_HUMAN` 停下。

可做率是**判定规则 × 环境配置**的函数，不是平台常量；历史「64 条全部判为不可做」是特定环境下的结论。分层说明、动作参数与已合并 PR 清单见根目录 `README-交付索引.md`。