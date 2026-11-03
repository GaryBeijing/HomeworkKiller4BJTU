# 第 2 部分 · API Reference 与扩展/升级指南

> 目标：让 Agent 在不读源码的情况下**正确调用**任何公开接口，并按配方**正确扩展**代码。
>
> 本文件所有签名均取自源码实际定义；`->` 后的类型为注解原文。`dict[str, Any]` 简写为 `dict`。

---

## 目录

- [1. 调用协议总览](#1-调用协议总览)
- [2. 统一返回结构 ApiResult](#2-统一返回结构-apiresult)
- [3. Python API](#3-python-api)
  - 3.1 `hwklr`（包元数据）
  - 3.2 `hwklr.config`
  - 3.3 `hwklr.runtime_data`
  - 3.4 `hwklr.features.base`
  - 3.5 `hwklr.features.settings`
  - 3.6 `hwklr.features.manifest`
  - 3.7 `hwklr.features.about`
  - 3.8 `hwklr.features.hsr`（高铁纵横）
  - 3.9 `hwklr.features.cprog`（C程序设计）
  - 3.10 `hwklr.features.build`（构建）
  - 3.11 `hwklr.UI`（窗口层）
  - 3.12 `hwklr.UI.tagview`（标签层）
  - 3.13 `hwklr.UI.server`（本地 HTTP）
- [4. 前端 API](#4-前端-api)
- [5. 配置项参考（config.json）](#5-配置项参考configjson)
- [6. 动作总表（tag × action）](#6-动作总表tag--action)
- [7. 扩展代码的方式（8 个配方）与编码规范](#7-扩展代码的方式8-个配方与编码规范)
- [8. 升级与兼容规则](#8-升级与兼容规则)
- [9. 改完自检清单](#9-改完自检清单)
- [10. 反模式（禁止事项）](#10-反模式禁止事项)

---

## 1. 调用协议总览

### 1.1 三层契约

前端只有两条通道能触达 Python，**没有第三条**：

| 通道 | 入口 | 适用 | 返回 |
|---|---|---|---|
| **A. 功能调用（唯一动态通道）** | `window.pywebview.api.call(tag, method, params)` | 一切业务动作 | `ApiResult` |
| **B. 元信息（只读）** | `GET /api/tags`、`GET /api/meta`、`window.pywebview.api.get_tags()`、`.get_meta()` | 标签列表、应用元信息 | 普通 JSON（非 ApiResult） |

其余 HTTP 路径只用于静态文件（`/page_data/*`、`/view_data/*`、`/`）。

### 1.2 一次调用的参数与校验契约

```
call(tag: str, method: str, params: dict|None)
  ├─ tag      : 标签名，必须是 VIEW_PARAMS 的键（"高铁纵横" / "C程序设计" / "构建" / "设置" / "关于"）
  ├─ method   : 动作名，必须是该 Feature.handle() 分发表里的键；不得以 '_' 开头
  └─ params   : JSON 对象；None 会被规范化为 {}
```

四道校验，任一失败返回 `failure(...)` 而**不抛异常**（JS 侧表现为 `ok:false`）：

| 校验 | 位置 | 失败信息 |
|---|---|---|
| 标签存在 | `WindowView.bridge_call` | `未知标签: <tag>` |
| `method` 非空且不以 `_` 开头 | `WindowView.bridge_call` | `非法动作: <method>` |
| `params` 为 dict | `WindowView.bridge_call` | `动作参数必须是对象` |
| `method` 非空且不以 `_` 开头（第二道） | `TagView.call` | 抛 `ValueError`，被上层兜住 |

顶层还有一层 `try/except Exception`：任何未被功能内部捕获的异常都会被转成 `failure("调用失败: <exc>")` 并记录 `_LOGGER.exception`。

### 1.3 时序（含前端在途状态）

```
JS: App.callOk('list_exams')
      │
      ├─ waitForBridge()               ← 等 window.pywebview.api 就绪（最多 12s，超时报"桥接初始化超时"）
      ├─ 取 App.active 作为 tag         ← 注意：标签名即路由键
      ▼
pywebview 内部把调用派发到 GUI 线程之外的桥接线程
      ▼
BridgeApi.call → WindowView.bridge_call → TagView.call → Feature.handle
      ▼
返回 dict（必须 JSON 可序列化；含 bytes / 自定义对象会直接失败）
      ▼
JS: result.ok ? return result.data : throw new Error(result.error)
```

---

## 2. 统一返回结构 ApiResult

```python
ApiResult = dict[str, Any]          # hwklr/features/base.py:28

def success(data: Any = None) -> ApiResult:            # {"ok": True,  "data": data}
def failure(message: str, data: Any = None) -> ApiResult:  # {"ok": False, "error": message, "data": data}
```

**硬约束**

| 规则 | 说明 |
|---|---|
| 顶层必有 `ok` | 前端 `callOk()` 只看 `ok`；缺失会被当成 `ok=false` |
| `data` 必须 JSON 可序列化 | 禁止 `bytes`、`set`、`datetime`、自定义对象；用 `to_payload()` 转 |
| `error` 面向用户 | 中文、可直接展示；内部异常细节进日志而不是 `error` |
| 成功也可能带 `data=None` | 例如 `logout` 返回 `success({"logged_in": False})`，建议总给结构而非 `None` |

**子类 `handle()` 的异常约定**：可以直接 `raise ValueError("中文提示")`，由各 Feature 的 `handle()` 统一转成 `failure(str(exc))`。**不要**在 `handle()` 里裸 `return {"ok": False}`，也不要依赖 `raise` 跨越桥接层（会变成 `调用失败: ...` 这种不带上下文的文案）。

---

## 3. Python API

### 3.1 `hwklr`（包元数据）

```python
from hwklr import APP_NAME, APP_TITLE, APP_ICON, APP_AUTHORS, APP_DESCRIPTION, APP_DISCLAIMER, DEV_BUILD
from hwklr import __version__, __author__
```

| 符号 | 类型 | 值/来源 | 说明 |
|---|---|---|---|
| `__version__` | `str` | `"2.3.1"`（被 `_build_info.EXPORT_VERSION` 覆盖） | 包版本 |
| `__author__` | `str` | `"Gary"` | — |
| `DEV_BUILD` | `bool` | `False`（被 `_build_info.DEV_BUILD` 覆盖） | 是否开发构建产物；控制"搭建开发环境"入口 |
| `APP_NAME` | `str` | `EXPORT_NAME or "HomeworkKiller4BJTU"` | 导出时可用自定义名覆盖 |
| `APP_TITLE` | `str` | `EXPORT_NAME or "HomeworkKiller4BJTU · 作业助手"` | 窗口标题默认值 |
| `APP_ICON` | `str` | `""` 或图标绝对路径 | 仅当 `_build_info.ICON_PATH` 指向的文件真实存在才非空 |
| `APP_AUTHORS` | `tuple[str, ...]` | `("Gary", "PhiloK (Remaster by Gary)（高铁纵横）")` | — |
| `APP_DESCRIPTION` | `str` | 长中文 | 关于页简介 |
| `APP_DISCLAIMER` | `str` | 长中文 | 关于页免责声明；**修改前确认合规** |

> `_build_info.py` 由构建功能自动生成，源码树里**不存在**；`hwklr/__init__.py` 用 `try/except ImportError` 兼容两种情形。不要手工创建该文件。

---

### 3.2 `hwklr.config`

唯一的配置读写口。**任何模块都不得自己拼 `config.json` 路径。**

```python
from hwklr.config import config_path, load_config, save_config, update_config, DEFAULT_CONFIG
```

| 符号 | 签名 | 行为 |
|---|---|---|
| `config_path` | `() -> Path` | 源码运行 → `<仓库根>/config.json`；`sys.frozen` → `Path(sys.executable).parent/config.json` |
| `load_config` | `() -> dict` | 文件不存在 → 写入默认值并返回；文件损坏/非对象 → 记 warning 并返回默认值（**不覆盖损坏文件**）；成功后 `_deep_merge(DEFAULT_CONFIG, loaded)` 再 `_migrate_config` |
| `save_config` | `(config: dict) -> None` | 原子写：先写 `config.json.tmp` 再 `replace`；全程持 `_CONFIG_LOCK`。可能抛 `OSError` |
| `update_config` | `(patch: dict) -> dict` | `load → _deep_merge(current, patch) → save`，返回更新后的完整配置 |
| `DEFAULT_CONFIG` | `Final[dict]` | 所有默认值；**新增配置项必须在此登记**，否则老旧配置文件不会自动补齐 |

**语义要点**

- `_deep_merge` 递归合并，`override` 优先，不修改入参。
- `_migrate_config` 做两件事：V1 顶层 `password` → `hsr.password`；丢弃已废弃的 `c_programming.temperature`，并用默认值补齐 `c_programming` / `build` / `build.features` 的缺失键。
- 每次 `load_config()` 都**真实读盘 + 解析 JSON**，没有缓存。因此高频路径（如 `/api/tags`）会反复读文件；这是已知特性，不要假设拿到的是同一个对象。

---

### 3.3 `hwklr.runtime_data`

知识库定位与读取。**只读取，不含业务逻辑。**

```python
from hwklr import runtime_data
```

| 符号 | 签名 | 行为 |
|---|---|---|
| `BANK_DIR` | `Path` | `hwklr/runtime_data/` |
| `list_banks` | `() -> dict[str, list[str]]` | `{feature: [版本从新到旧]}` |
| `list_versions` | `(feature: str) -> list[str]` | 大小写不敏感、去空白；不存在返回 `[]` |
| `latest_version` | `(feature: str) -> str` | 取最新；**不存在则抛 `FileNotFoundError`**，消息含可用功能列表 |
| `load_bank` | `(feature: str, version: str \| None = None) -> Any` | 返回 `json.load` 结果（`list` 或 `dict`）；每次重读，调用方可安全修改返回值 |

**命名规则**（正则 `^(?P<feature>[a-z0-9_]+)_bank_v(?P<version>\d+\.\d+)\.json$`，`IGNORECASE`）：

```
hwklr/runtime_data/hsr_bank_v1.0.json     → feature="hsr", version="1.0"
```

不合规的文件会被**静默忽略**（不报错）。

---

### 3.4 `hwklr.features.base`

```python
from hwklr.features.base import ApiResult, Feature, failure, success
```

#### `Feature`（抽象基类）

| 成员 | 签名 | 说明 |
|---|---|---|
| `__init__` | `(universal_param: dict) -> None` | 内部做 `dict(universal_param or {})`，即**浅拷贝**；`self._started = False` |
| `universal_param` | `@property -> dict` | 返回浅拷贝；实际键见下 |
| `started` | `@property -> bool` | — |
| `settings_group` | `@property @abstractmethod -> FeatureSettingsGroup` | **子类必须实现** |
| `start` | `() -> None` | 默认 `self._started = True` |
| `stop` | `() -> None` | 默认 `self._started = False` |
| `handle` | `@abstractmethod (action: str, params: dict) -> ApiResult` | 业务入口；未知动作应返回 `failure("未知动作: %s" % action)` |

`universal_param` 的实际内容（由 `WindowView.__init__` 注入）：

```python
{
  "context":  {"port": int},   # 与 WindowView._context 是同一对象；服务启动后写入真实端口
  "app_meta": {...},           # 与 WindowView._meta 是同一对象；features 列表在构造后被就地填充
}
```

> **坑**：`AboutFeature` 读的是 `universal_param["app_meta"]`，该 dict 的 `port` 永远是 `0`（端口只写进了 `_context`，由 `meta_payload()` 现拼）。要拿真实端口请用 `SettingsFeature` 的 `get_settings` 或 `BridgeApi.get_meta()`。

#### 构造结果的两个工厂

```python
success({"a": 1})              # {"ok": True, "data": {"a": 1}}
failure("请先登录")             # {"ok": False, "error": "请先登录", "data": None}
```

---

### 3.5 `hwklr.features.settings`

```python
from hwklr.features.settings import FeatureSettingsGroup, SettingsFeature, SettingsFieldSpec
```

#### `SettingsFieldSpec`（`@dataclass(frozen=True)`）

| 字段 | 类型 | 默认 | 作用 |
|---|---|---|---|
| `key` | `str` | 必填 | 配置里的字段名 |
| `label` | `str` | 必填 | 显示名（也用于错误信息） |
| `kind` | `str` | `"text"` | `text` / `password` / `number` / `select` / `switch` / `features` |
| `placeholder` | `str` | `""` | 占位符 |
| `help` | `str` | `""` | 字段下方说明 |
| `options` | `tuple[tuple[str, str], ...]` | `()` | `(value, label)`；`select` 与 `features` 用 |
| `secret` | `bool` | `False` | 输入框用 `password` 类型 + "显示/隐藏"按钮 |
| `min_value` / `max_value` | `float \| None` | `None` | `number` 的取值范围校验 |
| `step` | `float \| None` | `None` | `number` 的步长 |
| `strip` | `bool` | `True` | 文本是否 `strip()` |
| `is_necessary` | `bool` | `True` | 仅影响前端灰字"可选填"标记，**不阻止离开页面** |
| `alert` | `bool` | `False` | 高级设置；修改并保存时前端弹二次确认 |

**`kind` 的处理矩阵**（后端 `normalize()` / 前端 `buildField()` 必须一致）：

| kind | 前端控件 | `normalize` 结果 | 备注 |
|---|---|---|---|
| `text` | `<input type=text>` | `str`，`strip` 决定是否去空白 | 默认分支 |
| `password` | `<input type=password>` + 显示按钮 | 同 `text` | 后端无专门分支，走 else；通常配 `strip=False` |
| `number` | `<input type=number>` | `float`；非法/越界抛 `ValueError` | **会变成 float**，需要 int 时自行 `int()` |
| `select` | `<select>` | `str`；不在 `options` 的 value 集合内抛 `ValueError` | `options` 为空时不校验 |
| `switch` | `<input type=checkbox>` | `bool`（`_as_bool`：`bool` / 数字 / `"1,true,yes,on,是"`） | — |
| `features` | 表格 + 每行 checkbox | `dict[str, "dev"\|"release"]`，只保留 `options` 里登记的名字 | 值语义固定为字符串 |

#### `FeatureSettingsGroup`

```python
FeatureSettingsGroup(
    group_id: str,                 # 板块 ID，同时是 config.json 里的分组名（"general" 例外）
    title: str,
    description: str,
    field_specs: tuple[SettingsFieldSpec, ...],
    values_getter: Callable[[], dict],                  # 从 config 读当前值
    exporter: Callable[[dict], dict],                   # 规范化值 → 配置补丁
    complete_checker: Callable[[], bool],               # 必要设置是否齐全
    missing_getter: Callable[[], list[str]],            # 缺失项的可读名（如 "高铁纵横：密码"）
)
```

| 方法 | 返回 | 说明 |
|---|---|---|
| `field_specs` (prop) | `tuple[SettingsFieldSpec, ...]` | — |
| `values()` | `dict` | `{spec.key: values.get(key, "")}`，即**只含本组字段** |
| `fields()` | `list[dict]` | 前端渲染用字段数据（见下） |
| `normalize(raw_values)` | `dict` | 以当前值为底，按 `kind` 校验/转换；只处理传入的 key |
| `export(values=None)` | `dict` | 配置补丁；`None` 时用 `values()` |
| `is_complete()` | `bool` | `bool(complete_checker())` |
| `missing_labels()` | `list[str]` | — |
| `payload()` | `dict` | `{group_id, title, description, fields, complete, missing}` |

`fields()` 单项结构：

```python
{"key": str, "label": str, "kind": str, "value": Any, "placeholder": str, "help": str,
 "options": [{"value": str, "label": str}], "secret": bool,
 "min": float|None, "max": float|None, "step": float|None,
 "is_necessary": bool, "alert": bool,
 "rows": [{"name": str, "version": str, "dev": bool}]}   # 仅 kind == "features"
```

#### `SettingsFeature`

| 成员 | 签名 | 说明 |
|---|---|---|
| `__init__` | `(universal_param: dict)` | 自带 `general` 板块（`username`） |
| `settings_group` (prop) | `-> FeatureSettingsGroup` | 返回 `general` 组 |
| `register_group` | `(group: FeatureSettingsGroup) -> None` | 按 `group_id` 去重；重复注册静默忽略 |
| `groups` (prop) | `-> list[FeatureSettingsGroup]` | 副本 |
| `handle` | actions: `get_settings` / `save_settings` / `get_bank_info` | 见 §6.4 |

---

### 3.6 `hwklr.features.manifest`

**新增功能唯一需要手工维护的清单。**

```python
from hwklr.features.manifest import OFFICIAL_FEATURES, FEATURE_BY_NAME, FeatureSpec, feature_version, load_feature_class
```

```python
class FeatureSpec(NamedTuple):
    name: str          # 标签名，也是 ViewParam 的键与前端 call() 的 tag
    module: str        # 完整导入路径，如 "hwklr.features.hsr"
    class_name: str    # 类名，如 "HSRFeature"
    view_dir: str      # view_data 下的资源目录名，如 "hsr"
    description: str   # 标签栏 tooltip 与关于页功能说明
```

| 符号 | 签名 | 说明 |
|---|---|---|
| `OFFICIAL_FEATURES` | `Final[tuple[FeatureSpec, ...]]` | 当前 3 项，**顺序即标签顺序** |
| `FEATURE_BY_NAME` | `Final[dict[str, FeatureSpec]]` | 名称索引 |
| `load_feature_class` | `(module_name, class_name) -> type \| None` | `ImportError` → `None`；类不存在或不是类 → `None`。**不抛异常** |
| `feature_version` | `(spec: FeatureSpec) -> str` | 读模块 `__version__`；模块不可导入 → `"0.0.0"` |

> **静默失败风险**：`load_feature_class` 吞掉 `ImportError`。若新功能模块里有语法错误或 `ImportError`，标签页会**直接消失**且没有日志。排查时先手动 `python -c "import hwklr.features.<name>"`。

---

### 3.7 `hwklr.features.about`

| 成员 | 说明 |
|---|---|
| `AboutFeature(universal_param)` | 设置组为空 `field_specs=()`（因此不会被注册进设置页） |
| `handle("get_meta", {})` | 返回 `success(universal_param["app_meta"])`；`app_meta` 非 dict 时返回 `{}` |

返回的 `app_meta` 结构：

```python
{"name": str, "title": str, "version": str, "authors": [str],
 "description": str, "disclaimer": str,
 "features": [{"name": str, "description": str}],   # 构造时就地填充
 "port": 0}                                          # ← 恒为 0，见 §3.4 的坑
```

---

### 3.8 `hwklr.features.hsr`（高铁纵横）

```python
from hwklr.features.hsr import HSRFeature
from hwklr.features.hsr.client import BASE_URL, HsrApiError, HsrClient
from hwklr.features.hsr.bank import Bank, load_rows, load_items_from_file, normalize, \
    strip_question_number, strip_option_prefix, option_letter_map
from hwklr.features.hsr.aes import aes_ecb_encrypt_b64
from hwklr.features.hsr.captcha import CaptchaOffset, solve_offset
```

#### `HSRFeature`（动作见 §6.1）

实例内部状态：`_client: HsrClient|None`、`_records: list[dict]`（考试列表缓存）、`_bank_cache: Bank|None`（首访才加载）、`_lock: threading.RLock`。

`handle()` 整体持 `_lock`，并把 `HsrApiError` / `ValueError` / 其他异常统一转 `failure`。

#### `HsrClient`

```python
HsrClient(timeout: float = 40.0)
```

| 成员 | 签名 | 说明 |
|---|---|---|
| `token` (prop) | `-> str \| None` | 登录后持有的 Bearer Token |
| `login` | `(username: str, password: str) -> str` | 内部先过验证码；成功返回 token，失败抛 `HsrApiError` |
| `exam_list` | `() -> dict` | `GET /exam/my?pageNumber=1&pageSize=100`；返回裸分页对象或 `code==200` 的包体 |
| `start_precheck` | `(exam_id: int) -> dict` | `POST /exam/startPreCheck/<id>`；`code != 200` 抛错 |
| `start_exam` | `(exam_id: int) -> dict` | `POST /exam/startExam/<id>`；返回 `data`（试卷），**消耗一次作答机会** |
| `save_exam` | `(payload: dict) -> dict` | `POST /exam/save`（保留能力，UI 未用） |
| `commit_exam` | `(payload: dict) -> dict` | `POST /exam/commit`；原始响应，需自行判 `code == 200` |
| `detail_answer` | `(personal_exam_id: int) -> dict` | `GET /exam/detailAnswer?id=`；返回 `data`（非 dict 时 `{}`） |

`BASE_URL = "http://59.64.5.158/prod-api"`（明文 HTTP，见 `03 §16`）。

#### `Bank`

```python
Bank(items: Sequence[dict])
Bank.from_file(path: Path) -> Bank
```

| 成员 | 签名 | 返回 |
|---|---|---|
| `items` (prop) | `-> list[BankItem]` | 副本；`BankItem = {"q","a","t","chapter","section","answer_options","nq"}` |
| `count` (prop) | `-> int` | — |
| `lookup_item` | `(question: str, threshold: float = 0.90)` | `(item|null, score, method\|null)`，`method ∈ {"exact","exact-conflict","fuzzy"}` |
| `lookup` | `(question: str, threshold: float = 0.90)` | `(answer_text|null, score, method\|null)` |
| `resolve_answer_options` | `(answer_options, options, multi=False, trace: list[bool]\|None=None) -> list[str]` | 返回命中的 `optionCode` 列表；`trace` 会追加每个答案选项"是否靠原文命中" |
| `resolve_answer` | `(answer_text: str\|None, options, multi=False) -> list[str]` | 从答案文本解析（字母 / 原文 / 判断词 / 模糊） |

`options` 元素形如 `{"optionCode": str, "optionsContent": str, ...}`（服务端原样）。

#### 模块函数

| 函数 | 说明 |
|---|---|
| `normalize(value) -> str` | NFKC → strip → lower → 去空白 → 去标点 |
| `strip_question_number(value) -> str` | 去题干开头 `1.` / `2、` / `第3题` |
| `strip_option_prefix(value) -> str` | 去选项字母前缀 `"D）20%"` → `"20%"` |
| `option_letter_map(options) -> (dict[str,str], str)` | `(字母→optionCode, "prefix"｜"index")` |
| `load_rows(path) -> list[list[str]]` | 按扩展名读 `.xlsx/.xlsm/.docx/.json/.csv/.tsv/.txt` |
| `load_items_from_file(path) -> list[dict]` | 同上，输出统一条目（JSON 保留 `answer_options`） |

#### `aes.py` / `captcha.py`

| 符号 | 签名 | 说明 |
|---|---|---|
| `aes_ecb_encrypt_b64` | `(plaintext: bytes, key: str) -> str` | AES-128-ECB + PKCS7 → Base64；`key` 必须 UTF-8 后恰好 16 字节，否则 `ValueError` |
| `CaptchaOffset` | `NamedTuple(x: int, y: int, score: float)` | 匹配结果，`score` 为平均像素差（越小越像） |
| `solve_offset` | `(original_base64: str, piece_base64: str) -> CaptchaOffset` | 失败抛 `ValueError` |

---

### 3.9 `hwklr.features.cprog`（C程序设计）

```python
from hwklr.features.cprog import CProgrammingFeature
from hwklr.features.cprog.ai import AIClient, AIError, INITIAL_MAX_TOKENS, MAX_OUTPUT_TOKENS, \
    THINKING_LEVELS, analysis_question_info, generate_solution, next_thinking_level, \
    normalize_thinking_level, extract_json, resolve_api_key
from hwklr.features.cprog.models import (Course, CourseStructure, Part, ProblemRef, ProblemDetail,
    TestCase, QuestionAnalysis, SolutionDraft, TestCaseResult, Consequence, IndexRow, RecordItem)
from hwklr.features.cprog.site import BASE_URL, DEFAULT_TIMEOUT, MoodleError, MoodleSite, SubmitError, get_consequence
from hwklr.features.cprog.parsers import (clean_text, parse_courses, parse_course_title,
    parse_programming_index, parse_problem_page, parse_consequence, parse_history_submit_ids,
    parse_login_token, is_logged_in, login_error_message, extract_activity_id, extract_io_cell,
    result_is_terminal, deterministic_structure)
```

#### `CProgrammingFeature`（动作见 §6.2）

内部状态（重要，理解状态机时按此对账）：

| 字段 | 类型 | 含义 |
|---|---|---|
| `_site` | `MoodleSite\|None` | 主会话 |
| `_logged_in` | `bool` | 登录态 |
| `_courses` | `list[Course]` | 课程列表缓存 |
| `_course` / `_structure` | `Course` / `CourseStructure\|None` | 当前课程与分组结构 |
| `_details` | `dict[int, ProblemDetail]` | 题面缓存（按 module_id） |
| `_analyses` | `dict[int, QuestionAnalysis]` | 启发讲解缓存 |
| `_last_consequences` | `dict[int, Consequence]` | 最近一次判题结果 |
| `_attempts` | `dict[int, int]` | 已用提交次数（上限 5） |
| `_solutions` | `dict[int, SolutionDraft]` | 题解代码缓存 |
| `_job` / `_job_thread` | `dict` / `Thread\|None` | 题解后台任务状态 |

锁：`_state_lock: RLock`（包住除 `get_state` / `get_solution_job` 外的所有动作）、`_job_lock: Lock`（包住 `_job`）。

#### `ai.py`

常量：

| 常量 | 值 | 含义 |
|---|---|---|
| `INITIAL_MAX_TOKENS` | `5000` | 首次输出预算 |
| `MAX_OUTPUT_TOKENS` | `20000` | 输出预算上限 |
| `THINKING_LEVELS` | `("off","low","high","max")` | 思考等级序列 |
| `THINKING_AUTO` | `"auto"` | 自动档位名 |
| `DEFAULT_MODEL` | `"deepseek-flash"` | — |
| `DEFAULT_BASE_URL` | `"https://api.deepseek.com"` | — |

```python
class AIClient:
    def __init__(self, setting: dict) -> None      # model/base_url/provider/thinking_level/api_key
    model: str
    base_url: str
    thinking_mode: str                              # 规范化后的 "auto"|"off"|"low"|"high"|"max"
    auto_thinking: bool                             # @property，等价 thinking_mode == "auto"
    def resolve_thinking_level(self, level: str|None = None) -> str   # None/auto → "off"
    def chat_json(self, system: str, user: str,
                  max_tokens: int = INITIAL_MAX_TOKENS,
                  thinking_level: str|None = None) -> dict            # 失败抛 AIError
```

`chat_json` 内部：`from openai import OpenAI`（延迟导入，`timeout=180.0, max_retries=1`）、`response_format={"type":"json_object"}`、最多 3 次尝试、每次解析失败把预算翻倍（≤20000）、重试时在 user prompt 追加 `_REPAIR_HINT`。

思考参数只在 `provider == "deepseek"` 或 `base_url` 含 `"deepseek"` 时下发：

```python
{"extra_body": {"thinking": {"type": "disabled"}}}                                   # level == "off"
{"extra_body": {"thinking": {"type": "enabled"}}, "reasoning_effort": level}          # 其他等级
```

模块函数：

| 函数 | 签名 | 说明 |
|---|---|---|
| `normalize_thinking_level` | `(value) -> str` | 非法值 → `"auto"` |
| `next_thinking_level` | `(level: str) -> str` | `off→low→high→max`（到顶不变）；`auto`→`"off"` |
| `extract_json` | `(text: str) -> dict` | 容忍 ```json 围栏与前后噪声；失败抛 `AIError` |
| `resolve_api_key` | `(setting: dict) -> str` | `setting.api_key` → `HOMEWORKKILLER_API_KEY` → （按 provider）`DEEPSEEK_API_KEY` / `OPENAI_API_KEY` |
| `analysis_question_info` | `(client, detail, previous=None, course_name="", part_name="", max_tokens=5000, thinking_level=None) -> QuestionAnalysis` | 六段式讲解 |
| `generate_solution` | `(client, detail, analysis, previous=None, max_tokens=5000, thinking_level=None) -> SolutionDraft` | 完整 C 代码 |

#### `models.py`

全部提供 `to_payload() -> dict`。`@dataclass`：`Course(id, name)`、`Part(index, name, problems)`、`ProblemRef(part_name, title, module_id, activity_id, my_result, submit_count, number)`、`CourseStructure(course_name, parts, source, warning)`；`NamedTuple`：`TestCase(no,input,output,time_limit,memory_limit)`、`ProblemDetail(title,statement,test_cases,module_id,activity_id,time_limit,memory_limit,raw_text)`、`QuestionAnalysis(6 段)`、`SolutionDraft(solution_title,explanation,code,notes)`、`TestCaseResult(11 字段)`、`Consequence(is_ac,status,current_status,summary,compile_message,failed_cases,all_cases,submit_id,raw_text)`、`IndexRow(part_name,title,module_id,activity_id,my_result,submit_count)`、`RecordItem(part_name,number,title,detail)`。

> 注意 `ProblemDetail.to_payload()` **不输出 `raw_text`**（体量大），`Consequence.to_payload()` **输出 `raw_text`**。

#### `site.py`

```python
MoodleSite(base_url: str = "https://citel.bjtu.edu.cn/mlsv3", timeout: float = 30.0)
```

| 方法 | 签名 | 说明 |
|---|---|---|
| `clone` | `() -> MoodleSite` | 复制 Cookie 的独立会话（**不重新登录**，避免旧会话被踢） |
| `login` | `(username, password) -> tuple[bool, str]` | `(成功?, 错误信息)`；密码由调用方给（本项目固定 `f"{username}@Bjtu"`） |
| `get_courses` | `() -> list[Course]` | 解析 `my/`；未登录或无课抛 `MoodleError` |
| `get_course_page` | `(course_id: int) -> tuple[str, str]` | `(标题, HTML)` |
| `get_index_rows` | `(course_id: int) -> list[IndexRow]` | `mod/programming/index.php`；空结果抛 `MoodleError` |
| `get_my_results` | `(course_id: int) -> dict[int, tuple[str,int]]` | `{module_id: (result, submit_count)}` |
| `get_problem` | `(module_id: int) -> ProblemDetail` | `view.php?id=` |
| `resolve_activity_id` | `(module_id: int) -> int \| None` | 从题目页四个链接模式里找 `a=` |
| `get_submit_ids` | `(activity_id: int) -> list[int]` | `history.php?a=`；最新在前 |
| `has_any_ac` | `(module_id, activity_id=None, limit=12) -> tuple[bool,str]` | 回查历史提交是否曾 AC |
| `submit` | `(activity_id, code, language="gcc") -> int \| None` | 返回最新 submit_id；未被接受抛 `SubmitError` |
| `fetch_result` | `(activity_id, submit_id=None) -> Consequence` | 单次读取判题页 |
| `poll_consequence` | `(activity_id, submit_id=None, timeout=150.0, interval=2.0) -> Consequence` | 轮询到终止或超时 |
| `get_consequence`（模块级） | `(site, activity_id, submit_id=None, timeout=150.0) -> Consequence` | `poll_consequence` 的薄封装 |

异常：`MoodleError(RuntimeError)`、`SubmitError(MoodleError)`。

#### `parsers.py`

| 函数 | 说明 |
|---|---|
| `clean_text(str) -> str` | 去 `\xa0`、去行尾空白、压空行、`strip` |
| `parse_login_token(html) -> str` | `<input name="logintoken">` |
| `is_logged_in(html) -> bool` | 含 `page-my-index` 或 `login/logout.php` |
| `login_error_message(html) -> str` | `#loginerrormessage` / `.loginerrors` / `"Invalid login"` |
| `parse_courses(html) -> list[Course]` | `a[href*=course/view.php?id=]`，按出现顺序去重 |
| `parse_course_title(html, fallback="") -> str` | 去 `Course:` 前缀 |
| `parse_programming_index(html) -> list[IndexRow]` | 需 ≥7 列；跳过 `class="lastrow"` |
| `parse_problem_page(html, module_id=0) -> ProblemDetail` | `#description` + `#presetcode-table` |
| `parse_consequence(html, submit_id=None) -> Consequence` | `#test-result-detail-table`（13 列）+ `.compilemessage` |
| `result_is_terminal(html, consequence) -> bool` | 判题是否结束 |
| `parse_history_submit_ids(html) -> list[int]` | `submitid=` 或 `.diff1` 输入框 |
| `deterministic_structure(rows, course_name) -> CourseStructure` | 按 `part_name` 本地分组，`source="local"` |
| `extract_io_cell(cell) -> str` | 把 `<li><span>line↵</span></li>` 拼成多行文本 |
| `extract_activity_id(html) -> int \| None` | 命中 `submit.php?a=` / `result.php?a=` / `history.php?a=` / `view.php?a=` |

---

### 3.10 `hwklr.features.build`（构建）

```python
from hwklr.features.build import BuildFeature
from hwklr.features.build.packager import (APP_EXE_NAME, PYTHON_EMBED_MIRROR, VERSION_PATTERN,
    BuildError, build_package, pyinstaller_version, python_embed_url, python_embed_version,
    resolve_output_dir, safe_file_name)
from hwklr.features.build.devenv import (app_home, create_dev_venv, dev_env_ready,
    find_system_python, source_path, source_ready, venv_path, venv_ready)
```

#### `packager`

| 符号 | 签名 | 说明 |
|---|---|---|
| `VERSION_PATTERN` | `re.Pattern` = `^\d+\.\d+\.\d+(?:\.\d+)?$` | 版本号闸门 |
| `APP_EXE_NAME` | `"HomeworkKiller4BJTU"` | 默认可执行文件名/程序名 |
| `PYTHON_EMBED_MIRROR` | `"https://mirrors.aliyun.com/python-release/windows"` | embed 包镜像 |
| `pyinstaller_version` | `() -> str` | 未安装返回 `""` |
| `python_embed_version` | `() -> str` | 当前解释器 `x.y.z` |
| `python_embed_url` | `(version: str\|None = None) -> str` | `.../python-<v>-embed-amd64.zip` |
| `resolve_output_dir` | `(value: str) -> Path` | 空 → `<仓库根>/build`；相对路径以仓库根为基准 |
| `safe_file_name` | `(value: str) -> str` | 替换 Windows 非法字符、去首尾点/空格、截 80 字符、保留名前加 `_`、空则用默认名 |
| `build_package` | `(version, dev_build, output_dir, dev_format, dev_features, program_name="", icon_data="", icon_filename="", *, log, set_phase) -> dict` | **完整构建入口**；`log: Callable[[str],None]`，`set_phase: Callable[[str,str,int],None]` |

`build_package` 返回：

```python
{"kind": "directory"|"zip", "path": str, "exe": str,   # zip 时 exe=""
 "size": int, "name": str, "duration": float}
```

抛 `BuildError`（可读文案）或让底层异常冒出（`BuildFeature._run_job` 会捕获并记录堆栈）。

#### `devenv`

| 符号 | 签名 | 说明 |
|---|---|---|
| `app_home` | `() -> Path` | frozen → exe 目录；否则若父目录有 `start.bat`/`BUILD_INFO.json` → 父目录；否则仓库根 |
| `venv_path` | `() -> Path` | `app_home()/HwklrVenv` |
| `source_path` | `() -> Path` | `venv_path()/HwklrSource` |
| `venv_ready` / `source_ready` / `dev_env_ready` | `() -> bool` | 三级就绪判断 |
| `find_system_python` | `() -> tuple[list[str], str] \| None` | 依次试 `py -3`、`python`、`python3`；**排除当前解释器** |
| `create_dev_venv` | `(log: Callable[[str],None]\|None = None) -> dict` | 创建/复用 venv + 迁移源码；返回 `{ready,path,source,python,created,code_extracted}`；失败抛 `RuntimeError` |

---

### 3.11 `hwklr.UI`（窗口层）

```python
from hwklr.UI import BridgeApi, WindowView
```

#### `WindowView`

```python
WindowView(title: str = APP_TITLE, width: int | None = None, height: int | None = None)
```

构造期做 5 件事：

1. `load_config()`，取 `ui.width/height/min_width/min_height`（默认 1100×720，最小 900×620）。
2. `self._context = {"port": 0}`；`self._meta = _build_meta()`。
3. **按 `VIEW_PARAMS` 逐个 `TagView.load(name, universal_param)`**；`universal_param = {"context": self._context, "app_meta": self._meta}`。
4. `_resolve_order()` 强制 `设置` 倒数第二、`关于` 最后，否则 `RuntimeError`。
5. 把每个非 设置/关于 标签的 `settings_group`（**仅当 `field_specs` 非空**）注册进设置页；随后就地填充 `self._meta["features"]`。

| 成员 | 签名 | 说明 |
|---|---|---|
| `order` (prop) | `-> list[str]` | 副本 |
| `tags` (prop) | `-> dict[str, TagView]` | 副本 |
| `active_tag` (prop) | `-> TagView \| None` | — |
| `tags_payload` | `() -> list[dict]` | 见 §4.3 |
| `meta_payload` | `() -> dict` | `app_meta` + 实时 `port` |
| `bridge_call` | `(tag: str, method: str, params: dict\|None = None) -> dict` | 路由 + 四道校验 + 兜底 try/except |
| `start_server` | `() -> int` | 幂等；返回实际端口并写入 `context["port"]` |
| `stop_server` | `() -> None` | 端口复位为 0 |
| `activate_tagview` | `(tagview: TagView) -> None` | 用**窗口内注册的实例**替换入参；`previous.stop()` → `start()` → `window.evaluate_js("window.App && window.App.activate(<name>)")` |
| `run` | `() -> None` | 必须主线程：`start_server` → `webview.create_window(..., js_api=BridgeApi(self))` → 绑定 `events.loaded` → `webview.start(debug=ui.debug, icon=APP_ICON or None)`；`finally` 里停服务 |

窗口参数（写死，除尺寸外不来自配置）：`resizable=True`、`background_color="#2f3ab2"`、`text_select=True`、`min_size=(min_width, min_height)`、`url="http://127.0.0.1:<port>/"`。

#### `BridgeApi`

```python
BridgeApi(window_view: WindowView)
    call(tag: str, method: str, params: dict|None = None) -> dict   # → window_view.bridge_call
    get_tags() -> list[dict]                                        # → window_view.tags_payload()
    get_meta() -> dict                                              # → window_view.meta_payload()
```

> 桥接对象上**只有这三个公开方法**。任何"新增桥接方法"的想法都应该改成"在某个 Feature 里加 action"。

---

### 3.12 `hwklr.UI.tagview`（标签层）

```python
from hwklr.UI.tagview import SettingsTagView, TagView, TagViewBase, ViewParam, VIEW_DATA_DIR
from hwklr.UI.tagview.view_data import ABOUT_NAME, SETTINGS_NAME, VIEW_PARAMS
```

#### `ViewParam`（`NamedTuple`）

```python
function_name: str          # 键/标签名
title: str                  # 标签栏文字
html: str                   # 相对 view_data，如 "hsr/index.html"
css: tuple[str, ...]        # 如 ("hsr/css/hsr.css",)
js: tuple[str, ...]         # 如 ("hsr/js/hsr.js",)
feature_cls: type[Feature]
description: str
```

#### `TagView`

```python
TagView(param: ViewParam, feature: Feature)      # 校验 html/css/js 三个路径存在，缺失抛 FileNotFoundError
TagView.load(name: str, universal_param: dict|None = None) -> TagView   # 唯一推荐构造方式
```

| 成员 | 类型 | 说明 |
|---|---|---|
| `name` / `title` / `description` | `@property -> str` | 取自 `ViewParam` |
| `feature` | `@property -> Feature` | 功能实例 |
| `settings_group` | `@property -> FeatureSettingsGroup` | 直接代理 `feature.settings_group`（抽象约束在此落地） |
| `html_path` | `@property -> Path` | 绝对路径 |
| `describe` | `() -> dict` | `{name,title,description,html_url,css_urls,js_urls}`，URL 前缀 `/view_data/` |
| `start` / `stop` | `() -> None` | 转发 `feature.start()/stop()` |
| `call` | `(method, params) -> dict` | `method` 空或以 `_` 开头抛 `ValueError`，否则 `feature.handle(...)` |

`TagView.load` 遇到 `name == SETTINGS_NAME` 且 `cls is TagView` 时返回 `SettingsTagView`。

#### `SettingsTagView`

```python
register_settings_field(group: FeatureSettingsGroup) -> None
```
内部 `getattr(feature, "register_group")`，不可调用则抛 `TypeError`。

#### `VIEW_PARAMS` 的构建规则

```python
for spec in OFFICIAL_FEATURES:            # 顺序即标签顺序
    模块可导入 → ViewParam(name=spec.name, title=spec.name,
                          html=f"{spec.view_dir}/index.html",
                          css=(f"{spec.view_dir}/css/{spec.view_dir}.css",),
                          js =(f"{spec.view_dir}/js/{spec.view_dir}.js",),
                          description=spec.description)
    模块不可导入 → 跳过
VIEW_PARAMS[SETTINGS_NAME] = ...设置页固定参数...
VIEW_PARAMS[ABOUT_NAME]    = ...关于页固定参数...
```

`SETTINGS_NAME = "设置"`、`ABOUT_NAME = "关于"`（**中文常量，前端也用字面量 "设置"/"关于" 判定**，改动会破坏 base.js 的特判）。

---

### 3.13 `hwklr.UI.server`（本地 HTTP）

```python
UiHttpServer(page_dir: Path, view_data_dir: Path, preferred_port: int = 49152,
             tags_provider: Callable[[], list[dict]] | None = None,
             meta_provider: Callable[[], dict] | None = None)
```

| 成员 | 说明 |
|---|---|
| `port` (prop) | 实际端口；未启动为 `0` |
| `start() -> int` | 从 `preferred_port` 起最多试 100 个端口；全失败抛 `OSError` |
| `stop() -> None` | `shutdown` + `server_close` + `join(timeout=2.0)` |

端点表：

| 方法 | 路径 | 行为 |
|---|---|---|
| GET/HEAD | `/` | `page_dir/index.html` |
| GET/HEAD | `/api/health` | `{"ok": true}` |
| GET/HEAD | `/api/tags` | `tags_provider()` |
| GET/HEAD | `/api/meta` | `meta_provider()` |
| GET/HEAD | `/favicon.ico` | `204` 空响应 |
| GET/HEAD | `/page_data/<rel>` | `page_dir` 下的文件 |
| GET/HEAD | `/view_data/<rel>` | `view_data_dir` 下的文件 |
| 其他 | * | `404` |

所有响应带 `Cache-Control: no-store`；静态文件额外带 `X-Content-Type-Options: nosniff`。路径解析后必须仍在对应根目录内，否则 `403`。

---

## 4. 前端 API

### 4.1 全局运行时 `window.App`

由 `hwklr/UI/page_data/js/base.js` 暴露，**页面脚本唯一可依赖的外部对象**。

| 成员 | 签名 | 说明 |
|---|---|---|
| `App.init()` | `() -> Promise<void>` | DOMContentLoaded 自动调用一次：拉 `/api/tags` + `/api/meta`，渲染标签栏，激活第 1 个标签 |
| `App.activate(name, options?)` | `(string, {force?: bool}) -> Promise<void>` | 切标签主流程（见 §4.2） |
| `App.call(method, params?)` | `(string, object?) -> Promise<ApiResult>` | 调用**当前激活标签**的动作，返回原始结果，不判错 |
| `App.callOk(method, params?)` | `(string, object?) -> Promise<any>` | 同上，失败抛 `Error(result.error)`，成功返回 `result.data`。**业务代码只用这个** |
| `App.toast(message, type?)` | `(string, 'info'\|'success'\|'error'\|'warn') -> void` | 右下角提示，4.2s 自动消失 |
| `App.setLoading(visible, text?)` | `(bool, string?) -> void` | 全局加载遮罩 |
| `App.registerPage(name, page)` | `(string, PageHooks) -> void` | **每个标签页脚本必须调用一次** |
| `App.refreshTags()` | `() -> Promise<Array>` | 重新拉 `/api/tags` 并重渲染标签栏（设置保存后必须调用） |
| `App.openSettings(groupId?)` | `(string?) -> void` | 切到"设置"并高亮指定板块 |
| `App.takeSettingsTarget()` | `() -> string` | 取出并清空待高亮板块（设置页专用） |
| `App.meta` | `@get object` | `/api/meta` 的缓存 |
| `App.active` | `@get string\|null` | 当前标签名 |
| `App.tags` | `@get Array` | 标签元数据副本 |

### 4.2 页面脚本契约（生命周期）

每个 `view_data/<view_dir>/js/<view_dir>.js` 必须是 IIFE，并在末尾注册：

```js
App.registerPage('<标签名>', { init, onActivate, onDeactivate, highlightGroup });
```

| 钩子 | 何时调用 | 参数 | 用途 |
|---|---|---|---|
| `init(container)` | 每次激活、HTML 注入后**立即** | 内容容器 `HTMLElement` | 缓存 DOM 引用、绑定事件。**必须可重复执行** |
| `onActivate()` | `init` 之后、且设置齐全时 | — | 拉取数据、渲染。可 `await` |
| `onDeactivate()` | **下一个**标签激活时 | — | 停定时器、解绑全局监听 |
| `highlightGroup(id)` | 仅在 `App.openSettings(id)` 且已处于设置页时 | 板块 ID | 设置页专用，其他页不要实现 |

**激活主流程**（`base.js: activate()`，顺序不可错）：

```
1. await refreshTags()                       ← 每次都刷新（拿最新的 settings_ok）
2. tag = tags.find(name)；不存在 → throw
3. 若 active === name 或 activating === name → 直接 return（防重入）
4. token = ++activationToken；对旧页调 onDeactivate()
5. setLoading(true)
6. await Promise.all(加载该标签所有 CSS + JS)   ← 同一 URL 只加载一次（Map 缓存）
7. fetch(tag.html_url) → html
8. 若 token 已过期 → 丢弃结果（并发切换保护）
9. content-host.innerHTML = html；renderTabs()
10. await page.init(host)                     ← 旧 DOM 已销毁，必须重建引用
11. 若 tag.settings_ok === false 且 name 不是「设置/关于」：
        弹"请先完成必要设置"模态框 → return（**不调用 onActivate**）
12. await page.onActivate()
13. finally: setLoading(false)
```

**由此得到的三条铁律**

1. 页面状态**不能**放在模块顶层变量里假设"只初始化一次" —— `init()` 每次激活都重跑。
2. 全局监听（`document.addEventListener`）必须在 `init()` 里先解绑再绑定，或放 `onDeactivate()`。参考 `hsr.js` 的 `state.keydownHandler`。
3. 轮询必须用 `setTimeout` 链式自调度（每次成功后重新排期），并在 `done` / 异常 / `onDeactivate` 时清空定时器；**不要用 `setInterval`**。

### 4.3 `/api/tags` 单项结构

```json
{
  "name": "高铁纵横",
  "title": "高铁纵横",
  "description": "登录高铁答题系统，按题库自动匹配答案并提交考试。",
  "html_url": "/view_data/hsr/index.html",
  "css_urls": ["/view_data/hsr/css/hsr.css"],
  "js_urls":  ["/view_data/hsr/js/hsr.js"],
  "settings_ok": true,
  "settings_group": "hsr",
  "missing_settings": [],
  "settings_target": "hsr"
}
```

| 字段 | 语义 |
|---|---|
| `settings_ok` | `group.is_complete()`；`设置`/`关于` 的 `complete_checker` 恒返回 `True`，所以它们的值恒为 `true` |
| `settings_group` | 该功能设置组的 `group_id`；无组为 `""` |
| `missing_settings` | 缺失项可读名列表，如 `["通用：用户名", "高铁纵横：密码"]` |
| `settings_target` | 跳转目标板块：`missing` 里任一项含 **"用户名"** → `"general"`，否则等于 `settings_group` |

`/api/meta`（`WindowView.meta_payload()`）：

```json
{"name": str, "title": str, "version": str, "authors": [str], "description": str,
 "disclaimer": str, "features": [{"name": str, "description": str}], "port": int}
```

### 4.4 HTML / CSS 约定

- 每个标签页 HTML 是**片段**：根节点固定为 `<section class="tag-page ..." id="<前缀>-page">`，**不含** `<html>/<head>/<body>`。
- 公共组件的类名（`base.css` 提供）：`.card` `.card-head` `.card-soft` `.hero` `.hero-badge` `.grid` `.stack` `.row` `.spacer` `.field` `.hint` `.error-text` `.success-text` `.btn`(+`.primary`/`.ghost`/`.danger`/`.small`) `.data-table` `.table-wrap` `.table-empty` `.pill`(+`.ok`/`.warn`/`.bad`/`.info`) `.detail-list` `.modal-backdrop` `.modal` `.modal-close` `.loading` `.spinner` `.toast`(+type) `.toast-host` `.fatal-panel` `.hidden` `.muted` `.mono` `.scroll-area` `.settings-lock-overlay` `.settings-lock-card`。
- 隐藏/显示统一用 `.hidden` 类（`display:none !important` 语义），**不要**直接改 `style.display`。
- 设计令牌在 `base.css: :root` 的 CSS 变量里（`--accent`、`--ok`、`--bad`、`--radius-lg`、`--font` 等）。改配色只改变量，不要在页面 CSS 里硬编码颜色。
- 响应式断点已存在：`@media (max-width: 900px)`、`@media (max-width: 620px)`、`@media (prefers-reduced-motion: reduce)`。新页面样式应复用之。
- 标签页私有 CSS 用页面前缀类（如 `c-*`、`hsr-*`、`build-*`、`settings-*`、`about-*`）避免污染全局。

### 4.5 桥接 vs HTTP：怎么选

| 需求 | 用哪个 | 原因 |
|---|---|---|
| 读/写业务数据 | 桥接 `App.callOk` | 走 `Feature.handle`，有统一错误与串行保护 |
| 读标签列表/元信息 | `App.tags` / `App.meta` / `App.refreshTags()` | 已有缓存与刷新路径 |
| 载入页面资源 | 自动（`App.activate`） | 不要手写 `<script>` |
| 新增只读、无副作用、且与功能无关的接口 | 可在 `server.py` 加端点 | 例如健康检查；但要意识到它跑在 HTTP 线程、不经 `Feature` |

**不要**为了"少写一个 action"而从页面直接 `fetch` 业务数据 —— 绕过了错误兜底、设置门禁与日志。

---

## 5. 配置项参考（`config.json`）

所有键的默认值来自 `hwklr/config.py: DEFAULT_CONFIG`。**新增键必须写进 `DEFAULT_CONFIG`**，否则旧配置文件不会补齐。

| 键 | 类型 | 默认 | 读取方 | 说明 |
|---|---|---|---|---|
| `username` | str | `""` | 设置页 general、hsr、cprog | 学号/账号，两个功能共用 |
| `hsr.password` | str | `""` | hsr | 高铁系统密码（明文） |
| `hsr.enabled` | bool | `true` | hsr/WindowView | 高铁纵横标签是否加载 |
| `c_programming.enabled` | bool | `true` | cprog/WindowView | C 程序设计标签是否加载 |
| `build.enabled` | bool | `true` | build/WindowView | 构建标签是否加载 |
| `build.plugin_template` | str | `""` | build | 新建插件工程使用的模板 zip；空 → 随包模板 |
| `build.plugin_project` | str | `""` | build | 最近选择的插件工程目录 |
| `third-party` | list[str] | `[]` | extensions/WindowView | 已启用的第三方扩展标签名 |
| `c_programming.provider` | str | `"deepseek"` | cprog | `deepseek`/`openai`/`siliconflow`/`local`/`custom` |
| `c_programming.model` | str | `"deepseek-flash"` | cprog | 模型名 |
| `c_programming.base_url` | str | `"https://api.deepseek.com"` | cprog | OpenAI 兼容端点 |
| `c_programming.api_key` | str | `""` | cprog | 为空时回退到环境变量（见 §3.9） |
| `c_programming.thinking_level` | str | `"auto"` | cprog | `auto`/`off`/`low`/`high`/`max` |
| `c_programming.max_concurrency` | int | `1` | cprog | 题解线程数，钳制到 1–8 |
| `c_programming.enable_solution_mode` | bool | `false` | cprog | 题解模式总开关 |
| `c_programming.last_course_id` | int\|null | `null` | cprog | 上次课程，用于自动选中 |
| `build.output_dir` | str | `""` | build/packager | 空 → `<仓库根>/build`；相对路径以仓库根为基准 |
| `build.dev_format` | str | `"executable"` | build | `executable`/`zip`，仅开发构建生效 |
| `build.features` | dict[str,str] | `{"高铁纵横":"release","C程序设计":"release","构建":"dev"}` | build/packager | `dev`/`release` 开发标记 |
| `ui.width` / `ui.height` | int | `1100` / `720` | WindowView | 初始窗口尺寸 |
| `ui.min_width` / `ui.min_height` | int | `900` / `620` | WindowView | 最小尺寸 |
| `ui.debug` | bool | `false` | WindowView | 传给 `webview.start(debug=...)`，开启开发者工具 |
| `network.timeout_seconds` | float | `40` | **仅 hsr 登录** | 高铁 HTTP 超时 |
| `server.preferred_port` | int | `49152` | WindowView | 起始端口，被占用则 +1 顺延（最多 100 次） |

> **易误判点**：`network.timeout_seconds` 对 CITEL 不生效 —— `MoodleSite` 用固定的 `DEFAULT_TIMEOUT = 30.0`，且轮询/提交另有硬编码超时（判题轮询 150s、提交 60s）。
>
> **安全提示**：`username`、`hsr.password`、`c_programming.api_key` 均为明文。`config.json` 已被 `.gitignore` 忽略且不进任何分发包；不要把它打印进日志、不要贴进 issue。

---

## 6. 动作总表（tag × action）

调用方式统一为 `App.callOk('<tag>', {<params>})`。下表 `params` / `data` 均为 JSON 结构。

### 6.1 `高铁纵横`（`HSRFeature`）

| action | params | 成功 `data` | 主要失败原因 |
|---|---|---|---|
| `get_state` | — | `{logged_in, username, has_credentials, bank_count, bank_chapters:[str]}` | 知识库文件缺失 |
| `login` | `{username, password}` | `{username, logged_in}` | 空账号密码 / 验证码多次失败 / 账号密码错 |
| `login_saved` | — | 同 `login` | 配置里没有账号或密码 |
| `logout` | — | `{logged_in: false}` | — （**后端已实现但 UI 无入口**） |
| `list_exams` | — | `{records: [{…服务端字段, status, remaining, available}]}` | 未登录（"请先登录"） |
| `start_exam` | `{exam_id: int}` | `{exam_name, total, hit_count, missing:[{index,content}], risky:[{index,content}], score, submitted:true, exam_id, personal_exam_id, duration}` | ID 无效 / 考试不可作答 / 预检失败 / 提交 `code!=200`（此时 `failure` 带 `data`） |
| `get_bank_info` | — | `{feature:"hsr", versions:[str], latest_version, count, chapters:[str]}` | 无知识库 |

**副作用警告**

- `login` 成功后会 `update_config({"username":…, "hsr":{"password":…}})`，即**把凭据落盘**。
- `start_exam` 会消耗一次作答机会，且**不可撤销**。前端必须先二次确认（`hsr.js` 已有确认模态框）。
- `list_exams` 会给每条记录追加 `status`（`"已截止"`/`"未开始"`/`"次数用完"`/`"可作答（剩余 N 次）"`）、`remaining`（int）、`available`（bool）。
- **连续输错密码会被服务端临时封禁约 10 分钟**（需求 `HSR-4`）。这不是客户端逻辑，UI 只展示服务端错误、不会卡死；**不要写循环重试去"绕过"**，只会延长封禁。

### 6.2 `C程序设计`（`CProgrammingFeature`）

| action | params | 成功 `data` |
|---|---|---|
| `get_state` | — | `{logged_in, username, ai_ready, solution_mode_enabled, courses_loaded, course_name, last_course_id, analysis_cached, job_running}` |
| `load_courses` | — | `{courses:[{id,name}], last_course_id, username}` |
| `select_course` | `{course_id: int}` | `{course_id, course_name, source:"local", warning, parts:[{index,name,problems:[{number,title,module_id,activity_id,my_result,submit_count,solved}]}]}` |
| `analyze_problem` | `{module_id: int, refresh?: bool}` | `{already_solved, detail:{title,statement,test_cases:[{no,input,output,time_limit,memory_limit}],module_id,activity_id,time_limit,memory_limit}, analysis:{6 段}\|null, attempts, remaining, problem:{…}, cached, ai_error}` |
| `submit_problem` | `{module_id: int, code: str}` | `{consequence:{is_ac,status,current_status,summary,compile_message,failed_cases:[…],all_cases:[…],submit_id,raw_text}, attempts, remaining, is_ac, can_retry, problem}` |
| `start_solution_job` | `{module_ids: [int]}` | `{job_id, concurrency, problems:[{module_id,title,status:"等待队列",attempts:0,worker:null}]}` |
| `get_solution_job` | `{job_id?: str}` | 任务快照（见下） |

> `start_solution_job` 返回的 `concurrency` 是**配置值**；实际线程数是 `min(配置值, 题目数)`（`_split_chunks` 的段数），后台线程启动后会把它写进任务快照的 `concurrency` 字段。前端应以轮询到的 `job.concurrency` 为准。

**任务快照结构**（`get_solution_job` 的 `data`）

```json
{
  "job_id": "hex32", "running": true, "done": false,
  "phase": "starting|solution|done|error|idle",
  "message": "已完成 3/10 题",
  "current": 3, "total": 10, "title": "最近的题目名",
  "concurrency": 4,
  "problems": [{"module_id": 1, "title": "…", "status": "AC|等待队列|生成题解|提交中|WA：第2次尝试|AI错误|…", "attempts": 2, "worker": 0}],
  "events": [{"time": "12:00:03", "message": "…", "level": "info|success|warn|error"}],
  "result": {"ac": [...], "failed": [...], "already_ac": [...], "selected": 10} | null,
  "error": ""
}
```

`result` 子项：

| 键 | 单项字段 |
|---|---|
| `ac[]` | `{module_id, title, solution_title, explanation, code, notes, attempts}` |
| `failed[]` | `{module_id, title, status, summary, compile_message, attempts}`（`status` 可能是 `AI_ERROR` / `NO_ACTIVITY_ID` / `SUBMIT_REJECTED` / 判题状态 / `ERROR`） |
| `already_ac[]` | `{module_id, title, message}` |

**题目状态链与配色**（需求 `P2.3-2` 实时状态、`P2.3.1-2` 配色）

```
未提交  →  等待队列  →  生成题解  →  提交中  →  AC
 info       queued       working     submitting     ok

                            └─ 判题失败 →  WA：第1次尝试 → … → 错误：尝试次数过多
                                              bad              bad
```

| 状态文本 | 徽标类 | 颜色 |
|---|---|---|
| `未提交` | `info` | 蓝 |
| `等待队列` | `queued` | 灰 |
| `生成题解` | `working` | 橙 |
| `提交中` | `submitting` | 黄 |
| `AC…` | `ok` | 绿 |
| `错误…` / `AI错误` / 含"失败""无法""异常" / `WA\|TLE\|MLE\|RE\|CE\|PE\|OLE\|TR\|RJ\|MC` 前缀 | `bad` | 红 |
| 其他非空文本 | `warn` | 橙黄（兜底） |

> `statusPillKind()` 的 JSDoc 只声明了 4 种返回值，实际还会返回 `queued` / `working` / `submitting` —— 注释滞后，不是缺陷，改代码时以函数体为准。

**约束与副作用**

- `_ensure_no_job()`：题解任务运行期间，`load_courses` / `select_course` / `analyze_problem` / `submit_problem` / `start_solution_job` **全部**返回失败（"题解模式正在运行…"）。只有 `get_state` 与 `get_solution_job` 可用。
- `submit_problem` 每题上限 **5** 次；`attempts >= 5` 时直接失败。
- `analyze_problem` 命中已 AC 的题会返回 `already_solved: true` 且 `analysis: null`，不调 AI。
- `analyze_problem` 的 `refresh: true` 会带上一次判题结果重新问 AI（用于"根据错误改进讲解"）。
- AI 不可用不会让 `analyze_problem` 失败：会返回降级的 `analysis`（题面摘要）并把原因放进 `ai_error`。
- `start_solution_job` 需同时满足：`enable_solution_mode=true`、AI 配置完整、已选课程、题目非空。
- `events` 最多保留 200 条（`_MAX_EVENTS`），超出丢弃最旧。

### 6.3 `构建`（`BuildFeature`）

| action | params | 成功 `data` |
|---|---|---|
| `get_state` | — | 见下 |
| `start_build` | `{version, dev_build?, program_name?, icon_data?, icon_filename?}` | `{job_id}` |
| `get_job` | `{job_id?: str}` | 任务快照；`job_id` 不匹配返回失败 |
| `setup_dev_venv` | — | `{ready, path, source, python, created, code_extracted, template}` |
| `choose_plugin_project` | — | `{path, name, package, cancelled}`（取消时 path 为空） |
| `create_plugin_project` | `{name, package}` | `{path, name, package}` |
| `test_plugin` | `{project?}` | `{tab, extension}`；临时加载，不写入配置 |
| `start_plugin_build` | `{project?}` | `{job_id}`；结果 `kind="plugin"` |

`get_state` 的 `data`：

```json
{
  "version": "2.3.1", "default_version": "2.3.1.7559", "default_name": "HomeworkKiller4BJTU",
  "buildable": true, "dev_build": false,
  "dev_env_ready": false, "dev_env_path": "…\\HwklrVenv", "dev_source_path": "…\\HwklrVenv\\HwklrSource",
  "python_available": false, "python_path": "",
  "output_dir": "", "output_path": "D:\\…\\build", "dev_format": "executable",
  "features": [{"name": "高铁纵横", "version": "2.1.0", "dev": false}],
  "tool": {"builder": "2.1.3", "pyinstaller": "6.22.3", "available": true,
           "python": "3.15.2", "embed": "3.15.2",
           "embed_url": "https://mirrors.aliyun.com/python-release/windows/python-3.15.2-embed-amd64.zip"},
  "job": {"job_id": "", "running": false, "done": false, "phase": "idle", "message": "",
          "progress": 0, "log": [], "result": null, "error": ""}
}
```

`get_job` 的 `result`（构建成功后）：

```json
{"kind": "directory", "path": "…\\build\\<slug>", "exe": "…\\<exe>.exe",
 "size": 123456789, "name": "程序显示名", "duration": 42.7}
```

**约束**

- `buildable = not sys.frozen`；已打包程序调用 `start_build` 直接失败。
- `version` 必须匹配 `^\d+\.\d+\.\d+(?:\.\d+)?$`，否则失败（前端另有即时校验）。
- 同一时刻只允许一个构建任务；重复 `start_build` 返回"已有构建任务正在运行"。
- `setup_dev_venv` 仅在 `DEV_BUILD=True` 的产物中可用，否则返回"仅开发构建版本可搭建开发环境"；并发调用由 `_dev_lock` 拒绝。
- `log` 最多保留 2000 行。

### 6.4 `设置`（`SettingsFeature`）

| action | params | 成功 `data` |
|---|---|---|
| `get_settings` | — | `{groups: [groupPayload], port: int, version: str}` |
| `save_settings` | `{groups: {group_id: {key: value}}}` | 与 `get_settings` 相同（保存后的最新状态） |
| `get_bank_info` | — | `{banks: [{feature, version, count}]}` |
| `get_extensions` | — | `{extensions, errors, git_available, template_zip, extension_root}` |
| `pick_extension_zip` | — | `{path}`（取消为空） |
| `load_extension_zip` | `{path}` | `{extension, tab}` |
| `load_extension_git` | `{url}` | `{extension, tab}` |
| `set_extension_enabled` | `{name, enabled}` | 与 `get_extensions` 相同 |
| `set_group_enabled` | `{group_id, enabled}` | 与 `get_settings` 相同 |

`groupPayload` = `FeatureSettingsGroup.payload()` = `{group_id, title, description, fields, complete, missing, enabled, enabled_editable}`。

**`save_settings` 语义**

1. 只处理 `groups` 里出现的分组（`group_id` 必须匹配已注册的组）。
2. 每组 `normalize()` → `export()`，异常 `ValueError` 直接变 `failure(str(exc))`。
3. 多组补丁用 `_merge_patch` 递归合并后一次性 `update_config(patch)`。
4. 一个有效分组都没有 → "没有可保存的设置"。

**已知细节**：`save_settings` 只保存提交的分组，未提交的分组保持原值（这是前端"失焦自动保存单组"得以安全工作的前提）。

### 6.5 `关于`（`AboutFeature`）

| action | params | 成功 `data` |
|---|---|---|
| `get_meta` | — | `app_meta`（`name/title/version/authors/description/disclaimer/features`，另含 `version_display`、`software` 与 `plugins`；`port` 恒 0） |

### 6.6 知识库文件格式

**命名**：`hwklr/runtime_data/<feature>_bank_v<major>.<minor>.json`，`feature` 只允许 `[a-z0-9_]`。

当前唯一知识库 `hsr_bank_v1.0.json`：**JSON 数组**，263 条，每条：

```json
{
  "question": "中国铁路历经了几次大提速：",
  "answer": "D",
  "type": "single",
  "chapter": "第一章考试",
  "section": "单选题",
  "answer_options": [{"letter": "D", "text": "六"}]
}
```

| 字段 | 必需 | 说明 |
|---|---|---|
| `question` | 是 | 题干；`Bank` 内部归一化后建索引 |
| `answer` | 是 | 答案原文（字母 / 文本 / 判断词） |
| `type` | 否 | 题型标记，当前逻辑不依赖 |
| `chapter` / `section` | 否 | 章节与题型分组；`get_state.bank_chapters` 与 `get_bank_info.chapters` 取 `chapter` |
| `answer_options` | 否 | **最有价值**：直接给选项原文，可绕过字母顺序问题 |

`Bank` 也接受 `q`/`a`/`t` 短键（`Bank.__init__` 同时识别 `question|q`、`answer|a`、`type|t`）。

---

## 7. 扩展代码的方式（8 个配方）与编码规范

> 每个配方都是"照做即可"的清单。括号里是该步骤对应的源码位置，便于对照。

### 7.A 新增一个功能标签页

**改动清单：1 个新包 + 3 个新资源文件 + 1 处注册。**

**步骤 1** — 建包 `hwklr/features/<pkg>/__init__.py`：

```python
# -*- coding: utf-8 -*-
"""<功能说明>。"""
from __future__ import annotations

import logging
from typing import Any, Final

from hwklr.features.base import ApiResult, Feature, failure, success
from hwklr.features.settings import FeatureSettingsGroup, SettingsFieldSpec

__version__ = "1.0.0"
__author__ = "Gary"
__all__ = ["DemoFeature"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class DemoFeature(Feature):
    """<一句话职责>。"""

    def __init__(self, universal_param: dict[str, Any]) -> None:
        super().__init__(universal_param)
        self._settings_group: FeatureSettingsGroup = self._build_settings_group()

    # ---- 设置组（没有设置项时返回空 field_specs，见 AboutFeature）----
    @property
    def settings_group(self) -> FeatureSettingsGroup:
        return self._settings_group

    def _build_settings_group(self) -> FeatureSettingsGroup:
        def values_getter() -> dict[str, Any]:
            return {"note": ""}
        def exporter(values: dict[str, Any]) -> dict[str, Any]:
            return {"demo": {"note": str(values.get("note") or "")}}
        return FeatureSettingsGroup(
            group_id="demo",
            title="演示",
            description="演示功能的设置。",
            field_specs=(
                SettingsFieldSpec(key="note", label="备注", kind="text", is_necessary=False),
            ),
            values_getter=values_getter,
            exporter=exporter,
            complete_checker=lambda: True,
            missing_getter=lambda: [],
        )

    # ---- 动作分发（用 dict 表，未知动作返回 failure）----
    def handle(self, action: str, params: dict[str, Any]) -> ApiResult:
        handlers = {"get_state": self._action_get_state}
        handler = handlers.get(action)
        if handler is None:
            return failure("未知动作: %s" % action)
        try:
            return handler(params)
        except ValueError as exc:              # 参数/业务错误 → 可读文案
            return failure(str(exc))
        except Exception as exc:               # 兜底，保证错误回传到 UI
            _LOGGER.exception("演示功能未预期异常")
            return failure("操作失败: %s" % exc)

    def _action_get_state(self, params: dict[str, Any]) -> ApiResult:
        return success({"ready": True})
```

**步骤 2** — 建三个资源文件（**目录名 = view_dir**）：

```
hwklr/UI/tagview/view_data/demo/index.html
hwklr/UI/tagview/view_data/demo/css/demo.css
hwklr/UI/tagview/view_data/demo/js/demo.js
```

`demo/index.html`（片段，无 `<html>`）：

```html
<section class="tag-page tag-demo" id="demo-page">
  <div class="hero">
    <div><h1>演示</h1><p>功能说明。</p></div>
    <div class="hero-badge" id="demo-badge">就绪</div>
  </div>
  <section class="card">
    <div class="card-head"><h2>内容</h2></div>
    <p class="hint" id="demo-hint">加载中…</p>
  </section>
</section>
```

`demo/js/demo.js`：

```js
(function () {
  'use strict';
  const PAGE_NAME = '演示';
  const els = {};
  function cacheElements() { els.hint = document.getElementById('demo-hint'); }
  function init(container) { cacheElements(); /* 绑定事件，必须可重复执行 */ }
  async function onActivate() {
    try {
      const data = await App.callOk('get_state');
      if (els.hint) { els.hint.textContent = data.ready ? '就绪' : '未就绪'; }
    } catch (error) {
      App.toast(`读取状态失败: ${error.message}`, 'error');
    }
  }
  App.registerPage(PAGE_NAME, { init: init, onActivate: onActivate });
})();
```

**步骤 3** — 在 `hwklr/features/manifest.py: OFFICIAL_FEATURES` 追加（**顺序决定标签顺序**）：

```python
    FeatureSpec(
        name="演示",
        module="hwklr.features.demo",
        class_name="DemoFeature",
        view_dir="demo",
        description="演示功能，用于验证新增标签页流程。",
    ),
```

**步骤 4** — 可选但建议：

- `hwklr/features/__init__.py` 的 `__all__` 里加 `"DemoFeature"`（仅影响文档/`__all__` 可读性；惰性加载靠 `_FEATURE_IMPORTS` 自动覆盖）。
- 若新增配置分组，在 `hwklr/config.py: DEFAULT_CONFIG` 里加 `"demo": {"note": ""}`，并在 `_migrate_config` 里确保补齐。
- 若要发布构建中也包含它：确认 `build.features` 里不是 `dev`（默认 `release`）。

**验证**：

```powershell
Scripts\python.exe -c "import hwklr.features.demo, hwklr.features.manifest as m; print([s.name for s in m.OFFICIAL_FEATURES])"
Scripts\python.exe main.py     # 新标签应出现在「设置」之前
```

**不要做**：不要改 `WindowView` 的标签顺序逻辑；不要把 `DemoFeature` 直接 import 进 `UI/__init__.py`；不要在 `view_data/__init__.py` 里手写 `ViewParam`（框架已自动构建）。

---

### 7.B 给已有功能加一个动作

1. 在 `handle()` 的分发表里登记动作名（推荐 dict 表；`CProgrammingFeature` 用连续 `if`，两种都存在）。
2. 写 `_action_xxx(self, params) -> ApiResult`：
   - 参数校验失败 `raise ValueError("中文提示")`；
   - 成功一律 `return success({...})`，结构变更需同步本文档 §6。
3. 加日志：`_LOGGER.warning(...)` 用于可预期失败，`_LOGGER.exception(...)` 用于兜底分支。
4. 前端调用：`await App.callOk('xxx', {...})`，并用 `try/catch` 包住提示 `App.toast(error.message, 'error')`。
5. 若动作可能长时间阻塞（网络/编译/打包），**不要**在动作里轮询等待超过几秒 —— 改成"后台线程 + 任务快照"模式（参考 `start_solution_job` / `start_build`）。

**命名约定**：动作名小写 + 下划线；动词开头（`get_` / `list_` / `start_` / `save_` / `load_` / `submit_`）。

---

### 7.C 给功能加一个设置字段

1. 在 `_build_settings_group()` 的 `field_specs` 元组里加 `SettingsFieldSpec(...)`。
2. `values_getter()` 里**必须**返回该 key 的值（否则 `values()` 会取到 `""`）。
3. `exporter()` 里把该 key 写进正确的配置分组（补丁会被 `_merge_patch` 合并）。
4. 若该字段进入"必要设置"判定：同步 `complete_checker()` 与 `missing_getter()`（缺失项文案格式：`"<分组名>：<字段名>"`，且**用户名缺失必须写"通用：用户名"**，前端据此把跳转目标设为 `general`）。
5. 若是新配置键：在 `DEFAULT_CONFIG` 登记默认值；必要时在 `_migrate_config` 补迁移。
6. `kind` 选择见 §3.5 的矩阵。`secret=True` 会自动获得显示/隐藏按钮；`alert=True` 会在保存时弹二次确认。

**验证闭环**：改值 → 失焦 → 检查 `config.json` 真的写入了该键 → 重新进入页面确认回显一致。

---

### 7.D 新增一个独立设置分组

适用：一个功能要拆成多块设置，或一个非标签页模块需要配置入口。

1. 新建 `FeatureSettingsGroup(...)`，`group_id` 唯一（**不要**与 `general`/`hsr`/`c_programming`/`build` 冲突）。
2. 让它出现在设置页：由某个**已注册标签**的 `Feature.settings_group` 返回，或在该 Feature 的构造期调用 `SettingsFeature.register_group`（跨模块耦合，不推荐）。
3. 注意 `WindowView` 只注册 `field_specs` 非空的组。
4. 若要支持"从锁定页跳转高亮"，`group_id` 就是 `App.openSettings(group_id)` 的参数。

---

### 7.E 新增/升级一版知识库

1. 新文件放 `hwklr/runtime_data/<feature>_bank_v<X.Y>.json`（版本号必须是 `数字.数字`）。
2. **不要覆盖旧版本** —— 保留旧文件即可并存，`latest_version()` 会自动选最新。
3. 代码侧无需改动；读取方通过 `runtime_data.load_bank(feature)` 拿最新版。
4. 若新版本改了条目 schema，必须同步改读取方（如 `Bank` 的字段识别）。
5. 升级后 `设置 → 知识库` 表格与 `get_bank_info` 的 `count` 会自动变化，可用于验证。

**注意**：`HSRFeature._bank` 是**进程内一次性缓存**（首次访问时加载），因此新增题库文件后必须**重启应用**才生效。

---

### 7.F 新增一个 HTTP 端点

`hwklr/UI/server.py` 的结构是"处理器读 `self.server` 上挂的属性"：

1. 在 `UiHttpServer.__init__` 增加一个 `xxx_provider` 参数并存成 `self._xxx_provider`。
2. 在 `start()` 里把 `httpd.xxx_provider = self._xxx_provider` 挂到服务器实例上。
3. 在 `_handle_request` 里加分支（记得同时支持 `HEAD`，用 `send_body` 参数）。
4. 在 `WindowView.start_server()` 里把回调传进来。
5. 前端 `fetchJson('/api/xxx')`。

**必守规则**：只 `GET/HEAD`；响应 `Cache-Control: no-store`；涉及文件时用 `_send_file`（自带越界校验），不要自己拼路径；端点返回值必须 JSON 可序列化。

---

### 7.G 新增页面内交互 / 轮询

照抄 `build.js` / `cprog.js` 的任务轮询骨架：

```js
const POLL_INTERVAL = 800;
const state = { jobId: '', timer: null };

function schedulePoll() {
  if (state.timer) { window.clearTimeout(state.timer); }
  state.timer = window.setTimeout(pollJob, POLL_INTERVAL);
}

async function pollJob() {
  if (!state.jobId) { return; }
  if (state.timer) { window.clearTimeout(state.timer); state.timer = null; }
  try {
    const job = await App.callOk('get_job', { job_id: state.jobId });
    render(job);
    if (job.done) { return; }          // 结束时不再排期
    schedulePoll();
  } catch (error) {
    App.toast(`读取进度失败: ${error.message}`, 'error');
    if (state.timer) { window.clearTimeout(state.timer); state.timer = null; }
  }
}

function onDeactivate() {              // 切走时停掉
  if (state.timer) { window.clearTimeout(state.timer); state.timer = null; }
}
```

**要点**：单一轮询链（避免定时器叠加）；`App.active !== PAGE_NAME` 时不要弹结果模态框（`cprog.js` 用 `resultShownJobId` 保证结果只展示一次）；页面被切走再回来要能靠一次 `get_job` 恢复现场。

---

### 7.H 改窗口 / 端口 / UI 外壳

| 目标 | 改哪里 | 注意事项 |
|---|---|---|
| 初始/最小尺寸 | `config.json` 的 `ui.*` | 构造参数 `width`/`height` 优先级更高 |
| 窗口标题 | `hwklr/__init__.py: APP_TITLE` | 导出时 `EXPORT_NAME` 会覆盖 |
| 起始端口 | `config.json: server.preferred_port` | 顺延上限 100；`127.0.0.1` 绑定不可配 |
| 窗口背景色 | `hwklr/UI/__init__.py: _WINDOW_BACKGROUND` | 是模块常量，不在配置里 |
| 开发者工具 | `config.json: ui.debug = true` | 等价 `webview.start(debug=True)` |
| 整体配色/字体/圆角 | `page_data/css/base.css` 的 `:root` 变量 | 不要在标签页 CSS 里硬编码 |
| 页面骨架（标签栏/加载/提示容器） | `page_data/index.html` | 改 id 会破坏 `base.js` |
| 标签栏行为 | `page_data/js/base.js` | 改 `activate()` 顺序要重新核对 §4.2 |
| 图标 | 构建页上传图标，或 `_build_info.ICON_PATH` | 源码运行默认无图标 |

### 7.I 新建文件的头部与注释模板（需求 `D-1`～`D-4` / `S-1`～`S-4`）

**Python 文件头**（照抄，改日期/文件名/用途）：

```python
# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-02 21:30
# 最后更新: 2026-11-02 21:30
# 文件名: demo.py
# 主要用途: 一句话说明这个文件做什么。
# 文件版本: 1.0.0
"""模块 docstring：职责、边界、与其他模块的关系。

关键约束与易错点也写在这里，便于他人（和 Agent）不改代码就理解契约。
"""
from __future__ import annotations
```

**JS / CSS / HTML 文件头**：

```js
/*
  作者: Gary
  编写日期: 2026-11-02 21:30
  最后更新: 2026-11-02 21:30
  文件名: demo.js
  主要用途: 一句话说明。
  文件版本: 1.0.0
*/
```

**四条注释硬规则**

| 规则 | 说明 |
|---|---|
| 函数注释 | Python docstring 必须含 **参数 / 返回 / 异常** 三段；JS 用 JSDoc（`@param` / `@returns` / `@throws`） |
| 类型提示 | 所有参数（`self` 除外）标注类型；难以从上下文判断的局部变量也要标（`course_id: int = ...`） |
| 关键步骤 | 用 `#关键步骤：…` 标注流程中不能删的环节（现有代码到处在用，搜索 `关键步骤` 即可看懂主流程） |
| 私有命名 | 模块内部私有加 `_`；需严格私有的加 `__`（`A-3`） |

> 现成范例：`hwklr/features/build/devenv.py`（Python 头 + 逐函数 docstring + 类型注解齐全）、`hwklr/UI/tagview/view_data/build/js/build.js`（JS 头 + JSDoc）。

---

## 8. 升级与兼容规则

### 8.1 版本号怎么升（规则出自需求 `D-5` / `S-8`，案例出自 `drction` §12.1、§14.8）

| 变更类型 | 版本位 | 例（真实历史） |
|---|---|---|
| 新增功能（新标签页、新子系统） | **第二位 +1** | `2.0.0 → 2.1.0`（V2.1.0 构建）、`2.1.3 → 2.2.0`、`2.2.0 → 2.3.0` |
| 修复影响正常运行的 bug，或优化已有功能 | **第三位 +1** | `2.0.0 → 2.0.1`；`2.1.0 → 2.1.1 / 2.1.2 / 2.1.3`；`2.3.0 → 2.3.1` |
| 用户明确指定版本号 | 按用户要求 | `2.1.0` / `2.2.0` / `2.3.0` 都是用户点名的 "versionX.Y.Z" |
| 初始版本 | 固定 `1.0.0` | `1.0.0` |

三条配套硬规则（需求 `D-5` / `S-8`、`drction` §12.1）：

1. **改哪个文件，就同步该文件头部的"文件版本"并追加"最后更新"**；未修改的文件保持原版本。
2. 包版本（`hwklr.__version__`）与本次变更类型同步，不要只改文件头不改包版本。
3. 包版本必须是三段式 `x.y.z` —— `_default_export_version()` 只取前三段再拼时间戳模数。

> **需求文档自身有一处不一致，已核对**：`drction` §12.1 的表格写"修复影响正常运行的 bug → 提高 **0.1.0**"（第二位 +1），但同一节的应用记录与 `§14.8 版本记录` 全部按"**第三位 +1**"执行（`2.0.1`、`2.0.2`、`2.1.3`、`2.3.1`…）。**以应用记录与实际历史为准**，上表即按此整理。改版本号前扫一眼 `§14.8`，别造出第四种风格。

### 8.2 配置兼容

- **只加键，不删键。** 加键必须写 `DEFAULT_CONFIG`（`load_config` 的深合并会自动为旧文件补齐）。
- 删键/改键名必须在 `_migrate_config` 里迁移，且迁移必须**幂等**（可重复执行不产生副作用）。
- `_migrate_config` 只在 `load_config` 成功后内存中执行；真正的落盘发生在下次 `save_config`/`update_config`。

### 8.3 动作兼容

- 动作名是**跨端契约**：改名必须在同一提交内改完 JS 与本文件 §6。
- 未知动作返回 `failure("未知动作: …")`，不会崩 —— 这让"先加后端、后加前端"是安全的顺序。
- 返回结构**只增不改**：前端必须对缺失字段给默认值（现有代码普遍用 `data.x || ''` / `Array.isArray(...)` 防御）。

### 8.4 设置字段兼容

- `key` 一旦发布就视为稳定；语义变化要么换 key + 迁移，要么在 `exporter` 里做兼容读取。
- `field_specs` 的顺序即渲染顺序，插入新字段会改变 UI 布局（无兼容性问题，但需在文档里反映）。
- `group_id` 变更会让 `App.openSettings(group_id)` 的跳转目标失效。

### 8.5 知识库兼容

- 新增版本 = 新增文件，**不改旧文件**。
- 删除旧版本会让 `get_bank_info.versions` 变化；如果用户配置里记录了版本号会失效（当前无此配置）。
- 条目 schema 变更必须同步 `Bank` 与所有读取 `item["..."]` 的地方。

### 8.6 构建产物兼容

- `BUILD_INFO.json` 的键 `app / exe_name / version / dev_build / format / features / built_at` 是产物的公开元数据，**不要随意改名**。
- `_build_info.py` 的变量名 `EXPORT_VERSION / EXPORT_NAME / DEV_BUILD / ICON_PATH` 是约定，改名要同步 `hwklr/__init__.py`。
- 产物目录命名 `{exe_name}-v{version}[-dev]` 被 `_reset_artifact`（只允许删 `output_root` 直接子目录）与用户惯例依赖。

---

## 9. 改完自检清单

复制这段，逐条打勾：

```
[ ] 1. 导入检查：Scripts\python.exe -c "import hwklr; import hwklr.UI; import hwklr.features.<pkg>"
       —— 新功能模块必须能被单独 import；否则标签页会静默消失
[ ] 2. 启动检查：Scripts\python.exe main.py —— 窗口打开、标签数量正确、顺序为 <功能...> 设置 关于
[ ] 3. 动作检查：每个新 action 都能从 UI 触发，失败时 toast 显示中文可读文案
[ ] 4. 设置闭环：改设置 → 失焦 → config.json 落盘 → 重新进页面回显一致
[ ] 5. 门禁检查：清空 username 后，功能标签应弹"请先完成必要设置"并显示遮罩
[ ] 6. 重入检查：反复切换标签 5 次，页面功能仍可用（无重复监听、无重复定时器）
[ ] 7. 依赖检查：没有在模块顶层新增重量级 import（PIL/openai/requests/bs4 必须延迟导入）
[ ] 8. 序列化检查：新返回结构不含 bytes/set/datetime/自定义对象
[ ] 9. 版本检查：包版本、受影响模块 __version__ 已按 §8.1 升级
[ ] 10. 文档检查：本文件 §5/§6 与 03 对应章节已同步（见 README §5 维护约定）
[ ] 11. 打包检查（改了 build 或新增功能时）：构建页跑一次发布构建，产物能启动且功能数量正确
```

---

## 10. 反模式（禁止事项）

| 反模式 | 为什么不行 | 正确做法 |
|---|---|---|
| 在 `main.py` 里写业务逻辑 | 破坏唯一入口约定，打包与测试都变复杂 | 全部下沉到 `hwklr.features` |
| 功能里 `import webview` 或操作 DOM | 功能层不得依赖 UI 层，否则无法脱离窗口测试 | 只通过 `handle()` 返回数据 |
| 页面脚本直接 `fetch` 业务数据 | 绕过统一错误兜底、动作闸门与日志 | 走 `App.callOk` |
| 新增第二个桥接方法 | `BridgeApi` 是固定门面，加方法会让前端要区分多套协议 | 在对应 Feature 加 action |
| 在 `Feature.__init__` 里做网络请求 | 构造发生在窗口初始化阶段，会把启动拖慢/卡死 | 首次用到时惰性初始化（参考 `HSRFeature._bank`） |
| 模块顶层 `import openai/PIL/requests/bs4` | 启动变慢；打包无法排除这些模块 | 函数内延迟导入 |
| 用 `setInterval` 做轮询 | 会和上一轮未完成的请求叠加，且无法优雅停止 | `setTimeout` 链式自调度 + `onDeactivate` 清理 |
| 直接把 `config.json` 内容打进日志/异常 | 泄露密码与 API Key | 只记录键名与是否配置 |
| 修改已发布动作的名字/返回结构 | 破坏前端契约，症状是"点了没反应" | 新增动作或新增字段 |
| 手工编辑 `_build_info.py` / `BUILD_INFO.json` | 会被下次构建覆盖，且可能制造版本不一致 | 走构建页 |
| 在 `view_data/__init__.py` 手写新功能的 `ViewParam` | 绕过 `OFFICIAL_FEATURES` 单一事实源，构建裁剪会失效 | 只改 `manifest.py` |
| 让标签页脚本假设"DOM 只渲染一次" | `activate()` 每次都会重注入 HTML | 在 `init()` 里重新取元素、重新绑事件 |
| 在功能里 `print()` 调试 | 打包后 `--windowed` 无控制台，日志丢失 | 用 `logging.getLogger(__name__)` |
| 把知识库塞进 `.py` 常量 | 违反 `runtime_data` 约定，无法分版本 | 放 `runtime_data/*.json` |

---

**下一步**：需要理解"为什么这么实现"时，读 [`03-technical-deep-dive.md`](03-technical-deep-dive.md)。

