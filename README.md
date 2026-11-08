<div align="center">

# HomeworkKiller4BJTU · 北交作业助手

面向北京交通大学学生的桌面学习辅助工具：把高铁答题、C 语言程序设计练习与插件扩展整合到一个本地桌面应用中。

![Python](https://img.shields.io/badge/Python-3.15.2-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4?logo=windows&logoColor=white)
![Version](https://img.shields.io/badge/Version-4.1.0-5B4BFF)
![GUI](https://img.shields.io/badge/GUI-pywebview%20%2B%20WebView2-2F3AB2)

[功能特性](#-功能特性) · [界面预览](#-界面预览) · [快速开始](#-快速开始) · [使用指南](#-使用指南) · [构建与分发](#-构建与分发) · [插件开发](#-插件开发) · [常见问题](#-常见问题)

</div>

> [!WARNING]
> 本工具仅供个人账号学习辅助使用。请遵守学校考试纪律、课程 AI 使用规定与相关规章制度。题解模式会直接生成并提交完整代码，请仅在十分需要真实实例的情况下酌情使用，否则请使用启发模式自行完成。使用本工具产生的后果由使用者自行承担。

---

## 📖 项目简介

HomeworkKiller4BJTU（简称 HWKLR）是一个基于 **pywebview + 本地 HTTP 服务** 的 Windows 桌面应用。Python 负责业务逻辑与平台交互，HTML/CSS/JS 负责界面呈现，两者通过统一的 `Feature.handle(action, params)` 协议通信。

项目当前包含四个官方功能：

- **高铁纵横**：登录高铁答题系统，按内置题库自动匹配答案并提交考试。
- **C程序设计**：登录 CITEL 课程平台，获取课程与题目；提供“启发模式”逐步讲解，以及可选的“题解模式”生成并提交参考实现。
- **中国大学慕课**：登录中国大学 MOOC（icourse163.org），选择课程后批量完成视频、文档、测验与讨论任务；支持题库答案匹配、并发刷课与任务进度展示。
- **构建**：把程序导出为发布包/开发包，并支持第三方插件工程的创建、测试与打包。

从 **3.0.0** 开始，应用支持运行期加载第三方扩展，并在“关于”页展示插件元信息。

---

## ✨ 功能特性

### 通用体验

- **加载遮罩可取消**：所有全局加载遮罩（标签打开、登录、读取题目等）都在文字下方提供半透明白色“取消”按钮，点击后立即中止加载并提示加载超时；遮罩与标签内弹窗统一使用 0.19 秒淡入淡出。
- **固定标签位置**：构建标签始终为倒数第三（构建、设置、关于），构建设置板块始终放在最后。
- **多标签桌面 UI**：标签顺序固定为“功能标签 → 设置 → 关于”，支持窗口尺寸自适应。
- **统一设置中心**：账号、密码、AI 配置、构建配置、扩展管理全部集中在“设置”标签页，不再在每个功能页重复登录。
- **自动保存**：设置字段失焦或开关变化时自动保存；高风险设置（API Key、题解模式、并发数等）会先弹出二次确认。
- **必要设置门禁**：功能缺少必要设置时显示灰白色遮罩，并提供“去设置”快捷跳转与板块高亮。
- **功能启用开关**：每个功能设置板块右上角可启用/停用该功能，状态持久化到 `config.json`。

### 高铁纵横

- 自动完成验证码滑块识别、登录、考试列表、开考与交卷。
- 内置题库（`hwklr/runtime_data/hsr_bank_v1.0.json`）支持精确/模糊匹配与答案选项解析；首次使用时由 db 模块缓存到程序同级的 `db/hsr1.json`。
- 子窗口展示答题结果，避免撑长页面。

### C程序设计

- **启发模式**：按题目逐步返回题干解读，缓存到内存，重复查看不重复调用 AI；最后一步“大功告成”才显示提交代码。
- **题解模式**：需在设置中显式启用；逐题生成思路、生成带注释题解、提交并轮询判题结果。
- **并发解题**：最大并发数 1–8，可把已选题目平均分配给多个线程。
- **失败重试**：WA/TLE/MLE/RE 时自动提高思考等级与输出上限；PE/CE 只重写代码；最多 5 次尝试。
- **隐藏测试点识别**：Secure test 不公开输入/期望/实际输出时，只告知 AI“隐藏测试点”，避免误判。
- **状态可视化**：未提交、等待队列、生成题解、提交中、AC、错误等状态有独立配色。
- **终止解题**：题解任务运行中，原“开始学习”按钮变为红色描边、白底的“终止解题”，点击后在当前题目/AI 步骤结束时协作终止任务。

### 中国大学慕课

- **自动登录**：打开标签页后自动依次尝试“已保存 Cookie → 本机浏览器 Cookie → 设置中的账号密码（后台无头）”；全部失败时在标签内询问是否打开浏览器窗口登录，拒绝或再次失败后仅在右上角保留“重新登陆”。验证码/短信验证使用窗口登录。
- **固定视口布局**：页面不产生整页滚动，课程列表、任务表、日志各自内部滚动；窗口高度/宽度变化时自动压缩间距与侧栏。
- **课程与任务**：获取 MOOC/SPOC 课程与章节树，按视频、文档、测验、作业、考试、讨论分类展示；未完成任务默认勾选。
- **批量完成**：点击“开始完成”并确认警告后，后台执行视频并发播放、文档翻页/下载、测验题库匹配与填答、讨论复制回复；最大并行数、自动提交测验、自动发布讨论可在设置中调整（后两者默认关闭）。
- **进度展示**：运行中的任务胶囊变为浅绿色进度条并显示百分比（最多每 3 秒刷新），等待任务显示橙色“等待队列”，完成后自动刷新课程状态。
- **任务状态**：测验自动提交后显示分数（满分绿色、非满分红色），未自动提交显示黄色“已填写”并在标签内提示截图路径；讨论自动发布显示绿色“已发布”，否则同样为“已填写”。任务默认不勾选。
- **题库**：内置 `hwklr/db/icourse_sources.json` 课程目录（422 门），从 GinsMooc 下载的课程/测验/题目缓存到程序同级的 `db/icourse<termId>.json`；默认 TTL 24 小时。

### 构建与插件

- 源码环境支持“构建程序 / 构建插件”切换；开发构建产物只保留插件构建。
- 支持程序名称、图标、四段导出默认版本号（`x.y.z + 时间戳 % 9973`）。
- 发布构建使用 PyInstaller `--onedir --windowed --optimize 2` 并裁剪开发功能；开发构建保留源码归档与开发资料。
- 所有产物根目录附带 `README.md` 与 `LICENSE`；开发构建的源码归档同样包含这两个文件与 `Reference/`。
- 开发产物可一键搭建 `HwklrVenv`，按新布局解压源码、安装依赖并生成启动/调试脚本。
- 插件工程支持从模板新建、选择已有工程、临时测试、构建发布 zip。

### 关于页

- 展示软件版本、作者、功能列表、使用声明。
- 展示所有插件/功能的元信息：插件名、包名、作者、版本、更新日期、启用状态。
- 版本显示规则：软件 `vA.B.PatchC-bD`，插件 `前缀A.BpC-bD`；官方包名追加 `(Offical)`。

---

## 🖼️ 界面预览

<p align="center">
  <img src="docs/assets/screenshot-cprog.jpg" alt="C程序设计界面" width="900">
</p>

<p align="center"><sub>C程序设计：课程选择、题目列表、启发/题解模式与题目状态</sub></p>

---

## 🧱 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 桌面壳 | [pywebview](https://pywebview.flowrl.com/) 6.2.1 | Windows 下使用 WebView2 渲染前端 |
| 前端 | HTML / CSS / JavaScript | 无构建步骤，按标签动态加载资源 |
| 本地服务 | Python `http.server` | 提供静态资源与 `/api/tags`、`/api/meta` |
| 平台请求 | `requests` + `beautifulsoup4` | 登录、页面解析、提交与判题轮询 |
| AI | `openai` 兼容客户端 | 支持 DeepSeek / OpenAI / SiliconFlow / 本地兼容服务 |
| 图像 | Pillow | 验证码滑块匹配、程序图标转换 |
| 打包 | PyInstaller 6.22.3 | 目录版可执行文件；开发 zip 使用 python-embed |
| 运行时 | CPython 3.15.2（Windows 64 位） | 项目虚拟环境位于仓库根目录 |

---

## 🚀 快速开始

### 环境要求

- Windows 10 / 11（64 位）
- WebView2 Runtime（Windows 11 通常自带；Windows 10 如缺失请安装）
- Python 3.15.2（推荐与开发环境一致）
- 可访问外网（高铁、CITEL、AI 服务或插件 Git 仓库）

### 1. 获取代码

```powershell
git clone <your-repository-url> HomeworkKiller4BJTU
cd HomeworkKiller4BJTU
```

### 2. 创建虚拟环境并安装依赖

项目约定使用仓库根目录下的虚拟环境（`Scripts\python.exe`）。

```powershell
# 在仓库根目录创建虚拟环境（若无 py 启动器，可改用 python -m venv .）
py -3.15 -m venv .

# 使用清华源安装依赖
.\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 如果已经存在可用的 `Scripts\python.exe`，跳过创建步骤，直接安装依赖即可。
>
> 中国大学慕课功能使用 Playwright 驱动**系统 Microsoft Edge**，不会下载 Chromium；请确保本机已安装 Edge。窗口登录会在 `auth/edge-profile/` 创建独立浏览器配置目录。

### 3. 启动

```powershell
# 推荐：直接使用项目虚拟环境解释器
.\Scripts\python.exe main.py

# 如果本地保留有 run.bat 启动脚本，也可以：
.\run.bat
```

首次启动会在仓库根目录自动生成 `config.json`。打包后的程序则在可执行文件同级目录生成配置。

---

## ⚙️ 配置说明

所有设置都可以在应用内“设置”标签页完成；`config.json` 只是本机持久化文件。

| 配置分组 | 关键字段 | 说明 |
|---|---|---|
| `username` | `username` | 高铁纵横与 C 程序设计共用的学号/账号 |
| `hsr` | `password` / `enabled` | 高铁密码与功能启用状态 |
| `c_programming` | `provider` / `model` / `base_url` / `api_key` / `thinking_level` / `max_concurrency` / `enable_solution_mode` / `enabled` | AI 服务与 C 程序设计行为 |
| `build` | `output_dir` / `dev_format` / `plugin_template` / `plugin_project` / `features` / `enabled` | 构建目录、开发格式、插件模板/工程与开发标记 |
| `third-party` | 标签名列表 | 已启用的第三方扩展 |
| `ui` | `width` / `height` / `min_width` / `min_height` / `debug` | 窗口尺寸与调试模式 |
| `network` | `timeout_seconds` | 高铁请求超时 |
| `server` | `preferred_port` | 本地 UI 服务起始端口（默认 49152） |

> **安全提示**：`config.json` 中的密码与 API Key 为明文，且被 `.gitignore` 忽略。请勿提交、截图或分享该文件。

---

## 🧭 使用指南

### 高铁纵横

1. 在“设置 → 通用”填写学号/账号。
2. 在“设置 → 高铁纵横”填写密码。
3. 回到“高铁纵横”标签，登录、选择考试并开始答题。
4. 结果在子窗口中展示；提交前请确认考试状态。

### C程序设计

1. 在“设置 → 通用”填写学号/账号。
2. 在“设置 → C程序设计”配置 AI 服务商、模型、Base URL 与 API Key。
3. 回到“C程序设计”标签，选择课程、章节与题目。
4. 选择模式：
   - **启发模式**：逐步查看题干解读，最后一步显示提交代码框。
   - **题解模式**：需先在设置中开启“启用题解模式”；运行前会再次询问是否确实需要帮助。题解模式会逐题生成并提交代码，请谨慎使用。

> 使用建议：优先使用启发模式自行完成题目；只有在十分需要真实实例时再使用题解模式。

### 构建

- **构建程序**：填写导出显示版本号、程序名称与图标，选择是否开发构建，点击“构建”。
- **构建插件**：选择或新建插件工程，先“测试插件”临时加载调试，再“构建发布包”生成可导入的扩展 zip。

发布构建会裁剪标记为 `dev` 的功能与构建标签，不附带源码与开发资料；开发构建会保留源码归档，并可在产物中搭建 `HwklrVenv` 开发环境。

---

## 🧩 插件开发

### 扩展包结构

```text
extension.zip
├── meta.json
├── feature/
│   ├── __init__.py          # 入口：__all__ 中有且仅有一个 Feature 类名
│   └── ...                  # 其他依赖文件
└── UI/
    ├── index.html
    ├── css/
    │   └── ...
    └── js/
        └── ...
```

`meta.json` 示例：

```json
{
  "author": "Gary",
  "name": "我的插件",
  "package": "MyPlugin",
  "version": "1.0.0.0",
  "update_date": "2026-11-03",
  "official": false,
  "description": "示例插件"
}
```

`feature/__init__.py` 需要提供以下元信息与唯一入口类：

```python
__version__ = "1.0.0.0"
__author__ = "Gary"
__feature_name__ = "我的插件"
__package_name__ = "MyPlugin"
__update_date__ = "2026-11-03"
__official__ = False
__all__ = ["MyPluginFeature"]
```

入口类必须继承 `hwklr.features.base.Feature`，实现：

- `settings_group`：返回 `FeatureSettingsGroup`（无配置项时返回空组）；
- `about_meta`：返回 `AboutMetadataGroup`；
- `handle(action, params)`：按动作返回 `success(...)` / `failure(...)`。

界面资源由 `TagView` 自动加载，页面脚本通过 `App.registerPage(功能名, { init, onActivate })` 注册生命周期，并可使用 `App.callOk('动作名')` 调用后端。

### 导入与调试

1. **设置 → 通用 → 加载扩展**：
   - “从本地加载”：选择扩展 zip；
   - “从 Git 仓库加载”：输入仓库地址（需要本机安装 git）。
2. 导入成功后，扩展会出现在列表中，可随时启用/停用。
3. 在“构建 → 构建插件”中：
   - “新建插件工程”：从模板创建工程；
   - “测试插件”：从工程目录临时加载，不写入配置、下次启动不自动加载；
   - “构建发布包”：自动从 `__init__.py` 读取作者/版本，生成 `meta.json` 并打包 zip。

扩展启用状态保存在 `config.json` 的 `third-party` 字段中；扩展 zip 会解压到程序同级目录的 `extension/{作者}-{插件名}-{版本}/`。

> 插件模板位于 `hwklr/features/build/vendor/plugin-template.zip`，开发构建会把它复制到虚拟环境 `vendor/`。

---

## 📦 构建与分发

### 发布构建

- 输出目录默认 `build/`，可在“设置 → 构建”中修改。
- 默认导出目录名：`{程序名}-v{版本号}`。
- 使用 PyInstaller 目录版，无控制台、启用字节码优化。
- 不包含 `config.json`、参考文档、开发资料与插件模板，尽量减小包体。

### 开发构建

- 支持 `executable` 与 `zip` 两种格式。
- `zip` 格式使用阿里云镜像下载的 64 位 python-embed 作为运行时。
- 产物根目录附带 `README.md` 与 `LICENSE`；源码归档包含 `legacy/ Reference/ hwklr/ main.py requirements.txt README.md LICENSE`，同时附开发资料。
- 首次运行开发产物时，构建页会提示搭建 `HwklrVenv`：
  - `legacy/`、`Reference/`、`main.py`、`requirements.txt`、`README.md`、`LICENSE` 解压到虚拟环境根目录；
  - `hwklr/` 解压到 `HwklrVenv/Lib/`；
  - 使用虚拟环境 pip 从清华源安装依赖；
  - 生成 `启动程序.bat`（pythonw）与 `调试程序.bat`（python）。

### 插件发布包

插件发布包是一个 zip，包含：

```text
meta.json
feature/__init__.py
UI/index.html
UI/css/...
UI/js/...
```

文件名格式：`{作者}-{插件名}-{vA.BpC-bD}.zip`。

---

## 🗂️ 项目结构

```text
HomeworkKiller4BJTU/
├── main.py                     # 唯一入口：WindowView().run()
├── run.bat                     # 本地启动脚本（可选，未纳入版本控制时需手动保留）
├── requirements.txt            # 第三方依赖
├── config.json                 # 本机配置（不提交、不打包）
├── docs/assets/                # README 截图
├── hwklr/                      # 主包
│   ├── __init__.py             # 版本、APP_*、DEV_BUILD
│   ├── config.py               # config.json 唯一读写口与程序根解析
│   ├── db/                     # 数据库机制（DbManager/DbProvider/HSRDb/IcourseDb）
│   ├── features/
│   │   ├── base.py             # Feature 抽象、success/failure
│   │   ├── manifest.py         # OFFICIAL_FEATURES 官方功能清单
│   │   ├── settings.py         # FeatureSettingsGroup / SettingsFeature
│   │   ├── about.py            # AboutFeature / AboutMetadataGroup
│   │   ├── extensions.py       # 第三方扩展扫描/导入/启停/插件工程
│   │   ├── versions.py         # 版本显示格式
│   │   ├── hsr/                # 高铁纵横
│   │   ├── cprog/              # C 程序设计
│   │   ├── icourse/            # 中国大学慕课（登录/课程/动作/题库同步）
│   │   └── build/              # 构建与插件打包
│   ├── runtime_data/           # 随包分发的知识库源文件
│   └── UI/
│       ├── __init__.py         # WindowView + BridgeApi
│       ├── server.py           # 本地 HTTP 服务
│       ├── page_data/          # 全局页面骨架与公共资源
│       └── tagview/            # 标签抽象与各标签前端资源
├── db/                         # 运行期数据库缓存（自动生成，git 忽略）
├── auth/ documents/ artifacts/ # 慕课登录态、下载课件与失败截图（自动生成，git 忽略）
├── SoftwareIntro/              # 需求与方向文档
├── Reference/                  # 详细参考文档（架构/API/技术）
└── legacy/                     # 原版实现，仅作参考
```

> `SoftwareIntro/` 与 `legacy/` 是本地需求文档/原型目录，按 `.gitignore` 默认不纳入版本控制，也不进入发布包；`config.json`、`db/`、`run.bat`、`build/`、虚拟环境目录同样是本地文件。

更完整的架构、API 与技术细节见 [`Reference/README.md`](Reference/README.md)。

---

## 🔐 数据与隐私

- 所有配置只保存在本机 `config.json`，不会上传到项目仓库或第三方服务。
- 密码与 API Key 为明文存储；请不要提交、截图或分享 `config.json`。
- 构建产物不会包含 `config.json`；首次运行导出包时需要重新配置。
- 高铁/CITEL 请求直接发往对应平台；AI 请求直接发往你配置的 AI 服务商。
- 导入第三方扩展等同于执行第三方代码，请只加载可信来源的扩展。

---

## ❓ 常见问题

<details>
<summary><b>启动后白屏或提示“桥接初始化超时”</b></summary>

- 确认已安装 Microsoft Edge WebView2 Runtime。
- 检查端口 49152 是否被占用；应用会自动向后顺延，但防火墙可能拦截本地回环请求。
- 尝试以源码方式运行 `.\Scripts\python.exe main.py` 查看控制台错误。
</details>

<details>
<summary><b>标签页被灰色遮罩覆盖，提示“你未完成必要的设置”</b></summary>

该功能缺少必要配置（如用户名、密码、API Key）。点击“去设置”跳到对应板块；设置完成并保存后遮罩会自动消失。
</details>

<details>
<summary><b>C 程序设计持续出现 AI Error</b></summary>

- 检查 API Key、Base URL 与模型名称是否正确。
- 思考型模型可能把输出预算消耗在思维链上；应用会自动翻倍重试，必要时请降低思考等级或换用非思考模型。
- 本地 OpenAI 兼容服务可留空 API Key。
</details>

<details>
<summary><b>题解模式不可选或显示锁头</b></summary>

需要在“设置 → C程序设计”中开启“启用题解模式”。该设置默认关闭，并会在开启时二次确认。
</details>

<details>
<summary><b>构建失败</b></summary>

- 确认当前环境已安装 PyInstaller（`pip install pyinstaller`）。
- 确认当前不是已打包程序（导出后的程序不能再次构建）。
- 开发 zip 构建需要联网下载 python-embed；请检查阿里云镜像访问。
- 构建日志会保留在构建页文本框中，失败时临时目录位于 `build/.work/<产物名>`。
</details>

<details>
<summary><b>开发环境搭建失败</b></summary>

- 确认本机已安装 Python，并且 `py -3` 或 `python` 可用。
- 依赖安装使用清华源，若网络受限请配置代理或手动在 `HwklrVenv` 中安装。
</details>

<details>
<summary><b>导入扩展失败</b></summary>

常见原因：缺少 `meta.json`、缺少 `feature/__init__.py` 或 `UI/index.html`、`__all__` 不是恰好一个类名、入口类不是 `Feature` 子类、插件初始化抛异常。界面会弹出简要原因。
</details>

---

## 🤝 贡献

欢迎提交 Issue 与 Pull Request。为了保持项目一致，请遵守以下约定：

1. **运行环境**：所有安装、运行、测试均使用仓库根目录的虚拟环境（`Scripts\python.exe`）；依赖安装使用清华源。
2. **代码风格**：Python 使用类型提示与 docstring；JS 使用 JSDoc；关键步骤使用 `#关键步骤：…` 注释。
3. **文件头**：新文件需注明作者、编写日期、文件名、主要用途与文件版本；修改过的文件追加“最后更新”。
4. **版本号**：新增功能提升主版本，修复影响运行的 bug 提升次版本，仅实现优化提升修订号；修改文件时同步更新该文件版本。
5. **需求对齐**：功能变更需同步 `SoftwareIntro/function_requirements.md` 与 `SoftwareIntro/drction+rqrmnts(org).md`。
6. **提交前自检**：
   ```powershell
   .\Scripts\python.exe -m compileall -q hwklr main.py
   ```
   前端改动建议同时运行 `node --check <file>.js`。

---

## 🗓️ 版本历程

| 版本 | 主要内容 |
|---|---|
| **3.0.0** | 构建升级；程序/插件构建切换；插件工程模板与发布包；第三方扩展加载/启停；关于页元信息与版本格式；功能启用开关；开发环境新布局 |
| 2.3.1 | 修复并发解题重复登录导致会话失效；修复标签切换后课程/部分丢失；题目状态配色 |
| 2.3.0 | 题解模式逐题实时状态；最大并发数（1–8）；移除子窗口字体按钮 |
| 2.2.0 | 思考等级；AI 输出预算翻倍重试；隐藏测试点处理；整数宽度约束 |
| 2.1.x | 导出构建、图标/名称、开发环境搭建、裁剪与启动优化 |
| 2.0.x | C 程序设计重制；设置分组框架；启发/题解模式；必要设置门禁 |
| 1.0.0 | 高铁纵横重制与基础多标签 UI |

---

## 🙏 致谢

- **高铁纵横**：原版逻辑来自 [PhiloK](https://github.com/) 的 `B1.0`，本项目为 Gary 的 Remaster 实现。
- **C程序设计**：参考 `B_CHelper` 原型重制。
- 感谢 [pywebview](https://pywebview.flowrl.com/)、[requests](https://requests.readthedocs.io/)、[Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/)、[Pillow](https://python-pillow.org/)、[OpenAI Python SDK](https://github.com/openai/openai-python)、[PyInstaller](https://pyinstaller.org/) 等开源项目。
- 感谢所有提交 Issue、反馈问题与帮助测试的同学。

---

## 📄 许可证

本项目以 **Apache License 2.0** 开源，完整条款见仓库根目录的 [`LICENSE`](LICENSE)。

---

<div align="center">
  <sub>仅供个人学习辅助使用 · 请遵守学校与课程的相关规定</sub>
</div>
