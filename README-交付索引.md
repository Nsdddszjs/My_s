# 交付索引

本仓库的交付物、动作口径与数据口径索引。以下内容以 `main` 的 `git log` 为准。

## 1. 系统定位

输入一个悬赏，输出三件事：**能不能做、为什么不能做、做了的证据在哪**。
`zrb-agent` 是视觉驱动的 Android 众包悬赏执行 Agent 骨架，动作空间故意保持为 10 个。

## 2. 分层与文件

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 任务层 | `zrb-agent/zrb_agent/schema.py` | 悬赏数据模型与字段语义 |
| 守卫层 | `zrb-agent/zrb_agent/guard/` | 可行性判定与伦理红牌，一票否决 |
| 设备层 | `zrb-agent/zrb_agent/device.py` | 把结构化命令翻译成 adb 调用 |
| 感知层 | `zrb-agent/zrb_agent/perceive.py` | UI 树 → `PageState`；提交成功与「已通过」校验 |
| 决策层 | `zrb-agent/zrb_agent/planner.py` | 生成受限动作空间里的唯一动作 |
| 动作空间 | `zrb-agent/zrb_agent/schema_action.py` | 10 个动作的参数校验 |

## 3. 动作与参数口径

### 3.1 动作空间

动作清单与使用约束见 `zrb-agent/prompts/planner.md`。10 个动作是故意设小的：
每多一个动作，模型选错的概率与需要单独校验的失败模式都会增加。

### 3.2 关键参数示例

| 动作 | 参数 | 示例 |
| --- | --- | --- |
| `CAPTURE_EVIDENCE` | `name` | `{"name": "AA_step1.png"}` |
| `PICK_FROM_GALLERY` | `name` | `{"name": "AA_step1.png"}` |

`PICK_FROM_GALLERY` 按文件名匹配，**不用 index 参数**：相册按 `date_added` 倒序排列，
调试截图随时会抢占索引。按名匹配失败时必须抛错，不许静默回退到「点第 1 个」。

## 4. 「可做率」的口径

**可做率 = 判定规则 × 环境配置 的函数，不是数据常量。**
历史结论「64 条全部判为不可做」是「未装起点读书 + 未登录 + 无第三方 App」这一具体环境下的结论，
不能当作平台结论。反证：补齐环境后，起点读书单 1.28 元全额到账。

### 4.1 D 类（下载装 App）是两段门槛

「装得上」不等于「装完即完成」。21 条含下载安装的真机语料按第二段拆开（#69）：

| 桶 | 条数 | 金额 | 口径 |
| --- | --- | --- | --- |
| A 装完还要登录 | 6 | 6.54 元 | 等登录态入参（#74），当前不可无人值守 |
| B 含扫码 | 10 | 10.30 元 | 红线，永久排除 |
| C 装完即完成 | 5 | 8.52 元 | 唯一可做，D 类「可做」按此桶报 |

**不能把 A/B 桶算进「可做」。** 按动作词统计会把「下载 + 扫码 / 下载 + 登录」误算成可做；
判定层用 `COMPLETION_UNSPECIFIED` 显式标出「完成条件未在步骤中说明」，避免装完即停手。

## 5. 已合并 PR（截至 `main`）

- #48 — `NEEDS_LOGIN` 登录态判定
- #47 — 生产口径集成测试
- #45 — 拆分地区黑白名单并统一 `None` 语义
- #43 — planner 决策层
- #40 — `device.py` 坐标系与非 ASCII 修复

完整清单以 `git log --first-parent --oneline origin/main` 为准。

## 6. 验证

```bash
cd zrb-agent
python3 -m unittest discover -s tests
```