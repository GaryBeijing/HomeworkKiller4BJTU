# HomeworkKiller4BJTU 参考文档（总索引）

> 本目录是 **唯一权威的项目参考文档**。目标读者：需要在本仓库里读代码、改代码、加功能的 AI Agent（第一优先），以及接手维护的人类开发者（第二优先）。

---

## 0. 文档基线（判断文档是否过期用）

| 项 | 值 |
|---|---|
| 包版本 `hwklr.__version__` | `4.4.2` |
| 基线提交 | `771935b`（`main` 分支）基础上实现 Version 3.0.0（2026-11-03）、3.0.1（2026-11-04）、3.1.0、4.1.0（2026-11-08）、4.1.1、4.2.0、4.3.0、4.3.1、4.3.2、4.4.0、4.4.1 与 4.4.2（2026-11-10） |
| **需求基线** | `SoftwareIntro/function_requirements.md`（需求台账，已勾到 `4.4.2`）+ `SoftwareIntro/drction+rqrmnts(org).md`（编号化需求与验收记录，同步 `4.4.2`）。**这两份是需求与验收的主契约，优先级高于本文档。** |
| 运行时 | CPython 3.15.2（Windows，venv，`PYTHONUTF8=1`） |
| 关键三方库 | `pywebview 6.2.1`、`openai 3.42.0`、`requests 2.34.2`、`beautifulsoup4 4.15.0`、`Pillow 13.0.0`、`pyinstaller 6.22.3` |
| 文档编写时间 | 2026-11-02（2026-11-03 回填 3.0.0；2026-11-04 回填 3.0.1；2026-11-08 回填 3.1.0 与 4.0.0；2026-11-09 回填 4.1.1、4.2.0、4.3.0、4.3.1 与 4.3.2；2026-11-10 回填 4.4.0、4.4.1 与 4.4.2） |
| 代码规模 | Python ≈ 9 600 行（其中 `hwklr` 9 548 行），前端 JS/CSS/HTML ≈ 7 300 行；不含 `build/`、`Lib/`、`Scripts/` |

**过期判据**：若 `hwklr/__init__.py` 的 `__version__`、`hwklr/features/manifest.py` 的 `OFFICIAL_FEATURES`、或 `hwklr/config.py` 的 `DEFAULT_CONFIG` 与本文档描述不一致，说明文档已落后于代码 —— 以代码为准，并回填本文档。若 `SoftwareIntro/function_requirements.md` 出现新的 `[x]` 版本或新增需求条目，说明需求已推进 —— 以需求文档为准，并检查本文档 `01 §5.3` 的 roadmap 是否过期。

---

## 1. 文档结构与阅读策略

文档被拆成 **1 个索引 + 3 个部分**。这是有意为之：Agent 通常只需要读其中一部分，拆分避免每次都吞下几万字上下文。

| 文件 | 内容 | 什么时候读 |
|---|---|---|
| `README.md`（本文件） | 总索引、速查卡、硬性约束、术语表 | **每次开始工作前必读，约 3 分钟** |
| [`01-project-overview.md`](01-project-overview.md) | 第 1 部分：项目介绍、项目结构、分层架构、**参考资料范围与需求编号导航**、版本体系 | 第一次接触本仓库；或需要判断某个目录/文件干什么、某条要求出自哪里 |
| [`02-api-reference.md`](02-api-reference.md) | 第 2 部分：完整 API 参考（Python / 前端 / HTTP / 配置 / 动作表）+ **编写升级与扩展代码的 8 个配方** + 反模式 | 要写代码、要调用某个类、要加功能、要加设置项 |
| [`03-technical-deep-dive.md`](03-technical-deep-dive.md) | 第 3 部分：逐子系统的技术实现原理（每节"总览 → 细节"）、线程模型、时序、算法、已知限制 | 要调试、要重构、要理解"为什么这么设计"、要实现同类逻辑 |

### 1.1 三条约定，能省你很多时间

1. **章节号即锚点。** 一级标题统一为 `## N. 标题`，二级为 `### N.N 标题`。用 `grep -n '^##' Reference/02-api-reference.md` 列出全部章节，用 `grep -n '^### 4\.2' Reference/02-api-reference.md` 精确定位，不必全文阅读。
2. **路径一律相对仓库根目录**，用正斜杠书写，例如 `hwklr/features/base.py`。仓库根 = `D:\B1_Projects\HomeworkKiller4BJTU`。
3. **符号一律写成 `模块.类.方法`**，例如 `hwklr.UI.WindowView.bridge_call`、`Feature.handle`。第三方符号会标注来源库。

### 1.2 推荐的 Agent 工作流

```
0. 先用 01 §5.1 的编号表在需求文档里定位相关条目       （确认"该不该做、怎么算做完"）
1. 读本文件 §2 速查卡 + §3 硬性约束                   （必做）
2. 用 §2.2 的任务表定位要改的文件                       （30 秒）
3. 只读 02 中对应的 API 小节，不要通读
4. 需要"为什么"时再跳 03 的对应章节
5. 改完按 02 §9 的检查清单自检
6. 按需求文档要求回填：function_requirements 打勾 + drction 写"实现 + 验收"
```

---

## 2. 30 秒速查卡

### 2.1 启动与运行

```powershell
# 唯一入口（等价于双击 run.bat）
D:\B1_Projects\HomeworkKiller4BJTU\Scripts\python.exe main.py
```

- `main.py` 只做一件事：`WindowView().run()`。**没有任何业务逻辑**，不要往里加。
- 配置写在仓库根目录 `config.json`（首次运行自动生成默认值；打包后位于 exe 同级目录）。
- UI 通过 `http://127.0.0.1:<port>/` 载入，默认端口 49152，被占用则向后顺延。

### 2.2 我要做 X，该动哪个文件

| 任务 | 主改文件 | 连带改 |
|---|---|---|
| 新增一个功能标签页 | `hwklr/features/<name>/__init__.py`（新文件）+ `hwklr/features/manifest.py` | `hwklr/UI/tagview/view_data/<view_dir>/` 三件套 |
| 给已有功能加一个动作 | 该功能的 `handle()` 分发 + 处理函数 | 对应 `view_data/<view_dir>/js/*.js` |
| 加一个设置项 | 该功能 `_build_settings_group()` 里的 `SettingsFieldSpec` | 同处 `values_getter` / `exporter` |
| 加一个设置分组 | 新增 `FeatureSettingsGroup`，由 `Feature.settings_group` 返回 | 无需改设置页，`WindowView` 自动注册 |
| 加一版知识库 | 放 `hwklr/runtime_data/<feature>_bank_vX.Y.json` | 无需改代码（同名扫描） |
| 加 HTTP 端点 | `hwklr/UI/server.py` 的 `_handle_request` | 前端 `fetch('/api/...')` |
| 改窗口尺寸/标题/图标 | `config.json` 的 `ui.*`；标题走 `hwklr/__init__.py` | — |
| 改打包行为 | `hwklr/features/build/packager.py` | `hwklr/features/build/__init__.py` 的设置项 |
| 改前端公共样式/行为 | `hwklr/UI/page_data/css/base.css`、`js/base.js` | — |

### 2.3 五个最高频的"我懵了"及其答案

| 现象 | 原因 | 位置 |
|---|---|---|
| 新功能类写好了但标签页不出现 | 模块导入抛异常被静默吞掉，`load_feature_class()` 返回 `None` 就跳过该标签 | `hwklr/features/manifest.py:77`、`hwklr/UI/tagview/view_data/__init__.py:65` |
| 前端调用报"未知动作" | 动作名没进 `handle()` 的分发表，或名字以 `_` 开头被闸门拦掉 | `base.py` 子类 `handle`、`UI/__init__.py:289`、`tagview/__init__.py:209` |
| 标签切换后页面元素全失效 | `activate()` 会 `innerHTML = html` 重注入 DOM 并重新 `init()`；旧监听器必须解绑 | `page_data/js/base.js:401` 与各页 `init()` |
| 设置保存了但功能仍说"未配置" | `complete_checker` 与 `values_getter` 读的键不一致，或缺 `exporter` 落盘 | 各功能 `_build_settings_group()` |
| 打包后功能消失 | 该功能被标记 dev 并被发布构建裁剪；`构建` 功能在发布构建里**永远**被裁剪 | `packager.py:209` |

---

## 3. 硬性约束（改动前必须遵守，违反会产生静默故障）

> 这些是架构层面的不变量，不是风格建议。每一条都在代码里有强制逻辑，破坏后多半**不报错、只是行为变怪**。

1. **`main.py` 保持极薄。** 只允许 `WindowView()` + `run()`；任何业务逻辑都放进 `hwklr`。
2. **标签顺序不变量：功能标签在前，`设置` 倒数第二，`关于` 最后。** 由 `WindowView._resolve_order()` 二次校验，违反直接抛 `RuntimeError`。
3. **UI 与功能之间只能通过 `Feature.handle(action, params)` 通信。** 不允许前端直接 import Python，也不允许功能层 import `webview`。
4. **所有跨桥返回值必须 `dict` 且 JSON 可序列化，顶层必有 `ok` 布尔字段。** 用 `success()` / `failure()` 构造，不要手写。
5. **动作名不得以下划线开头。** `WindowView.bridge_call` 与 `TagView.call` 各拦一道。
6. **每个 `Feature` 子类必须实现 `settings_group` 抽象属性。** 没有设置也要返回空 group（参考 `AboutFeature`）。空 `field_specs` 的 group 不会被注册进设置页。
7. **新增官方功能必须同时登记 `OFFICIAL_FEATURES`**，否则 UI 不建标签、构建不打包、设置页不显示开发标记。
8. **`config.json` 永不进分发包，也永不提交。** 里面是明文密码与 API Key。
9. **不要给 `hwklr/features/*` 引入新的顶层重量级 import。** 三方库一律在函数内部延迟导入（现状：`PIL`、`openai`、`requests`、`bs4`、`openpyxl`、`docx` 全部延迟导入）。这条直接决定启动速度。
10. **`hwklr/features/build/vendor/*.zip` 是下载缓存**，不进产物、不要手改。

### 3.1 代码规范（需求 `D-` / `S-` 系列，同样是硬约束，验收会查）

| 规范 | 要求 | 需求编号 |
|---|---|---|
| **文件头** | 每个代码文件开头必须写：作者、编写日期（精确到分钟）、文件名、主要用途、文件版本；**修改过的文件追加"最后更新"**。HTML/CSS/JS/BAT 用各自注释语法 | `D-1` / `S-1` |
| **包元数据** | 每个 `__init__.py` 必须写 `__version__`、`__all__`、`__author__` | `A-2` / `S-5` |
| **函数注释** | Python docstring（参数 / 返回 / 异常），JS 用 JSDoc | `D-2` / `S-2` |
| **类型提示** | 所有参数（`self` 除外）标注类型；难以从上下文判断的局部变量也要标 | `D-3` / `S-3` |
| **关键步骤注释** | 用 `#关键步骤：…` 形式（JS/CSS/HTML 用各自注释语法） | `D-4` / `S-4` |
| **私有命名** | 模块内私有加单下划线 `_`；需严格私有的加双下划线 `__` | `A-3` |
| **版本号** | 新增功能 → 第二位 +1；修 bug / 优化实现 → 第三位 +1；用户指定版本时从其要求。**改了哪个文件就同步该文件的"文件版本"** | `D-5` / `S-8`（细则与案例见 `02 §8.1`） |
| **运行环境** | 一切安装 / 运行 / 测试都用项目 venv（`Scripts\python.exe`）；依赖写入 `requirements.txt`，用清华源安装 | `D-6` / `S-6` |
| **批处理编码** | `.bat` 用 ASCII 或与系统代码页一致的编码（避免中文 Windows 把 UTF-8 当 GBK 解析坏命令） | `S-7` |

> 现有代码 100% 遵守上述文件头与 docstring 规范。新增文件照抄现有文件的头部即可，例如 `hwklr/features/build/devenv.py` 前 8 行。

---

## 4. 术语表

| 术语 | 含义 | 代码坐标 |
|---|---|---|
| **Feature** | 一个功能的业务实现，抽象基类，只认 `handle(action, params)` | `hwklr/features/base.py` |
| **TagView** | 一个标签页 = 一套前端资源 + 一个 Feature 实例的绑定体 | `hwklr/UI/tagview/__init__.py` |
| **WindowView** | 窗口层：建标签、定顺序、起 HTTP 服务、开 pywebview、转发桥接 | `hwklr/UI/__init__.py` |
| **BridgeApi** | 暴露给 JS 的 `window.pywebview.api` 对象，只有 `call/get_tags/get_meta` 三个方法 | `hwklr/UI/__init__.py:54` |
| **universal_param** | 窗口注入给每个 Feature 的通用参数：`{"context": {"port": int}, "app_meta": {...}}` | `hwklr/UI/__init__.py:139` |
| **ApiResult** | 统一返回结构 `{"ok": bool, "data": any, "error": str}` | `hwklr/features/base.py:28` |
| **FeatureSpec** | 功能清单项：名称 / 模块 / 类名 / 资源目录 / 说明 | `hwklr/features/manifest.py:29` |
| **ViewParam** | 标签页静态参数：名称 / 标题 / html / css / js / 功能类 / 说明 | `hwklr/UI/tagview/view_data/__init__.py:40` |
| **FeatureSettingsGroup** | 一个功能在设置页里的板块：字段定义 + 读值/导出/完整性回调 | `hwklr/features/settings.py:63` |
| **page_data** | 全局共用前端资源（页面骨架、公共 CSS/JS） | `hwklr/UI/page_data/` |
| **view_data** | 每个标签页私有的 HTML/CSS/JS | `hwklr/UI/tagview/view_data/<view_dir>/` |
| **动作（action）** | 前端发起的一次功能调用名，如 `list_exams` | 各 Feature 的 `handle()` |
| **知识库（bank）** | `runtime_data` 下按功能分版本的 JSON 数据 | `hwklr/runtime_data/` |
| **发布构建 / 开发构建** | 裁剪后的发行包 / 含全部功能+文档+源码的包 | `hwklr/features/build/packager.py` |

---

## 5. 文档维护约定

改动代码后，按下表检查是否要同步本文档；**不确定时宁可加一句，也不要让文档撒谎**。

| 你改了什么 | 必须更新 |
|---|---|
| **新增 / 变更需求** | `SoftwareIntro/function_requirements.md`（登记条目，完成后 `[]`→`[x]`）+ `SoftwareIntro/drction+rqrmnts(org).md`（编号、【原文】/【约束】标记、验收记录）；本文件 §0 需求基线、`01 §5.3` roadmap |
| 新增/删除/重命名功能 | `01` §3.2、`02` §6、`03` §8 |
| 新增/修改动作 | `02` §6 动作总表、`03` 对应子系统章节 |
| 新增配置字段 | `02` §5 配置项参考 |
| 改设置字段类型/语义 | `02` §3.5、`03` §7 |
| 改打包流程/产物布局 | `02` §3.10、`03` §13 |
| 改线程模型或锁 | `03` §1、§2 |
| 包版本号变化 | 本文件 §0 基线表 + `01` §6 |

---

**下一步**：若你是第一次接触本仓库，请继续读 [`01-project-overview.md`](01-project-overview.md)。
