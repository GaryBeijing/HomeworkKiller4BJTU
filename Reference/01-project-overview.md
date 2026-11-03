# 第 1 部分 · 项目介绍、项目结构、参考资料范围与用途

> 目标：让你在 10 分钟内知道"这是个什么项目、代码在哪、我该改哪里、需求与验收依据在哪、哪些东西别碰"。
>
> 读完本文后应当能回答：这个程序怎么跑起来的？UI 是怎么搭起来的？新增功能要落在哪几个目录？需求文档的编号（`HSR-16`、`P2.3-4`）怎么查？哪些需求还没做？

---

## 目录

- [1. 项目介绍](#1-项目介绍)
  - 1.1 一句话定位
  - 1.2 它实际提供的三个功能
  - 1.3 目标用户与使用边界
  - 1.4 不是什么
- [2. 技术选型](#2-技术选型)
- [3. 项目结构](#3-项目结构)
  - 3.1 顶层目录总表
  - 3.2 `hwklr` 包逐文件职责
  - 3.3 UI 资源的双目录约定
  - 3.4 被 `.gitignore` 屏蔽但对理解项目重要的路径
- [4. 分层架构](#4-分层架构)
  - 4.1 五层视图
  - 4.2 一次前端点击的完整旅程
  - 4.3 解耦手段清单
- [5. 参考资料的范围与用途](#5-参考资料的范围与用途)
  - 5.1 需求编号导航（Agent 最该先学会用的一张表）
  - 5.2 使用规则（三条，别违反）
  - 5.3 仍未完成的需求（roadmap，别当成已实现）
  - 5.4 与现行代码的偏差（以代码为准）
- [6. 版本号体系与发布形态](#6-版本号体系与发布形态)
- [7. 阅读路线](#7-阅读路线)

---

## 1. 项目介绍

### 1.1 一句话定位

**面向北京交通大学学生的桌面学习辅助工具**：一个 Python 后端 + 本地 Web UI 的多标签页应用，把"高铁答题系统自动作答"和"C 语言程序设计课程作业辅助（启发式讲解 / 自动题解）"封装成可点击的桌面软件，并自带一键打包导出能力。

### 1.2 它实际提供的三个功能

三个功能在代码里是三个平级的 `Feature` 实现，也对应 UI 里三个标签页：

| 标签页 | 实现 | 一句话职责 | 联网对象 |
|---|---|---|---|
| **高铁纵横** | `hwklr/features/hsr/` | 登录高铁答题系统，用内置题库（263 题）按**选项原文**匹配答案，自动答题并提交 | `http://59.64.5.158/prod-api`（明文 HTTP） |
| **C程序设计** | `hwklr/features/cprog/` | 登录 CITEL（Moodle）读课程题目；**启发模式**给六段式讲解让人自己写码，**题解模式**让 AI 直接生成完整 C 代码并自动提交、按判题结果迭代修正 | `https://citel.bjtu.edu.cn/mlsv3` + OpenAI 兼容 API |
| **构建** | `hwklr/features/build/` | 把当前源码导出为「PyInstaller 目录版可执行文件」或「python-embed + zip 免安装包」，支持功能裁剪、图标、名称、四段版本号 | 阿里云镜像（下载 python-embed） |

另有两个**框架级**标签页，不是 `OFFICIAL_FEATURES` 的成员，由 `view_data/__init__.py` 硬编码追加：

- **设置**（`hwklr/features/settings.py`）：通用账号 + 各功能注册进来的设置板块 + 运行信息 + 知识库清单。
- **关于**（`hwklr/features/about.py`）：应用名、版本、作者、功能列表、免责声明。

### 1.3 目标用户与使用边界

- 用户是**学生本人**，用自己的学号登录自己的账号。
- 程序不含任何绕过鉴权的逻辑：高铁走正常登录（含滑块验证码自动识别），CITEL 走标准 Moodle 表单登录。
- 所有凭据只存本机 `config.json`，不上传。
- `hwklr/__init__.py` 内的 `APP_DISCLAIMER` 是产品级声明：题解模式会直接生成并提交完整代码，仅在"十分需要真实实例"时使用。**任何新功能都不得与之矛盾的表述。**

### 1.4 不是什么

- 不是 Web 服务：HTTP 服务只监听 `127.0.0.1`，且只服务静态资源与两个只读 API，唯一的动态入口是 pywebview 的 JS 桥。
- 不是插件系统：功能集合目前是**编译期**（源码期）确定的，通过 `OFFICIAL_FEATURES` 静态清单登记，打包时按清单裁剪，没有运行期加载外部插件的能力。**但"第三方扩展加载"已是已登记、未实现的 v3 需求**（见 §5.3），改动时不要断言"永远不会有插件"。
- 不是多用户：进程内只有一个 `WindowView`，一份 `config.json`，一个账号态。

---

## 2. 技术选型

| 关注点 | 选择 | 为什么（代码中能验证的理由） |
|---|---|---|
| 桌面外壳 | `pywebview 6.2.1` | 直接复用系统 WebView2，无需自带浏览器内核；`js_api` 提供 Python↔JS 桥 |
| UI | 原生 HTML + CSS + 原生 JS（无框架、无构建步骤） | 前端资源即文件，`TagView` 按路径下发，改完刷新即可；无 npm 工具链 |
| 静态资源服务 | 自建 `ThreadingHTTPServer`（`hwklr/UI/server.py`） | 需要"固定起始端口 + 端口顺延"、需要同时暴露 `page_data` 与 `view_data` 两个资源根、需要两个只读 API。pywebview 内置服务做不到这些 |
| 配置 | 单个 `config.json`，集中由 `hwklr/config.py` 读写 | 禁止各模块自己拼路径；支持默认值深合并与旧版迁移 |
| 知识库 | `hwklr/runtime_data/*.json`，按 `<feature>_bank_v<major>.<minor>.json` 命名 | 版本可并存，运行期选最新版 |
| 网络 | `urllib`（高铁）、`requests`（CITEL）、`openai` SDK（AI） | 三种来源协议差异大，各用最合适的 |
| HTML 解析 | `beautifulsoup4` + **`html.parser`**（非 lxml） | 有意去掉 lxml：省 ~7MB 二进制、避免打包体积；已对全部页面快照验证两种后端输出一致 |
| 打包 | `PyInstaller --onedir` + 自研 python-embed zip 组装 | 目录版启动快、体积小；zip 版免安装、可迁移 |
| 加密 | 自实现 AES-128-ECB（`hwklr/features/hsr/aes.py`） | 只为复刻 crypto-js 的验证码坐标加密，避免引入 `cryptography` 依赖 |

依赖清单（`requirements.txt`，**必须与之一致**）：

```
pywebview==6.2.1   Pillow==13.0.0   openpyxl==3.1.5   python-docx==1.2.0
requests==2.34.2   beautifulsoup4==4.15.0   lxml==6.1.3   openai==3.42.0   pyinstaller==6.22.3
```

> **注意**：`lxml` 虽然在 `requirements.txt` 里，但**代码中从未 import**（`parsers.py` 固定用 `html.parser`），且打包时被显式 `--exclude-module lxml`。它是历史遗留依赖。
> `openpyxl` / `python-docx` 只被 `hwklr/features/hsr/bank.py` 的**多格式题库导入**函数使用，而当前 UI 没有该入口 —— 发布构建会把它们排除。

---

## 3. 项目结构

### 3.1 顶层目录总表

```
HomeworkKiller4BJTU/
├── main.py                  ← 唯一入口（43 行）
├── config.json              ← 运行期配置（git 忽略，含明文凭据）
├── requirements.txt         ← 依赖锁定
├── run.bat                  ← 用项目 venv 启动（git 忽略）
├── .gitignore
├── hwklr/                   ← 全部实现（详见 3.2）
├── Reference/               ← 本文档
├── build/                   ← 历史构建产物（git 忽略）
├── SoftwareIntro/           ← 需求与设计资料（git 忽略）
├── legacy/                  ← 原型代码 B1.0 / B_CHelper（git 忽略）
├── .vscode/                 ← 编辑器本地配置（git 忽略）
├── Include/ Lib/ Scripts/   ← venv 产物（git 忽略）
├── pyvenv.cfg               ← venv 描述（git 忽略）
└── __pycache__/             ← 字节码缓存
```

| 路径 | 是否入库 | 作用 | Agent 能不能改 |
|---|---|---|---|
| `main.py` | 是 | 只 `WindowView().run()` | 可改，但**只允许**改启动参数/日志配置；业务一律下沉 |
| `hwklr/` | 是 | 全部实现 | 主战场 |
| `Reference/` | 是 | 本文档 | 可改（见 `README.md` §5 维护约定） |
| `config.json` | 否 | 运行期配置 | **不要提交**、不要把真实值写进文档/日志 |
| `run.bat` | 否 | 开发启动脚本（设置 `PYTHONUTF8=1`、`chcp 65001`、异常时 `pause`） | 可改，但不入库 |
| `requirements.txt` | 是 | 依赖锁定 | 加依赖时同步；注意"延迟导入"约束 |
| `build/` | 否 | 历史产物 + `build/.work/` 临时目录 | 不要改；可整目录删除 |
| `SoftwareIntro/` | 否 | 需求文档与问题截图（见 §5） | 不要改；仅作历史参考 |
| `legacy/` | 否 | 原型 `B1.0/`、`B_CHelper/` | 不要改；**不参与运行** |
| `.vscode/` | 否 | 编辑器 `files.exclude` | 无关 |
| `Include/ Lib/ Scripts/ pyvenv.cfg` | 否 | venv | 无关 |
| `hwklr/features/build/vendor/*.zip` | 否 | python-embed 下载缓存（13.7MB，`python-3.15.2-embed-amd64.zip`） | 不要手改；删了会自动重下 |

### 3.2 `hwklr` 包逐文件职责

行数为实际统计值，用于判断"这个文件值不值得读"。

```
hwklr/
├── __init__.py                     64 行    包元数据：版本、APP_*、DEV_BUILD；可选读取 _build_info.py
├── config.py                      223 行    config.json 唯一读写口：DEFAULT_CONFIG / load / save / update / 迁移
│
├── features/                                ── 功能层 ──
│   ├── __init__.py                 66 行    统一导出 + PEP 562 惰性 __getattr__（按需加载可选功能）
│   ├── base.py                    122 行    Feature 抽象基类、success()/failure()、ApiResult
│   ├── manifest.py                108 行    ★ OFFICIAL_FEATURES 单一事实源 + load_feature_class/feature_version
│   ├── about.py                   250 行    AboutFeature + AboutMetadataGroup（动作：get_meta）
│   ├── extensions.py              700 行    ★ 第三方扩展扫描/校验/导入/启停 + 插件工程模板与发布包构建
│   ├── versions.py                 70 行    软件/插件版本显示格式（vA.B.PatchC-bD / A.BpC-bD）
│   ├── settings.py                760 行    SettingsFieldSpec / FeatureSettingsGroup / SettingsFeature
│   ├── hsr/                                 ── 高铁纵横 ──
│   │   ├── __init__.py            598 行    HSRFeature：动作分发、考试状态判定、答案匹配编排、提交 payload
│   │   ├── client.py              335 行    HsrClient：验证码→登录→考试列表→预检→开考→提交→答卷详情
│   │   ├── bank.py                659 行    Bank：题干归一化、精确/模糊匹配、答案→选项编码解析、多格式题库导入
│   │   ├── aes.py                 149 行    AES-128-ECB + PKCS7（复刻 crypto-js），含 FIPS-197 自检
│   │   └── captcha.py             130 行    滑块拼图匹配（Pillow ImageChops 差值最小化）
│   ├── cprog/                               ── C 程序设计 ──
│   │   ├── __init__.py           1412 行    CProgrammingFeature：状态机、启发分析、提交、**题解后台任务**
│   │   ├── ai.py                  567 行    AIClient（严格 JSON）+ 两套提示词 + 思考等级/预算升级
│   │   ├── models.py              291 行    12 个数据结构，全部带 to_payload()
│   │   ├── parsers.py             643 行    纯 HTML 解析：登录/课程/题目/判题结果/提交历史/本地分组
│   │   └── site.py                463 行    MoodleSite：登录、课程、题目、提交、判题轮询、会话克隆
│   └── build/                               ── 构建 ──
│       ├── __init__.py            542 行    BuildFeature：构建表单状态、后台任务、开发环境入口、设置板块
│       ├── packager.py           1080 行    build_package()：裁剪、PyInstaller、embed zip、图标、版本资源
│       ├── devenv.py              376 行    HwklrVenv 创建 + 源码迁移到虚拟环境内部
│       └── vendor/                          python-embed 下载缓存（不入库）
│
├── runtime_data/                            ── 知识库 ──
│   ├── __init__.py                 92 行    BANK_DIR / list_banks / list_versions / latest_version / load_bank
│   └── hsr_bank_v1.0.json       3985 行    高铁题库，263 条，list[dict]，字段见 02 §6.6
│
└── UI/                                      ── UI 层 ──
    ├── __init__.py                400 行    ★ WindowView + BridgeApi
    ├── server.py                  290 行    UiHttpServer：端口顺延、静态资源、/api/tags、/api/meta、路径穿越防护
    ├── page_data/                           ── 全局共用前端资源 ──
    │   ├── index.html              30 行    页面骨架：#tabbar / #content-host / #loading / #toast-host
    │   ├── css/base.css           739 行    设计令牌（:root 变量）+ 全部公共组件
    │   └── js/base.js             528 行    ★ 前端运行时 window.App：标签渲染、激活、资源加载、桥接、提示
    └── tagview/
        ├── __init__.py            241 行    ★ TagView / TagViewBase / SettingsTagView
        └── view_data/
            ├── __init__.py        120 行    ★ ViewParam + VIEW_PARAMS（由 OFFICIAL_FEATURES 动态构建）
            ├── <view_dir>/index.html          标签页私有 HTML 片段
            ├── <view_dir>/css/<view_dir>.css  标签页私有样式
            └── <view_dir>/js/<view_dir>.js    标签页私有逻辑（IIFE + App.registerPage）
```

`<view_dir>` 现有五个：`hsr`、`cprog`、`build`（来自 `OFFICIAL_FEATURES`），以及 `settings`、`about`（框架内置）。

### 3.3 UI 资源的双目录约定

| | `hwklr/UI/page_data/` | `hwklr/UI/tagview/view_data/<view_dir>/` |
|---|---|---|
| 归属 | 全局，整个应用一份 | 每个标签页一份 |
| 内容 | 页面骨架 `index.html`、`base.css`、`base.js` | `index.html`（**只是片段**，不含 `<html>`）、`css/*.css`、`js/*.js` |
| 下发 URL | `/page_data/...` | `/view_data/...` |
| 加载时机 | 首屏由 `page_data/index.html` 引 `base.css` + `base.js` | 切到该标签时由 `App.activate()` 动态 `<link>` / `<script>` 注入，**每个 URL 只加载一次** |
| 硬约束 | 不要引入外部 CDN | 文件名必须与 `view_dir` 同名：`<view_dir>/css/<view_dir>.css`、`<view_dir>/js/<view_dir>.js`（由 `view_data/__init__.py:_feature_param` 拼死） |

> `TagView.__init__` 会**启动时校验**三类文件是否存在，缺失直接抛 `FileNotFoundError` 并终止启动 —— 这是少见的"快速失败"路径。

### 3.4 被 `.gitignore` 屏蔽但对理解项目重要的路径

`.gitignore` 当前忽略：`/B*/`、`/Include/`、`/Lib/`、`/Scripts/`、`/SoftwareIntro/`、`/pyvenv.cfg`、`.vscode/`、`/legacy/`、`__pycache__/`、`*.pyc`、`/config.json`、`/run.bat`、`/build/`、`hwklr/features/build/vendor/*.zip`。

其中四个需要理解（**不要因为"被忽略"就当它不存在**）：

1. **`config.json`** —— 运行期唯一配置，含真实学号/密码/API Key。字段结构见 `02 §5`。打包时不复制。
2. **`SoftwareIntro/`** —— 需求与问题资料，且**被构建功能引用**：`packager._DEV_EXTRA_DIRS` 会把 `SoftwareIntro`、`B1.0`、`B_CHelper` 复制进开发构建产物。注意 `B1.0` / `B_CHelper` 现已移到 `legacy/` 下，`_copy_dev_extras` 用 `is_dir()` 判断后**静默跳过**，所以现在开发构建里只会附带 `SoftwareIntro`。
3. **`legacy/`** —— 旧原型（`B1.0/` 高铁原版、`B_CHelper/` C 作业助手原版）。`hsr` 与 `cprog` 的 docstring 明确写了"Remaster 自 B1.0 / B_CHelper"，**行为语义的最终解释权在原版，但运行期完全不依赖它**。
4. **`hwklr/features/build/vendor/*.zip`** —— 构建用的 python-embed 缓存。已缓存 `python-3.15.2-embed-amd64.zip`，与当前解释器 3.15.2 一致，所以"开发构建 + zip"不需要联网下载。

---

## 4. 分层架构

### 4.1 五层视图

```
┌────────────────────────────────────────────────────────────────────┐
│ ① 前端运行时 window.App（page_data/js/base.js）                    │
│    标签页脚本：IIFE → App.registerPage(name, {...})                │
└────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                 ┌─────────────────┴─────────────────┐
                 ▼                                   ▼
┌────────────────────────────────┐  ┌────────────────────────────────┐
│ ② BridgeApi（业务通道）        │  │ ②′ UiHttpServer（资源通道）    │
│    call / get_tags / get_meta  │  │    静态文件 · 2 个只读 API     │
└────────────────────────────────┘  └────────────────────────────────┘
                 │                                   │
                 └───────────────────────────────────┘
                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│ ③ 窗口层 WindowView                                                │
│    建标签 · 定顺序（设置倒二、关于最后）· 注册设置组 · 转发桥接    │
└────────────────────────────────────────────────────────────────────┘
                                   │
                 TagView.load(name, universal_param)
                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│ ④ 标签层 TagView（= 前端资源 + Feature 实例）                      │
│    describe() 渲染 · call() 转发 · settings_group 只读代理         │
└────────────────────────────────────────────────────────────────────┘
                                   │
              Feature.handle(action, params) → ApiResult
                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│ ⑤ 功能层 Feature（业务实现）                                       │
│    hsr / cprog / build / settings / about                          │
│    向下可用：config.py · runtime_data · 各自子模块                 │
└────────────────────────────────────────────────────────────────────┘
```

**依赖方向严格单向向下**：⑤ 不 import ④，④ 不 import ③ 之外的东西，① 只知道 ② 的 URL 与三个桥接方法。唯一的例外是 `hwklr/UI/tagview/view_data/__init__.py`（属于 ④ 的资源注册表）需要引用 ⑤ 的类来构造 `ViewParam`，这是"注册表"的必然代价，但引用的是**类型**而非实例。

### 4.2 一次前端点击的完整旅程

以点击"高铁纵横 → 刷新列表"为例，这条链路是全项目的标准形制：

```
[1] hsr.js  els.refresh 的 click 回调
        ↓  App.callOk('list_exams')
[2] base.js  callOk → call → waitForBridge()
        ↓  window.pywebview.api.call('高铁纵横', 'list_exams', {})
[3] BridgeApi.call(tag, method, params)                 hwklr/UI/__init__.py
        ↓  WindowView.bridge_call(...)
[4] 校验：标签存在？method 是字符串且不以 '_' 开头？params 是 dict？
        ↓  TagView.call(method, params)
[5] 再校验一次方法名非法 → ValueError
        ↓  Feature.handle('list_exams', {})
[6] HSRFeature.handle：查分发表 → _action_list_exams
        ↓  self._ensure_client().exam_list()   # 阻塞的 HTTP 请求
[7] HsrClient._request → urllib → 解析 JSON
        ↓  记录装饰（status/remaining/available）
[8] return success({"records": [...]})
        ↑  逐层原样返回（③ 再兜底 try/except）
[9] base.js  callOk 检查 result.ok，返回 result.data
[10] hsr.js  renderExams() 渲染表格
```

关键点：**第 3～8 层之间没有任何类型转换**，一路都是 `dict`。UI 不需要知道业务对象的类，业务不需要知道 DOM。

### 4.3 解耦手段清单（这是本项目的核心设计资产）

| 手段 | 实现位置 | 解决什么 |
|---|---|---|
| **单一动作入口** `handle(action, params)` | `features/base.py` | 前端与功能之间只有一个函数签名，新增动作不改协议 |
| **统一返回结构** `ApiResult` | `features/base.py` | 前端只需判 `ok`；异常被转成 `error` 字符串，不抛到 JS |
| **单一事实源清单** `OFFICIAL_FEATURES` | `features/manifest.py` | "有哪些功能"只写一处；UI 建标签、构建裁剪、设置页开发标记三处消费 |
| **资源目录约定** `<view_dir>/index.html|css/<view_dir>.css|js/<view_dir>.js` | `view_data/__init__.py` | 新增标签页零注册成本，路径全自动拼 |
| **设置组自注册** `Feature.settings_group` + `SettingsTagView.register_settings_field` | `features/settings.py`、`UI/__init__.py` | 设置页不认识任何具体功能，只认识"设置组"抽象 |
| **回调式设置** `values_getter` / `exporter` / `complete_checker` / `missing_getter` | `FeatureSettingsGroup` | 设置页能读写任意功能的配置，而完全不 import 该功能 |
| **惰性导入** PEP 562 `features.__getattr__` + `load_feature_class` | `features/__init__.py`、`manifest.py` | 裁剪掉的功能模块不存在也不会崩，只是少一个标签 |
| **延迟导入三方库** | 各功能内部（`PIL`/`openai`/`requests`/`bs4`） | 启动只加载真正要用的库；打包时可整模块排除 |
| **数据类与 `to_payload()`** | `cprog/models.py` | 业务对象与 JSON 之间只有一层显式转换，字段改动集中 |
| **前后端生命周期契约** `{init,onActivate,onDeactivate}` | `page_data/js/base.js` | 页面重注入后能可靠地重建 DOM 引用与事件 |

---

## 5. 参考资料的范围与用途

`SoftwareIntro/` **不是历史资料，而是本项目的需求与验收基线**。其中 `function_requirements.md` 与 `drction+rqrmnts(org).md` 由每版需求逐条累积而成，并随 `2.3.1` 同步更新；前者是需求原文台账（打勾表示已实现），后者是带编号与验收记录的主契约，自述"后续所有开发、重构、验收任务的统一依据"。

> **优先级**：需求文档 > 本参考文档 > 代码注释。当本文件与需求文档冲突时，以需求文档为准，并回填本文件。

| 文件 | 行数 | 性质 | 用途 | 可信度 |
|---|---|---|---|---|
| `SoftwareIntro/README.md` | 9 | 项目定位原文（目的、产品设想） | "这个软件为什么存在"的唯一出处；`APP_DESCRIPTION` 的语义来源 | **最高**（原文） |
| `SoftwareIntro/tech_direction.md` | 30 | **架构技术指导**（V1 起草，未随版本更新） | 目录结构、模块规范、UI/核心方案的设计动机；已被 `drction` §3–§5 工程化展开并编号 | 高（架构依据）；个别措辞被后续决策覆盖，见 §5.4 |
| `SoftwareIntro/function_requirements.md` | 310 | **版本需求台账 + 完成状态**：V1.0 → 2.3.1 逐版需求原文，条目 `[]` → `[x]` 表示已实现；末尾 `version3`、`version 铺垫更新` 为**未完成**需求 | 判断"某个行为是不是需求"查这里；新需求也登记在这里 | **最高**（需求原文） |
| `SoftwareIntro/drction+rqrmnts(org).md` | 1181 | **方向与需求整理版（已同步到 2.3.1）**：带编号体系（`G/A/UI/C/D/S/ENV/NFR/HSR/Q/ISSUE/P*`）、歧义决策记录、工单记录、开源署名、每版实现说明与**验收实测数据** | 开发与验收的**主契约**：动手前对照【原文】/【约束】，完成后回填验收 | **最高**（唯一验收依据） |
| `SoftwareIntro/issue/README.md` + 6 张截图 | 51 | 工单现象与截图（ISSUE-1/2/3） | 回归线索；ISSUE-1/2 已在 1.0.1 修复，处理结果见 `drction` §12.3 | 高（记录准确，问题已修） |
| `SoftwareIntro/UI.png` | — | 初始视觉稿 | 标签栏/内容区视觉基线（激活高亮、非激活浅色、深色内容区） | 中（现 UI 已演进） |
| `legacy/B1.0`、`legacy/B_CHelper` | — | 原型源码（只读） | "原版行为到底怎么判"的最终解释权；`hsr` / `cprog` 的行为语义来源（`drction` §6.2、§13） | 高（对"原版行为"而言） |

### 5.1 需求编号导航（Agent 最该先学会用的一张表）

`drction+rqrmnts(org).md` 用编号体系组织了全部要求。**定位需求时用编号 grep，比通读 1181 行快一个数量级。**

| 前缀 | 含义 | 条目数 | grep 示例 |
|---|---|---|---|
| `G-` | 项目目标与用户 | 4 | `grep -n 'G-2' SoftwareIntro/drction+rqrmnts\(org\).md` |
| `A-` | 架构与模块规范（唯一入口、`__init__` 三件套、私有命名、高解耦） | 6 | `A-4` |
| `UI-` | UI 技术与标签栏规则（pywebview、49152 顺延、`TagView`、顺序不变量、响应式） | 18 | `UI-14` |
| `C-` | 核心要求（Feature 抽象、配置、`runtime_data`、解耦与性能） | 15 | `C-10` |
| `D-` / `S-` | 代码规范与版本规则 / 脚本编写规范 | 6 + 8 | `D-5`（版本号）、`S-2`（docstring） |
| `ENV-` | 运行环境与依赖（venv、requirements、跨平台、`run.bat`） | 6 | `ENV-2` |
| `NFR-` | 非功能需求（解耦、响应性、健壮性、可维护性、安全、AI 可控、合规） | 8 | `NFR-7` |
| `HSR-` | **高铁纵横必须保真的 40 条原版行为**（登录/验证码/列表/状态判定/匹配/提交/题库） | 40 | `HSR-16`（按选项原文匹配） |
| `Q-` | 歧义决策记录（`§11.1` 已确认 6 条、`§11.2` 待确认 4 条） | 10 | `Q-3`（配置路径） |
| `ISSUE-` | 工单与处理结果（含截图名） | 3 | `ISSUE-2` |
| `P1-/P2-/P2.1-/P3-/P2.2-/P2.3-/P2.3.1-` | **各版本的工单级实现与验收项**（`§14.10`–`§14.18`） | 30+ | `P2.3-4`（分段规则） |

配套的版本结构：

| 位置 | 内容 |
|---|---|
| `§2` | 逐版范围（1.0 → 2.3.1），每版"原文 + 摘要" |
| `§10` | **V1.0 验收清单**（全部 `[x]`，含实测说明与"未执行项"） |
| `§14.7` | **V2 验收清单**（全部 `[x]`） |
| `§14.8` | **版本记录表**（1.0.0 → 2.3.1 每版的日期与变更摘要）—— 写 CHANGELOG 或判断"这行为是哪版加的"直接查它 |
| `§14.9` | **已知限制**（与本文档 `03 §17` 互补，偏产品视角） |
| `§14.10`–`§14.18` | 每版"工单要求 → 实现 → 验收（含实测数字/桩测试断言）" |

### 5.2 使用规则（三条，别违反）

1. **标注语义**：`【原文】` 直接来自参考文件，**不得擅自更改**；`【解读】` 是对原文的工程化拆解，可优化；`【推断】` 是参考文件未明确时的默认方案，实施前可调整；`【约束】` 是实现时必须遵守的硬规则。
2. **完成即回填**：一个版本/条目完成后，在 `function_requirements.md` 对应标题与子项把 `[]` 改成 `[x]`（`drction` §2.12），并在 `drction` 的该版小节补"实现 + 验收"记录。
3. **验收要有证据**：现有验收记录都写了具体依据（实测尺寸、断言数量、桩测试调用序列、真实 AC 结果、包体/启动数字）。新增验收请沿用这个标准，不要只写"已验证"。

### 5.3 仍未完成的需求（roadmap，别当成已实现）

| 需求 | 出处 | 现状 | 架构影响 |
|---|---|---|---|
| **参考文档（HTML 版）**：以 HTML 编写，置于 `SoftwareIntro/Reference/Manual`、`SoftwareIntro/Reference/API Reference`、`SoftwareIntro/Reference/Tech Design Docs` | `function_requirements.md` §"建立参考文档" | **以 Markdown 形式在 `Reference/` 落地**（本目录三个部分与上述三份文档一一对应），HTML 版未做 | 若将来要 HTML 版，可从本目录三个 md 转换，不必重写内容 |
| `version3` 主体需求 | `function_requirements.md` §`version3.0.0` | **已完成（3.0.0）**：虚拟环境新布局、插件构建、扩展加载/启停、关于页元信息与版本格式、功能启用开关 | 运行期扩展注册表已落地：`features/extensions.py`、`UI/tagview/view_data` 的可变扩展参数、`/extensions/<id>/...` 资源路由 |

### 5.4 与现行代码的偏差（以代码为准）

1. `tech_direction.md` 说"每个功能的 UI 定制内容放 `view_data`，实例化参数放 `hwklr.tagview` 的 `view_data.py`" → 实际是 `hwklr/UI/tagview/view_data/__init__.py`（包路径演进为 `hwklr.UI.*`）。
2. `tech_direction.md` 说"所有设置放 `../config.json`" → 实际固定在**项目根目录**（`main.py` 同级），打包后在 exe 同级。
3. `tech_direction.md` 说"知识库放置到 `runtime_data` 模块中，每一个功能对应的知识库单独一个 dict 格式变量" → 实际是 `hwklr/runtime_data/` **包** + 每功能每版本一个 JSON 文件（`<feature>_bank_vN.N.json`），由 `runtime_data/__init__.py` 提供读取接口（`drction` C-9～C-13、Q-10）。原 `runtime_data.py` 已删除。
4. `tech_direction.md` 要求"同时适配 Windows / macOS / Linux" → 代码只在 `server.py`（`SO_REUSEADDR`）、`devenv.py`（`CREATE_NO_WINDOW`、venv 路径）等处做了 `sys.platform` 分支，**仅 Windows 实机验证过**；构建产物（`start.bat`、exe、版本资源）是 Windows 专用（`drction` §14.9 已列为已知限制）。

`legacy/B1.0`、`legacy/B_CHelper` 是 `hsr` / `cprog` 的原型实现，**不参与运行、不参与打包**，只在需要核对"原版到底怎么判的"时查阅（`drction` §6.2 把"必须保真的原版行为"整理成了 `HSR-1`～`HSR-40`）。

> 需求期望开发构建产物附带"参考文档与原型"（`drction` §7.5、§14.12），但 `packager._DEV_EXTRA_DIRS` 仍指向根级 `B1.0`、`B_CHelper`，而这两个目录早已移入 `legacy/` —— 于是 `_copy_dev_extras` 静默跳过，目前开发构建实际只附带 `SoftwareIntro/`。详见 `03 §17.2` 第 8 条。

本文档自身的三个部分范围划分见 `README.md §1`。

---

## 6. 版本号体系与发布形态

项目里同时存在 **4 种版本号**，混用会导致构建产物版本显示错乱：

| 版本号 | 载体 | 例 | 谁在用 |
|---|---|---|---|
| **包版本**（3 段） | `hwklr/__init__.py: __version__` | `2.3.1` | 设置页"软件版本"、关于页、构建 `get_state.version`、`_default_export_version()` 的前三段 |
| **模块版本**（3 段） | 每个模块的 `__version__` | `hsr 2.1.0` / `cprog 2.3.1` / `build 2.1.3` | 设置页"Feature 开发标记"表格的"版本"列（`feature_version()`）、构建页"构建工具版本"（`tool.builder` = `build` 模块版本） |
| **导出显示版本**（3 或 4 段） | 构建时写入 `_build_info.EXPORT_VERSION` + `BUILD_INFO.json` | `2.3.1.7559` | 产物界面显示、Windows 文件版本资源 |
| **内部实现版本** | `packager.__version__` 等 | `2.1.3` | 仅 debug 用 |

**导出显示版本的默认值算法**（`features/build/__init__.py: _default_export_version`）：

```
取包版本前三段 → 拼上 int(YYMMDDHHMMSS) % 9973 → x.y.z.w
例：包版本 2.1.3，构建时刻 26-11-01 12:59:59 → 2.1.3.7559
```

**版本注入链**（打包时）：

```
packager._write_build_info()  →  <stage>/hwklr/_build_info.py
        ↓  （源码运行时该文件不存在，走 try/ImportError 分支）
hwklr/__init__.py  →  __version__ = EXPORT_VERSION
                  →  APP_NAME / APP_TITLE 由 EXPORT_NAME 覆盖
                  →  DEV_BUILD / APP_ICON 由 DEV_BUILD / ICON_PATH 决定
        ↓
WindowView._build_meta() → 前端"关于"页与标题栏
```

发布形态有三种，产物的目录名一律为 `{exe_name}-v{version}[-dev]`：

| 形态 | 触发条件 | 产物 | 运行时 | 控制台 |
|---|---|---|---|---|
| 发布构建 | `dev_build=false` | `build/<slug>/`（PyInstaller onedir） | 内嵌 Python | 无（`--windowed`） |
| 开发构建 · executable | `dev_build=true` 且 `dev_format=executable` | `build/<slug>/` + `SoftwareIntro/` + `source-v<ver>.zip` | 内嵌 Python | 有（`--console`） |
| 开发构建 · zip | `dev_build=true` 且 `dev_format=zip` | `build/<slug>.zip` | 包内 `runtime/python.exe`（python-embed） | 由 `start.bat` 决定 |

---

## 7. 阅读路线

| 你的身份/任务 | 建议路径 |
|---|---|
| 第一次接手，想知道全貌 | 本文件 §1–§4 → `02` §1–§3（协议与 Python API 骨架）→ `03` §1–§5（线程与启动） |
| **要确认"这个行为是不是需求/能不能改"** | 本文件 §5.1 查编号 → `grep -n 'HSR-16' SoftwareIntro/drction+rqrmnts\(org\).md` |
| **要验收/交付某个版本** | `SoftwareIntro/drction+rqrmnts(org).md` §10（V1）、§14.7（V2）、§14.10–§14.18（逐版工单验收） |
| 要加一个新功能标签页 | `README` §2.2 → `02` §7.A（配方，逐条照做）→ `03` §8（注册与裁剪原理） |
| 要改某个功能的行为 | `02` §6 动作总表定位动作 → `02` §3.8–§3.10 该功能 API → `03` §10–§13 对应子系统 |
| 要加设置项 | `02` §3.5 + §7.C |
| 要动打包 | `02` §3.10 + §7.H → `03` §13–§14 |
| 要排查"界面卡住/状态不对" | `03` §1（线程）、§4（前端状态机）、§6（设置门禁） |
| 只想快速定位一行代码 | `README` §2.2 任务表 + `grep -n` 章节号 |

---

**下一步**：继续读 [`02-api-reference.md`](02-api-reference.md)（要写代码时）或 [`03-technical-deep-dive.md`](03-technical-deep-dive.md)（要理解实现时）。
