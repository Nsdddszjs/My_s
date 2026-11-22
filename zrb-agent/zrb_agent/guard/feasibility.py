"""可行性判定：先过伦理守卫，再按步骤关键词与奖励金额过滤。"""

import re
from dataclasses import dataclass, field

from zrb_agent.guard.ethics import check_ethics
from zrb_agent.schema import AbortReason, Bounty, Verdict

# 判定顺序按「特异 → 通用」：支付宝/淘宝是明确的 App 信号，扫码类词更通用，
# 先判特异词，避免「支付宝扫码」被扫码抢先归因为 NEEDS_WECHAT。
# 「某宝」「支某宝」「ZFB」是平台为规避审核故意写错字的黑话；词表不可能穷举，
# 这里只是针对「故意写错字绕过审核」这一已知对抗行为的最小防线。
_ALIPAY_TERMS = ("支付宝", "淘宝", "某宝", "支某宝", "ZFB", "zfb")
_THIRD_PARTY_TERMS = ("下载", "注册", "试玩", "安装")
_WECHAT_TERMS = (
    "长按识别", "二维码", "扫码", "扫一扫", "识别二维码",
    "某信", "薇信", "威信", "WX", "wx", "VX", "vx",
)

# 第三方 App 名表：平台文案常默认你已装 App，只写「打开 XX」而不写「下载」，
# 只认安装类动词会漏。命中任一 App 名即判 NEEDS_THIRD_PARTY_APP。
_THIRD_PARTY_APPS = (
    "得物", "淘宝", "京东", "拼多多", "抖音", "快手", "哔哩哔哩", "支付宝",
    "微信", "小红书", "美团", "起点读书", "番茄", "番茄小说", "高德",
    "百度地图", "夸克", "剪映", "汽水音乐",
    "联通", "王卡", "微店", "天猫", "滴滴", "麦当劳", "惠康", "手心输入法",
    "穿越火线", "梦幻西游", "爱加速",
)

# 已装/已登录状态都用包名（`pm list packages -3` 的产物）；这份表只登记
# 真机验证过或明确知道对应关系的中文显示名。调用方可用 Environment.name_to_pkg
# 覆盖/扩充；表里没有的名字视为「不知道对应哪个包」，仍按缺件保守处理。
_APP_PACKAGES = {
    "起点读书": "com.qidian.QDReader",
    "番茄小说": "com.dragon.read",
    "番茄": "com.dragon.read",
    "红果免费短剧": "com.phoenix.read",
    "小红书": "com.xingin.xhs",
    "淘宝": "com.taobao.taobao",
    "天猫": "com.taobao.taobao",
    "手机天猫": "com.taobao.taobao",
    "QQ": "com.tencent.mobileqq",
    "京东": "com.jingdong.app.mall",
    "拼多多": "com.xunmeng.pinduoduo",
    "ai荔枝": "com.jsbc.ailitchi",
    "AI荔枝": "com.jsbc.ailitchi",
    "手心输入法": "com.xinshuru.inputmethod",
    "极近": "com.wuhan.jijin",
    "微信": "com.tencent.mm",
    "软件商店": "com.heytap.market",
}

# 「打开 X 页面」里的 X 是 App 内部 tab/页面，不是另一个 App。只在传入
# Environment 时生效，避免改变不传环境时的既有归因。
_PAGE_NOUNS = (
    "精选", "首页", "我的", "个人中心", "详情页", "详情", "商品页", "店铺",
    "活动页", "任务页", "任务", "排行榜", "分类", "搜索页", "设置", "钱包",
    "消息", "发现", "推荐", "购物车", "订单", "个人主页", "主页", "直播间",
    "视频页", "小说页", "书架", "目录", "章节",
)

# 平台文案的惯用句式是「打开 XX」，只认动词会漏；捕获组不在浏览器白名单里，
# 说明打开的是 App、小程序或 App 内页面，同样判 NEEDS_THIRD_PARTY_APP。
_OPEN_APP_PATTERN = re.compile(
    r"打开\s*([\u4e00-\u9fa5A-Za-z0-9]{2,8})\s*(弹窗|App|app|小程序|页面)"
)
_BROWSER_WHITELIST = ("浏览器", "链接", "网页", "百度", "搜狗", "必应")
_MIN_REWARD = 0.30  # 低于三角钱的悬赏不值得执行。

# 隐性登录动词：App 内动作要能追溯「是谁做的」，数据挂在账号上，因此必然要求
# 登录。真机实测（红果免费短剧）说明文案可以完全不写「登录」，只有这些动作词
# 暴露登录门槛；纯浏览器打开链接、应用商店下载、对自己屏幕截图不在此列。
_LOGIN_ACTION_TERMS = (
    "助力", "邀请", "分享", "领取", "兑换", "关注", "点赞", "收藏", "评论",
    "转发", "搜索", "加购物车", "下单", "签到", "打卡", "浏览指定", "观看",
    "进店", "开通", "送礼物", "添加",
)
# 显式登录词：「账号」必须收录——真机语料【秋水织素妆】的唯一暴露点就是步骤
# 里的「账号手机号」；只写「下载」的步骤会先命中第三方 App 规则，所以登录态
# 必须排在 App 判定之前。
_LOGIN_EXPLICIT_TERMS = (
    "账号", "登录", "注册", "手机号登录", "手机号注册", "绑定手机", "验证码",
    "一键登录", "登录后",
)
# 人群限定词：描述的是「账号处于什么状态」，不是「任务要做什么」。要证明自己
# 是新用户/老用户/每个手机号只能做一次，平台必须先有一个可查的账号，等价于
# 手机号 + 短信验证码注册。真机文案写「一个手机号一次」，与「每个手机号一次」
# 同义，两个变体都收录。
# 「仅限」不单独收录：它同样出现在地区白名单（仅限广州 / 仅限泰国 IP）里，
# 单凭这两个字判登录会把纯地区单错误归因；人群词必须能指认账号状态。
_AUDIENCE_TERMS = (
    "新用户", "新人", "新会员", "老用户", "回归", "首次", "首单", "三十天回归",
    "每个手机号一次", "一个手机号一次", "勿多账号", "仅限新玩家",
)

# 完成动作词：类型/报名条件点名了「装完之后还要做什么」，但步骤只写到下载安装。
# 悬赏主按标题验收，planner 按步骤执行完就停手，会「做完了却拿不到赏金」且
# 不报错。这里只把类型/报名条件里出现、步骤里缺席的动作显式标出来，至少不静默放行。
# 标题（``【商家名】 运营标签``）不是常规来源：商家品牌名里带「助力」时，步骤原文
# 当然不会重复那个词，把品牌名当来源必然假阳性（Issue #77）。
_COMPLETION_ACTION_TERMS = ("试玩", "助力", "答题", "看视频", "进群")

# 安装类动作：这些动作只是「拿到 App」，本身不等于完成任务。步骤里只有它们时，
# 后面的完成动作很可能没写进步骤（#69 的 D 类缺口）。
_INSTALL_ACTION_TERMS = ("下载", "安装", "应用商店", "应用市场", "apk")

# 步骤自己已经交代了「什么算完成」的同义表述：此时不能再判「完成条件没写」。
# 例：【MSpace】type 写「简单助力，点个赞就完成」，步骤写「…全程只需要30秒
# 体验完成」——完成条件写了，只是没重复「助力」二字（Issue #77）。
_STEP_COMPLETION_EVIDENCE = (
    "体验完成", "立即完成", "完成即可", "完成即", "即完成", "就算完成",
)


def _completion_text(bounty: Bounty) -> str:
    """完成条件来源：任务类型与报名条件（步骤原文用于对照，不参与拼装）。

    **不读标题**：``title`` 是「【商家品牌名】 运营标签」，品牌名里的动作词不是
    完成条件（Issue #77 的 3 条假阳性都来自它）。标题只在步骤只剩下载安装时
    作为「这单还有后续动作」的线索，见 :func:`_completion_unspecified`。
    """
    return " ".join(part for part in (bounty.type, bounty.limite) if part)


def _completion_unspecified(bounty: Bounty) -> bool:
    """步骤是否漏掉了完成动作，需要显式标出 ``COMPLETION_UNSPECIFIED``。

    两条独立路径，都要求步骤不是大厅列表预览的截断：

    1. 类型/报名条件点名了完成动作，步骤里没有对应动作；
    2. 步骤只有下载/安装（拿到 App 就结束），而标题的运营标签点名了完成动作：
       「装得上」不等于「装完即完成」。这一条不把标题当常规来源，只在步骤明确
       停在安装时成立——品牌名假阳性单没有安装动作，不会命中。
       【微店新星助力】是真缺口：步骤只写「提前下载微店 + 扫一扫」，标题里的
       「助力」说明装完还有后续动作，而步骤没写（Issue #77）。

    步骤已用「体验完成」等同义表述交代了完成条件时，两条都不成立。
    """
    steps_text = " ".join(bounty.step_texts)
    if not steps_text.strip() or bounty.steps_incomplete:
        return False
    if any(evidence in steps_text for evidence in _STEP_COMPLETION_EVIDENCE):
        return False
    completion_text = _completion_text(bounty)
    if any(
        term in completion_text and term not in steps_text
        for term in _COMPLETION_ACTION_TERMS
    ):
        return True
    title = bounty.title or ""
    return (
        any(term in steps_text for term in _INSTALL_ACTION_TERMS)
        and not any(term in completion_text for term in _COMPLETION_ACTION_TERMS)
        and any(term in title for term in _COMPLETION_ACTION_TERMS)
        and not any(term in steps_text for term in _COMPLETION_ACTION_TERMS)
    )


# 前序依赖：这单要求先完成前几天的活动/前置任务，本身就不是独立可做的单。
# 「第 N 天」几乎只在续做语境里出现；「后续」单独出现可能是营销话术
# （【cpb会员中心】「不错过后续福利」），所以只认带比较/存在语义的搭配。
# 语义是「这单做不了」，因此排在任何环境缺件修正之前。
_PREREQ_STRONG = re.compile(
    r"(第[一二三四五六七1234567]天"
    r"|做过我的|之前做过|做过的"
    r"|需要先完成|先做完)"
)
_PREREQ_WEAK = re.compile(
    r"(后续(赏金|奖励|任务)|有后续|两天后续|三天后续|后续比这个)"
)


@dataclass(frozen=True)
class Environment:
    """执行设备的可用环境快照，用来回答「缺的到底是不是真缺」。

    ``installed`` / ``logged_in`` 是**包名**集合（``pm list packages -3`` 与登录态
    审计的产物）；``account_is_new`` 是包名 → 账号是否新号；``name_to_pkg`` 是文案
    里的中文显示名 → 包名。默认值全是空集合/空表，含义是「不知道」而不是
    「设备上什么都没装」；不知道的一律按缺件保守处理。

    只在调用方显式传入时生效；``env is None`` 时守卫层保持不感知环境的旧行为。
    ``account_is_new`` 属于高风险的账号维度：只对人工确认过的新号填 True，
    不填（或 False）时人群门槛照旧开火。
    """

    installed: frozenset[str] = frozenset()
    logged_in: frozenset[str] = frozenset()
    account_is_new: dict[str, bool] = field(default_factory=dict)
    name_to_pkg: dict[str, str] = field(default_factory=lambda: dict(_APP_PACKAGES))


def _login_text(bounty: Bounty) -> str:
    """把可能暴露登录态的三个来源拼成一段文本：type、limite 与步骤。"""
    return " ".join(
        part for part in (bounty.type, bounty.limite, *bounty.step_texts) if part
    )


def _has_prerequisite(bounty: Bounty) -> bool:
    """文案是否表明该悬赏依赖之前已完成的任务；不读环境，纯文本事实。

    ``title`` / ``type`` / ``limite`` 必须一起读：真机语料里【百度推荐官】的
    「后续比这个赏金高」只出现在 ``limite``，只读 steps 会漏。
    """
    text = " ".join(
        part for part in (bounty.title, bounty.type, bounty.limite, *bounty.step_texts) if part
    )
    return bool(_PREREQ_STRONG.search(text) or _PREREQ_WEAK.search(text))


def _named_apps(text: str, env: Environment) -> tuple[list[str], list[str]]:
    """返回 (映射表能查到包名的 App, 词表点名但映射表没登记的 App)。

    第二阶段那些 App 对应哪个包未知，无法确认「已装/已登录」，必须保守处理。
    """
    mapped = [name for name in env.name_to_pkg if name in text]
    unmapped = [
        app for app in _THIRD_PARTY_APPS if app in text and app not in env.name_to_pkg
    ]
    return mapped, unmapped


def _installed(name: str, env: Environment) -> bool:
    pkg = env.name_to_pkg.get(name)
    return pkg is not None and pkg in env.installed


def _apps_near_install_verb(text: str, names: list[str]) -> list[str]:
    """文案里紧挨着「下载/安装/注册/试玩」出现的 App 名。

    用于判断「要装的那个 App」具体是谁；只在动作词附近找，避免把页面里顺带
    提到的另一个已装 App 当成下载对象。
    """
    found: list[str] = []
    for name in names:
        start = 0
        while True:
            index = text.find(name, start)
            if index < 0:
                break
            start = index + 1
            window = text[max(0, index - 8): index + len(name) + 8]
            if any(verb in window for verb in _THIRD_PARTY_TERMS):
                found.append(name)
                break
    return found


def _task_target_app(bounty: Bounty) -> str | None:
    """「要下载的 App」同时也是任务标题主体时返回该 App 名，否则 ``None``。

    判据是 App 名同时出现在 steps 与标题里，不依赖 ``_THIRD_PARTY_APPS`` 词表，
    所以「仙遇」「梦幻西游」这类词表外的名字也能认出来。标题里的书名号内容优先。
    """
    blob = " ".join(bounty.step_texts)
    head = bounty.title or ""
    if not blob or not head.strip():
        return None
    for match in re.finditer(r"[【\[]([^】\]]{2,12})[】\]]", head):
        name = match.group(1).strip()
        if name and name in blob:
            return name
    stem = re.sub(r"[【】\[\]]", " ", head).strip()
    for name in (stem, stem.replace(" ", "")):
        if len(name) >= 2 and name in blob:
            return name
    return None


def _needs_third_party_app(bounty: Bounty, env: Environment) -> bool:
    """环境感知版第三方 App 判定。

    四类情况视为已满足：①要装的就是任务主体 App（D2，交给能力矩阵判能否安装）；
    ②文案点名的 App 全部已装；③「打开 X 页面」里的 X 是站内页面（D1）；④开放
    动作指向已装 App。说不清的对象（词表外、映射缺失、只说「下载 App」）仍拦。
    """
    text = " ".join(bounty.step_texts)
    target = _task_target_app(bounty)
    mapped, unmapped = _named_apps(text, env)

    unresolved = [
        name for name in mapped if name != target and not _installed(name, env)
    ]
    unresolved.extend(app for app in unmapped if app != target)
    if unresolved:
        return True

    wants_install = any(term in text for term in _THIRD_PARTY_TERMS)
    # 没说清装的是哪个 App 时无法确认已装；任务目标 App 本身就是下载对象时豁免。
    if wants_install and not (target and target in text):
        if not _apps_near_install_verb(text, mapped + unmapped):
            return True

    for match in _OPEN_APP_PATTERN.finditer(text):
        name = match.group(1)
        if name in _BROWSER_WHITELIST or name == target or name in _PAGE_NOUNS:
            continue
        if _installed(name, env):
            continue
        return True
    return False


def _login_satisfied(text: str, env: Environment) -> bool:
    """D3：文案点名的 App 全都已登录时，登录门槛在环境层面已满足。

    说不出是哪个 App 的、或点到了一个未登录/无法核实的 App，一律不算满足。
    """
    mapped, unmapped = _named_apps(text, env)
    if not mapped or unmapped:
        return False
    return all(
        env.name_to_pkg[name] in env.logged_in for name in mapped
    )


def _audience_satisfied(text: str, env: Environment) -> bool:
    """D4：点名的 App 账号确实已是新号时，人群门槛在环境层面已满足。

    这是最高风险的一条，必须同时满足「App 已登录」与「账号明确是新号」，缺一不可。
    """
    mapped, unmapped = _named_apps(text, env)
    if not mapped or unmapped:
        return False
    for name in mapped:
        pkg = env.name_to_pkg[name]
        if pkg not in env.logged_in or env.account_is_new.get(pkg) is not True:
            return False
    return True


# 不含具体动作的套话：整条步骤只剩这些词，等于没说清要干什么。
_VAGUE_STEP_MARKERS = ("按页面提示", "按提示", "详见", "待核", "按说明", "见页面", "以页面为准")
# 套话步骤都很短；10 字的「按提示操作后截图上传」带具体动作，必须放行，所以上限取 9。
_VAGUE_MAX_LEN = 9


def _is_vague(step: str) -> bool:
    """整条步骤只剩「按页面提示操作」之类套话时返回 True。"""
    return len(step) <= _VAGUE_MAX_LEN and any(marker in step for marker in _VAGUE_STEP_MARKERS)


def primary_reason(reasons: list[AbortReason]) -> AbortReason | None:
    """兼容层：取原因列表首个，等价于改造前的单值返回；DO / DEFERRED 返回 ``None``。"""
    return reasons[0] if reasons else None


def check_feasibility(
    bounty: Bounty, env: Environment | None = None
) -> tuple[Verdict, list[AbortReason]]:
    """返回 (判定, 全部中止原因)；判定为 DO 或 DEFERRED 时原因为空列表。

    真机上一条悬赏常同时卡在多道门上，旧版只返回首个会静默丢弃其余阻断；这里按
    旧版优先级全部收集，列表首个仍是旧版返回值（``primary_reason`` 兼容层）。

    ``env`` 是设备环境快照（已装包 / 已登录包 / 账号是否新号 / 名字→包名映射）。
    传入后守卫层会先问「这个门槛在环境层面是否已经满足」再开火：已装的 App 不再
    判缺前置、任务目标 App 的下载/安装属于任务本身、已登录的 App 不再判 NEEDS_LOGIN、
    人工确认的新号不再判人群门槛。``env is None`` 时以上环境修正全部关闭；与设备
    无关的前序依赖规则（``NEEDS_PREREQUISITE``）是独立文本事实，任何调用都生效。

    低赏金是性价比结论，不是可行性结论，两者不该抢同一个枚举位：LOW_REWARD
    放在所有其它判定之后，只有没有任何其它中止原因时才作为最后理由返回。
    ``reward is None`` 是赏金没读到，返回 UNKNOWN_REWARD，不能当 0 元判 LOW_REWARD。

    两阶段判定：``bounty.steps_incomplete=True`` 表示步骤来自大厅列表预览，可能
    只给了第 1 步。此时有效步骤不足 2 条就不下可行性结论（不再判 DO 或
    UNKNOWN_STEPS），返回 ``Verdict.DEFERRED``，由调用方报名后用完整步骤复判。
    优先级说明：

    - 伦理/地区红牌照常先判：它们来自结构化字段（或明确文本），不会被步骤变多改写；
    - 前序依赖紧跟在伦理之后：它是「这单本身做不了」，不能被环境修正豁免；
    - 微信/支付宝/登录/第三方 App 等关键词命中照常中止：预览里的步骤是完整步骤的
      子集，加步骤只会增加命中，不会让已出现的门槛消失。命中多族时全部保留；
    - 完成条件词（试玩/助力/答题/看视频/进群）只在类型/报名条件里出现、步骤里
      没有对应动作时，追加 COMPLETION_UNSPECIFIED：按步骤做完不等于达标，不能静默放行。
      标题不是完成条件来源；步骤只剩下载安装时，标题里的动作词才作为「还有后续动作」
      的线索。该门依赖「步骤里缺什么」，预览步骤不完整时不判，留给完整步骤复判；
    - UNKNOWN_REWARD / LOW_REWARD 照常返回：赏金是列表页字段事实，与步骤完整性无关；
    - 只要列表里已经有阻断，就返回 ABORT，不再因为预览不完整降级为 DEFERRED；
    - 只有当「步骤未知」或「本应判 DO」这两个依赖步骤完整性的结论出现时，才改为
      DEFERRED。这样 ``steps_incomplete=False`` 的所有既有路径保持原样。
    """
    reasons: list[AbortReason] = []

    # 保持旧版优先级顺序，所以列表首个永远等于旧版的返回值。
    reason = check_ethics(bounty)
    if reason is not None:
        reasons.append(reason)

    if _has_prerequisite(bounty):
        reasons.append(AbortReason.NEEDS_PREREQUISITE)

    text = " ".join(bounty.step_texts)
    if any(term in text for term in _ALIPAY_TERMS):
        reasons.append(AbortReason.NEEDS_ALIPAY)
    if "保存图片" in text:
        reasons.append(AbortReason.NEEDS_SCANNER)
    if any(term in text for term in _WECHAT_TERMS):
        reasons.append(AbortReason.NEEDS_WECHAT)
    # 登录态判定必须排在第三方 App 之前：下载类步骤几乎都会命中「下载/安装」，
    # 若先判 App，会把「下载后凭新用户身份做任务」错误归因为 App 门槛。
    login_text = _login_text(bounty)
    login_triggered = (
        any(term in login_text for term in _LOGIN_EXPLICIT_TERMS)
        or any(term in login_text for term in _AUDIENCE_TERMS)
        or any(term in login_text for term in _LOGIN_ACTION_TERMS)
    )
    if login_triggered:
        audience_triggered = any(term in login_text for term in _AUDIENCE_TERMS)
        if env is None or not _login_satisfied(login_text, env):
            reasons.append(AbortReason.NEEDS_LOGIN)
        elif audience_triggered and not _audience_satisfied(login_text, env):
            reasons.append(AbortReason.NEEDS_LOGIN)
    if env is None:
        third_party = (
            any(term in text for term in _THIRD_PARTY_TERMS)
            or any(app in text for app in _THIRD_PARTY_APPS)
            or any(
                match.group(1) not in _BROWSER_WHITELIST
                for match in _OPEN_APP_PATTERN.finditer(text)
            )
        )
    else:
        third_party = _needs_third_party_app(bounty, env)
    if third_party:
        reasons.append(AbortReason.NEEDS_THIRD_PARTY_APP)

    # 第二段门槛：装得上 ≠ 装完即完成。完成动作从类型/报名条件里读，标题只在
    # 步骤只剩下载安装时作为线索；planner 按步骤执行到末尾会静默漏做，这里显式标出。
    # 这个门看「步骤里缺什么」，不是「步骤里有什么」：大厅预览可能只给了第 1 步，
    # 缺动作可能只是截断，所以步骤不完整时不下结论，等报名后的完整步骤复判。
    if _completion_unspecified(bounty):
        reasons.append(AbortReason.COMPLETION_UNSPECIFIED)

    # 已有明确阻断就不 DEFERRED：预览步骤是完整步骤子集，补全只会增加命中。
    if reasons:
        return Verdict.ABORT, reasons

    steps = [step.strip() for step in bounty.step_texts if step.strip()]
    # 大厅预览只给 1 步时，步骤越少不一定越糟：报名后的完整步骤可能补上说清的动作。
    preview_incomplete = bounty.steps_incomplete and len(steps) <= 1
    # 只要有一条步骤说清了，这单就还能继续做，所以用 all 而不是 any；
    # 长度上限避免误杀「按提示操作后截图上传」这类带具体动作的步骤。
    if not steps or all(_is_vague(step) for step in steps):
        if preview_incomplete:
            return Verdict.DEFERRED, []
        return Verdict.ABORT, [AbortReason.UNKNOWN_STEPS]
    if bounty.reward is None:
        return Verdict.ABORT, [AbortReason.UNKNOWN_REWARD]
    if bounty.reward < _MIN_REWARD:
        return Verdict.ABORT, [AbortReason.LOW_REWARD]
    if preview_incomplete:
        # 预览步骤不足以支撑 DO：先报名，拿到完整步骤后再走一次判定。
        return Verdict.DEFERRED, []
    return Verdict.DO, []
