/*
  作者: Gary
  编写日期: 2026-11-01 12:40
  最后更新: 2026-11-03 21:20
  文件名: build.js
  主要用途: “构建”页面逻辑：程序/插件构建模式切换、插件工程新建/选择/测试/发布、开发环境遮罩与后台任务轮询。
  文件版本: 3.0.0
*/

(function () {
  'use strict';

  const PAGE_NAME = '构建';
  const VERSION_PATTERN = /^\d+\.\d+\.\d+(?:\.\d+)?$/;
  const POLL_INTERVAL = 700;
  const MAX_ICON_BYTES = 8 * 1024 * 1024;
  const PHASE_LABELS = {
    idle: '空闲',
    starting: '准备中',
    prepare: '准备中',
    stage: '整理文件',
    download: '下载运行时',
    build: '打包中',
    package: '压缩中',
    done: '已完成',
    error: '构建失败',
  };

  /** 页面运行状态。 */
  const state = {
    jobId: '',
    timer: null,
    running: false,
    notifiedJobId: '',
    toolAvailable: false,
    devFormat: 'executable',
    buildable: true,
    defaultVersion: '',
    versionValue: '',
    defaultName: '',
    nameValue: '',
    nameTouched: false,
    iconData: '',
    iconFilename: '',
    devBuild: false,
    devPackage: false,
    devEnvReady: false,
    pythonAvailable: false,
    devEnvPath: '',
    devSourcePath: '',
    settingUp: false,
    mode: 'program',
    modes: { program: true, plugin: true },
    defaultMode: 'program',
    plugin: {},
    pluginBusy: false,
    modeTouched: false,
  };

  /** 页面元素缓存。 */
  const els = {};

  /**
   * 缓存页面元素引用。
   * @returns {void}
   */
  function cacheElements() {
    els.toolBadge = document.getElementById('build-tool-badge');
    els.toolVersion = document.getElementById('build-tool-version');
    els.outputPath = document.getElementById('build-output-path');
    els.devFormat = document.getElementById('build-dev-format');
    els.devFeatures = document.getElementById('build-dev-features');
    els.version = document.getElementById('build-version');
    els.versionError = document.getElementById('build-version-error');
    els.name = document.getElementById('build-name');
    els.iconFile = document.getElementById('build-icon-file');
    els.iconChoose = document.getElementById('build-icon-choose');
    els.iconClear = document.getElementById('build-icon-clear');
    els.iconImg = document.getElementById('build-icon-img');
    els.iconFallback = document.getElementById('build-icon-fallback');
    els.iconName = document.getElementById('build-icon-name');
    els.iconPreview = document.getElementById('build-icon-preview');
    els.dev = document.getElementById('build-dev');
    els.status = document.getElementById('build-status');
    els.log = document.getElementById('build-log');
    els.start = document.getElementById('build-start');
    els.openSettings = document.getElementById('build-open-settings');
    els.page = document.getElementById('build-page');
    els.devGate = document.getElementById('build-dev-gate');
    els.devMessage = document.getElementById('build-dev-message');
    els.devSetup = document.getElementById('build-dev-setup');
    els.devError = document.getElementById('build-dev-error');
    els.devPath = document.getElementById('build-dev-path');
    els.devPlaceholder = document.getElementById('build-dev-placeholder');
    els.devPlaceholderPath = document.getElementById('build-dev-placeholder-path');
    els.modeSwitch = document.getElementById('build-mode-switch');
    els.programCard = document.getElementById('build-program-card');
    els.pluginCard = document.getElementById('build-plugin-card');
    els.pluginProjectPath = document.getElementById('plugin-project-path');
    els.pluginProjectName = document.getElementById('plugin-project-name');
    els.pluginTemplatePath = document.getElementById('plugin-template-path');
    els.pluginVenv = document.getElementById('plugin-venv-state');
    els.pluginChoose = document.getElementById('plugin-choose');
    els.pluginNew = document.getElementById('plugin-new');
    els.pluginTest = document.getElementById('plugin-test');
    els.pluginStatus = document.getElementById('plugin-status');
    els.pluginLog = document.getElementById('plugin-log');
    els.pluginBuildStart = document.getElementById('plugin-build-start');
    els.pluginOpenSettings = document.getElementById('plugin-open-settings');
    els.pluginNewModal = document.getElementById('plugin-new-modal');
    els.pluginNewName = document.getElementById('plugin-new-name');
    els.pluginNewPackage = document.getElementById('plugin-new-package');
    els.pluginNewError = document.getElementById('plugin-new-error');
    els.pluginNewCancel = document.getElementById('plugin-new-cancel');
    els.pluginNewConfirm = document.getElementById('plugin-new-confirm');
  }

  /**
   * 更新构建状态徽标。
   * @param {string} text 状态文本。
   * @param {'info'|'ok'|'warn'|'bad'} [kind] 徽标类型。
   * @returns {void}
   */
  function setStatus(text, kind) {
    if (!els.status) {
      return;
    }
    els.status.className = 'pill ' + (kind || 'info');
    els.status.textContent = text;
  }

  /**
   * 校验版本号输入并更新红框与提示。
   * @returns {boolean} 合法返回 true。
   */
  function validateVersion() {
    if (!els.version) {
      return false;
    }
    const value = String(els.version.value || '').trim();
    const valid = VERSION_PATTERN.test(value);
    els.version.classList.toggle('invalid', !valid);
    els.version.title = valid ? '' : '版本号不合法！';
    if (els.versionError) {
      els.versionError.classList.toggle('hidden', valid);
    }
    return valid;
  }

  /**
   * 设置版本号输入框的值并立即校验。
   * @param {string} value 版本号。
   * @returns {void}
   */
  function applyVersion(value) {
    if (!els.version) {
      return;
    }
    els.version.value = String(value || '');
    validateVersion();
  }

  /**
   * 渲染图标预览并更新本地状态。
   * @param {string} dataUrl 图标 Data URL；空字符串表示未选择。
   * @param {string} filename 原始文件名。
   * @returns {void}
   */
  function renderIconPreview(dataUrl, filename) {
    state.iconData = String(dataUrl || '');
    state.iconFilename = String(filename || '');
    if (!dataUrl) {
      if (els.iconImg) {
        els.iconImg.onload = null;
        els.iconImg.onerror = null;
        els.iconImg.removeAttribute('src');
        els.iconImg.classList.add('hidden');
      }
      if (els.iconFallback) {
        els.iconFallback.classList.remove('hidden');
      }
      if (els.iconPreview) {
        els.iconPreview.classList.remove('has-icon');
      }
      if (els.iconName) {
        els.iconName.textContent = '支持 .ico / png / jpg';
      }
      if (els.iconClear) {
        els.iconClear.classList.add('hidden');
      }
      if (els.iconFile) {
        els.iconFile.value = '';
      }
      return;
    }
    if (els.iconImg) {
      els.iconImg.onload = () => {
        els.iconImg.classList.remove('hidden');
        if (els.iconFallback) {
          els.iconFallback.classList.add('hidden');
        }
        if (els.iconPreview) {
          els.iconPreview.classList.add('has-icon');
        }
      };
      els.iconImg.onerror = () => {
        els.iconImg.classList.add('hidden');
        if (els.iconFallback) {
          els.iconFallback.classList.remove('hidden');
        }
        if (els.iconPreview) {
          els.iconPreview.classList.remove('has-icon');
        }
      };
      els.iconImg.alt = filename || '程序图标';
      els.iconImg.src = dataUrl;
    }
    if (els.iconName) {
      els.iconName.textContent = filename || '已选择图标';
      els.iconName.title = filename || '';
    }
    if (els.iconClear) {
      els.iconClear.classList.remove('hidden');
    }
  }

  /**
   * 读取用户选择的图标文件。
   * @returns {void}
   */
  function handleIconFile() {
    const file =
      els.iconFile && els.iconFile.files ? els.iconFile.files[0] : null;
    if (!file) {
      return;
    }
    if (file.size > MAX_ICON_BYTES) {
      App.toast('图标文件过大（最大 8 MB）', 'error');
      renderIconPreview('', '');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      renderIconPreview(String(reader.result || ''), file.name);
    };
    reader.onerror = () => {
      App.toast('读取图标文件失败', 'error');
      renderIconPreview('', '');
    };
    reader.readAsDataURL(file);
  }

  /**
   * 显示开发环境已就绪的占位页面。
   * @param {string} path HwklrVenv 路径。
   * @returns {void}
   */
  function showDevPlaceholder(path) {
    // #V3：开发环境就绪后直接展示插件构建面板，不再显示“尽情期待”占位页。
    if (els.page) {
      els.page.classList.remove('dev-ready');
    }
    if (els.devGate) {
      els.devGate.classList.add('hidden');
    }
    if (els.devPlaceholder) {
      els.devPlaceholder.classList.add('hidden');
    }
    if (els.pluginVenv) {
      els.pluginVenv.textContent = path ? '已就绪' : '已就绪';
      els.pluginVenv.title = path || state.devEnvPath || '';
    }
    state.mode = 'plugin';
    applyMode();
    setBackgroundInert(false);
  }

  /**
   * 遮罩显示时让被遮挡的页面内容不可聚焦/交互。
   * @param {boolean} active 是否禁用背景交互。
   * @returns {void}
   */
  function setBackgroundInert(active) {
    if (!els.page) {
      return;
    }
    els.page.querySelectorAll('.hero, #build-program-card, #build-plugin-card').forEach((element) => {
      if (active) {
        element.setAttribute('inert', '');
      } else {
        element.removeAttribute('inert');
      }
    });
  }

  /**
   * 更新插件构建状态徽标。
   * @param {string} text 状态文本。
   * @param {'info'|'ok'|'warn'|'bad'} [kind] 徽标类型。
   * @returns {void}
   */
  function setPluginStatus(text, kind) {
    if (!els.pluginStatus) {
      return;
    }
    els.pluginStatus.className = 'pill ' + (kind || 'info');
    els.pluginStatus.textContent = text;
  }

  /**
   * 根据模式显示程序或插件构建面板。
   * @returns {void}
   */
  function applyMode() {
    const modes = state.modes || { program: true, plugin: true };
    if (!modes.plugin) {
      state.mode = 'program';
    }
    if (!modes.program) {
      state.mode = 'plugin';
    }
    const mode = state.mode;
    if (els.programCard) {
      els.programCard.classList.toggle('hidden', mode !== 'program');
    }
    if (els.pluginCard) {
      els.pluginCard.classList.toggle('hidden', mode !== 'plugin');
    }
    if (els.modeSwitch) {
      const count = [modes.program, modes.plugin].filter(Boolean).length;
      els.modeSwitch.classList.toggle('hidden', count < 2);
      els.modeSwitch.querySelectorAll('button').forEach((button) => {
        const target = String(button.dataset.mode || '');
        button.classList.toggle('active', target === mode);
        button.disabled = !modes[target];
      });
    }
    updatePluginButtons();
  }

  /**
   * 根据插件工程状态刷新“测试插件/构建发布包”按钮。
   * @returns {void}
   */
  function updatePluginButtons() {
    const plugin = state.plugin || {};
    const hasProject = Boolean(plugin.project) && plugin.project_valid !== false;
    if (els.pluginTest) {
      els.pluginTest.disabled = !hasProject || state.pluginBusy;
    }
    if (els.pluginBuildStart) {
      els.pluginBuildStart.disabled =
        !hasProject || state.running || state.pluginBusy;
    }
  }

  /**
   * 渲染插件工程状态。
   * @param {Object} plugin 服务端插件状态。
   * @returns {void}
   */
  function renderPlugin(plugin) {
    state.plugin = plugin && typeof plugin === 'object' ? plugin : {};
    const data = state.plugin;
    if (els.pluginProjectPath) {
      els.pluginProjectPath.textContent = data.project || '未选择';
      els.pluginProjectPath.title = data.project || '';
    }
    if (els.pluginProjectName) {
      els.pluginProjectName.textContent = data.project_name || '—';
    }
    if (els.pluginTemplatePath) {
      els.pluginTemplatePath.textContent = data.template_available
        ? data.template
        : '模板不可用';
      els.pluginTemplatePath.title = data.template || '';
    }
    if (els.pluginVenv) {
      els.pluginVenv.textContent = data.venv_ready ? '已就绪' : '未搭建';
    }
    if (els.pluginNew) {
      els.pluginNew.disabled = !data.venv_ready;
      els.pluginNew.title = data.venv_ready
        ? '从模板新建插件工程'
        : '请先搭建开发环境';
    }
    if (els.pluginHint) {
      if (data.project_error) {
        els.pluginHint.textContent = `当前工程不可用：${data.project_error}`;
        els.pluginHint.classList.add('error-text');
      } else {
        els.pluginHint.textContent =
          '“测试插件”会从当前工程目录临时加载插件，不写入启用配置，也不会在下次启动时自动加载。';
        els.pluginHint.classList.remove('error-text');
      }
    }
    updatePluginButtons();
  }

  /**
   * 切换构建模式。
   * @param {string} mode 模式名（program/plugin）。
   * @returns {void}
   */
  function switchMode(mode) {
    if (!state.modes[mode]) {
      return;
    }
    state.mode = mode;
    applyMode();
  }

  /**
   * 弹出新建插件工程窗口。
   * @returns {void}
   */
  function openNewProjectModal() {
    if (!els.pluginNewModal) {
      return;
    }
    els.pluginNewModal.classList.remove('hidden');
    if (els.pluginNewError) {
      els.pluginNewError.classList.add('hidden');
      els.pluginNewError.textContent = '';
    }
    if (els.pluginNewName) {
      els.pluginNewName.value = '';
      els.pluginNewName.focus();
    }
    if (els.pluginNewPackage) {
      els.pluginNewPackage.value = '';
    }
  }

  /**
   * 关闭新建插件工程窗口。
   * @returns {void}
   */
  function closeNewProjectModal() {
    if (els.pluginNewModal) {
      els.pluginNewModal.classList.add('hidden');
    }
  }

  /**
   * 选择已存在的插件工程。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function choosePluginProject() {
    const data = await App.callOk('choose_plugin_project');
    if (!data || data.cancelled || !data.path) {
      return;
    }
    state.plugin = Object.assign({}, state.plugin, {
      project: data.path,
      project_valid: true,
      project_name: data.name || '',
      project_error: '',
    });
    renderPlugin(state.plugin);
    App.toast('已选择插件工程', 'success');
  }

  /**
   * 从模板新建插件工程。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function createPluginProject() {
    const name = els.pluginNewName ? String(els.pluginNewName.value || '').trim() : '';
    const packageName = els.pluginNewPackage
      ? String(els.pluginNewPackage.value || '').trim()
      : '';
    if (!name || !packageName) {
      if (els.pluginNewError) {
        els.pluginNewError.textContent = '插件名和包体名都不能为空。';
        els.pluginNewError.classList.remove('hidden');
      }
      return;
    }
    if (els.pluginNewConfirm) {
      els.pluginNewConfirm.disabled = true;
      els.pluginNewConfirm.textContent = '创建中…';
    }
    try {
      const data = await App.callOk('create_plugin_project', {
        name,
        package: packageName,
      });
      state.plugin = Object.assign({}, state.plugin, {
        project: data.path,
        project_valid: true,
        project_name: data.name || name,
        project_error: '',
      });
      renderPlugin(state.plugin);
      closeNewProjectModal();
      App.toast('插件工程已创建', 'success');
    } catch (error) {
      if (els.pluginNewError) {
        els.pluginNewError.textContent = error.message;
        els.pluginNewError.classList.remove('hidden');
      }
    } finally {
      if (els.pluginNewConfirm) {
        els.pluginNewConfirm.disabled = false;
        els.pluginNewConfirm.textContent = '创建';
      }
    }
  }

  /**
   * 从工程目录临时加载并测试插件。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function testPlugin() {
    if (state.pluginBusy) {
      return;
    }
    state.pluginBusy = true;
    updatePluginButtons();
    try {
      const data = await App.callOk('test_plugin', {
        project: state.plugin.project || '',
      });
      await App.refreshTags();
      const tab = String((data && data.tab) || '');
      if (tab) {
        await App.activate(tab);
      }
      App.toast('插件已临时加载', 'success');
    } catch (error) {
      App.toast(`测试插件失败: ${error.message}`, 'error');
    } finally {
      state.pluginBusy = false;
      updatePluginButtons();
    }
  }

  /**
   * 启动插件发布包构建。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function startPluginBuild() {
    if (state.running || state.pluginBusy) {
      return;
    }
    state.running = true;
    state.notifiedJobId = '';
    updatePluginButtons();
    if (els.pluginLog) {
      els.pluginLog.value = '';
    }
    setPluginStatus('准备构建插件…', 'info');
    try {
      const data = await App.callOk('start_plugin_build', {
        project: state.plugin.project || '',
      });
      state.jobId = String(data.job_id || '');
      schedulePoll();
    } catch (error) {
      state.running = false;
      updatePluginButtons();
      setPluginStatus('启动失败', 'bad');
      App.toast(`启动插件构建失败: ${error.message}`, 'error');
    }
  }

  /**
   * 根据服务端状态决定是否显示开发构建遮罩。
   * @param {Object} data 服务端状态。
   * @returns {void}
   */
  function renderDevGate(data) {
    state.devPackage = Boolean(data.dev_build);
    state.devEnvReady = Boolean(data.dev_env_ready);
    state.pythonAvailable = Boolean(data.python_available);
    state.devEnvPath = String(data.dev_env_path || '');
    state.devSourcePath = String(data.dev_source_path || '');

    if (!state.devPackage) {
      if (els.page) {
        els.page.classList.remove('dev-ready');
      }
      if (els.devPlaceholder) {
        els.devPlaceholder.classList.add('hidden');
      }
      if (els.devGate) {
        els.devGate.classList.add('hidden');
      }
      setBackgroundInert(false);
      return;
    }
    if (state.devEnvReady) {
      showDevPlaceholder(state.devEnvPath);
      return;
    }
    if (els.page) {
      els.page.classList.remove('dev-ready');
    }
    setBackgroundInert(true);
    if (els.devPlaceholder) {
      els.devPlaceholder.classList.add('hidden');
    }
    if (els.devGate) {
      els.devGate.classList.remove('hidden');
    }
    if (els.devMessage) {
      els.devMessage.textContent = state.pythonAvailable
        ? '在当前位置搭建开发环境？'
        : '无法在此构建开发环境，请安装python后继续';
    }
    if (els.devSetup) {
      els.devSetup.classList.toggle('hidden', !state.pythonAvailable);
      els.devSetup.disabled = false;
      els.devSetup.textContent = '好的，在这里为我搭建开发环境';
    }
    if (els.devError) {
      els.devError.classList.add('hidden');
      els.devError.textContent = '';
    }
    if (els.devPath) {
      els.devPath.textContent = state.devEnvPath
        ? `目标目录：${state.devEnvPath}`
        : '';
    }
  }

  /**
   * 请求后端创建 HwklrVenv 开发环境。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function setupDevEnv() {
    if (state.settingUp || !state.pythonAvailable) {
      return;
    }
    state.settingUp = true;
    if (els.devSetup) {
      els.devSetup.disabled = true;
      els.devSetup.textContent = '正在搭建…';
    }
    if (els.devError) {
      els.devError.classList.add('hidden');
      els.devError.textContent = '';
    }
    try {
      const result = await App.callOk('setup_dev_venv');
      state.devEnvReady = true;
      state.devSourcePath = String(
        (result && result.source) || state.devSourcePath
      );
      showDevPlaceholder(String((result && result.path) || state.devEnvPath));
      await loadState();
      App.toast('开发环境已就绪', 'success');
    } catch (error) {
      if (els.devError) {
        els.devError.textContent = error.message;
        els.devError.classList.remove('hidden');
      }
      App.toast(`搭建开发环境失败: ${error.message}`, 'error');
    } finally {
      state.settingUp = false;
      if (els.devSetup) {
        els.devSetup.disabled = false;
        els.devSetup.textContent = '好的，在这里为我搭建开发环境';
      }
    }
  }

  /**
   * 渲染静态构建状态。
   * @param {Object} data 服务端状态。
   * @returns {void}
   */
  function renderState(data) {
    const tool = data.tool || {};
    state.toolAvailable = Boolean(tool.available);
    state.devFormat = String(data.dev_format || 'executable');
    state.buildable = data.buildable !== false;
    state.modes = Object.assign(
      { program: true, plugin: true },
      data.modes || {}
    );
    state.defaultMode = String(data.default_mode || 'program');
    if (!state.modeTouched) {
      state.mode = state.defaultMode;
    }
    renderPlugin(data.plugin || {});

    const builder = tool.builder ? `构建工具 ${tool.builder}` : '构建工具';
    if (els.toolBadge) {
      els.toolBadge.textContent = state.toolAvailable
        ? `${builder} · PyInstaller ${tool.pyinstaller}`
        : state.buildable
          ? `${builder} · PyInstaller 未安装`
          : `${builder} · 导出包内不可构建`;
    }
    if (els.toolVersion) {
      els.toolVersion.textContent = state.toolAvailable
        ? `${builder} · PyInstaller ${tool.pyinstaller} · Python ${tool.python || '—'}`
        : `${builder} · PyInstaller 未安装 · Python ${tool.python || '—'}`;
    }
    if (els.outputPath) {
      els.outputPath.textContent = String(data.output_path || '—');
      els.outputPath.title = String(data.output_path || '');
    }
    if (els.devFormat) {
      els.devFormat.textContent =
        state.devFormat === 'zip' ? 'zip（python-embed）' : 'executable（可执行文件）';
    }
    if (els.devFeatures) {
      const names = (Array.isArray(data.features) ? data.features : [])
        .filter((item) => item && item.dev)
        .map((item) => item.name);
      els.devFeatures.textContent = names.length ? names.join('、') : '无';
    }

    // 仅在用户尚未填写自定义值时才使用服务端默认值。
    state.defaultVersion = String(
      data.default_version || data.version || ''
    );
    if (!state.versionValue) {
      // 首次进入时锁定服务端自动填充的版本号，切换标签后保持不变。
      state.versionValue = state.defaultVersion;
      applyVersion(state.defaultVersion);
    } else {
      applyVersion(state.versionValue);
    }
    state.defaultName = String(data.default_name || 'HomeworkKiller4BJTU');
    if (els.name) {
      if (!state.nameTouched) {
        els.name.value = state.defaultName;
        state.nameValue = state.defaultName;
      } else {
        els.name.value = state.nameValue;
      }
    }

    if (!state.buildable) {
      setStatus('当前环境不可构建', 'warn');
      if (els.start) {
        els.start.disabled = true;
      }
    } else if (!state.running) {
      if (els.start) {
        els.start.disabled = false;
      }
    }
    renderDevGate(data);
    applyMode();
  }

  /**
   * 渲染构建任务状态与日志。
   * @param {Object} job 任务状态。
   * @returns {void}
   */
  function renderJob(job) {
    if (!job || typeof job !== 'object') {
      return;
    }
    state.jobId = String(job.job_id || state.jobId);
    const lines = Array.isArray(job.log) ? job.log : [];
    if (els.log) {
      const text = lines.join('\n');
      if (els.log.value !== text) {
        // 只有原本就在底部时才自动跟随最新日志，避免打断用户回看。
        const atBottom =
          els.log.scrollTop + els.log.clientHeight >= els.log.scrollHeight - 12;
        els.log.value = text;
        if (atBottom) {
          els.log.scrollTop = els.log.scrollHeight;
        }
      }
    }

    if (els.pluginLog) {
      const text = lines.join('\n');
      if (els.pluginLog.value !== text) {
        const atBottom =
          els.pluginLog.scrollTop + els.pluginLog.clientHeight >=
          els.pluginLog.scrollHeight - 12;
        els.pluginLog.value = text;
        if (atBottom) {
          els.pluginLog.scrollTop = els.pluginLog.scrollHeight;
        }
      }
    }

    state.running = Boolean(job.running);
    const phase = String(job.phase || 'idle');
    const kind =
      phase === 'error' ? 'bad' : phase === 'done' ? 'ok' : 'info';
    setStatus(PHASE_LABELS[phase] || '构建中', kind);
    setPluginStatus(PHASE_LABELS[phase] || '构建中', kind);
    if (els.start) {
      els.start.disabled = state.running || !state.buildable;
    }
    updatePluginButtons();

    if (job.done && job.job_id && state.notifiedJobId !== job.job_id) {
      state.notifiedJobId = String(job.job_id);
      if (job.error) {
        App.toast(`构建失败：${job.error}`, 'error');
      } else {
        const result = job.result || {};
        App.toast(`构建完成：${result.path || '已生成产物'}`, 'success');
      }
    }
  }

  /**
   * 读取构建页状态。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function loadState() {
    const data = await App.callOk('get_state');
    renderState(data);
    if (data.job) {
      renderJob(data.job);
      if (data.job.running) {
        schedulePoll();
      } else if (data.job.done) {
        setStatus(
          data.job.phase === 'error' ? '构建失败' : '已完成',
          data.job.phase === 'error' ? 'bad' : 'ok'
        );
      }
    }
  }

  /**
   * 安排下一次构建状态轮询。
   * @returns {void}
   */
  function schedulePoll() {
    if (state.timer) {
      window.clearTimeout(state.timer);
    }
    state.timer = window.setTimeout(pollJob, POLL_INTERVAL);
  }

  /**
   * 轮询构建任务并刷新日志。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function pollJob() {
    state.timer = null;
    if (!state.jobId) {
      return;
    }
    // 离开构建标签后停止轮询，返回时由 onActivate 重新读取一次任务状态。
    if (App.active !== PAGE_NAME) {
      return;
    }
    try {
      const job = await App.callOk('get_job', { job_id: state.jobId });
      renderJob(job);
      if (job.running) {
        schedulePoll();
      }
    } catch (error) {
      setStatus('读取进度失败', 'bad');
      App.toast(`读取构建进度失败: ${error.message}`, 'error');
    }
  }

  /**
   * 启动一次构建。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function startBuild() {
    if (state.running || !state.buildable) {
      return;
    }
    if (!validateVersion()) {
      App.toast(
        '版本号不合法！请填写 x.x.x 或 x.x.x.x 形式（例如 2.1.3.7559）',
        'error'
      );
      if (els.version) {
        els.version.focus();
      }
      return;
    }
    const devBuild = Boolean(els.dev ? els.dev.checked : state.devBuild);
    const needsPyInstaller = !devBuild || state.devFormat !== 'zip';
    if (needsPyInstaller && !state.toolAvailable) {
      App.toast('未安装 PyInstaller，无法进行该格式的构建', 'error');
      return;
    }
    state.versionValue = String(els.version.value || '').trim();
    state.nameValue = els.name ? String(els.name.value || '').trim() : '';
    state.running = true;
    state.notifiedJobId = '';
    if (els.start) {
      els.start.disabled = true;
    }
    if (els.log) {
      els.log.value = '';
    }
    setStatus('准备构建…', 'info');
    try {
      const data = await App.callOk('start_build', {
        version: state.versionValue,
        dev_build: devBuild,
        program_name: state.nameValue,
        icon_data: state.iconData,
        icon_filename: state.iconFilename,
      });
      state.jobId = String(data.job_id || '');
      schedulePoll();
    } catch (error) {
      state.running = false;
      if (els.start) {
        els.start.disabled = false;
      }
      setStatus('启动失败', 'bad');
      App.toast(`启动构建失败: ${error.message}`, 'error');
    }
  }

  /**
   * 页面初始化：缓存元素并绑定事件。
   * @param {HTMLElement} container 内容容器。
   * @returns {void}
   */
  function init(container) {
    cacheElements();
    if (state.timer) {
      window.clearTimeout(state.timer);
      state.timer = null;
    }
    if (els.version) {
      els.version.value = state.versionValue || '';
      els.version.addEventListener('input', () => {
        state.versionValue = String(els.version.value || '');
        validateVersion();
      });
      validateVersion();
    }
    if (els.name) {
      els.name.value = state.nameValue || '';
      els.name.addEventListener('input', () => {
        state.nameValue = String(els.name.value || '');
        state.nameTouched = true;
      });
    }
    if (els.iconChoose) {
      els.iconChoose.addEventListener('click', () => {
        if (els.iconFile) {
          els.iconFile.click();
        }
      });
    }
    if (els.iconFile) {
      els.iconFile.addEventListener('change', handleIconFile);
    }
    if (els.iconClear) {
      els.iconClear.addEventListener('click', () => renderIconPreview('', ''));
    }
    renderIconPreview(state.iconData, state.iconFilename);
    if (els.dev) {
      els.dev.checked = state.devBuild;
      els.dev.addEventListener('change', () => {
        state.devBuild = Boolean(els.dev.checked);
      });
    }
    if (els.devSetup) {
      els.devSetup.addEventListener('click', () => {
        setupDevEnv().catch((error) =>
          App.toast(`搭建开发环境失败: ${error.message}`, 'error')
        );
      });
    }
    if (els.page) {
      els.page.classList.remove('dev-ready');
    }
    if (els.devGate) {
      els.devGate.classList.add('hidden');
    }
    if (els.devPlaceholder) {
      els.devPlaceholder.classList.add('hidden');
    }
    setBackgroundInert(false);
    if (els.start) {
      els.start.disabled = true;
      els.start.addEventListener('click', () => {
        startBuild().catch((error) =>
          App.toast(`构建操作失败: ${error.message}`, 'error')
        );
      });
    }
    if (els.openSettings) {
      els.openSettings.addEventListener('click', () => App.openSettings('build'));
    }
    if (els.modeSwitch) {
      els.modeSwitch.querySelectorAll('button').forEach((button) => {
        button.addEventListener('click', () => {
          state.modeTouched = true;
          switchMode(String(button.dataset.mode || ''));
        });
      });
    }
    if (els.pluginChoose) {
      els.pluginChoose.addEventListener('click', () => {
        choosePluginProject().catch((error) =>
          App.toast(`选择插件工程失败: ${error.message}`, 'error')
        );
      });
    }
    if (els.pluginNew) {
      els.pluginNew.addEventListener('click', openNewProjectModal);
    }
    if (els.pluginNewCancel) {
      els.pluginNewCancel.addEventListener('click', closeNewProjectModal);
    }
    if (els.pluginNewConfirm) {
      els.pluginNewConfirm.addEventListener('click', () => {
        createPluginProject().catch((error) =>
          App.toast(`新建插件工程失败: ${error.message}`, 'error')
        );
      });
    }
    if (els.pluginNewModal) {
      els.pluginNewModal.addEventListener('click', (event) => {
        if (event.target === els.pluginNewModal) {
          closeNewProjectModal();
        }
      });
    }
    if (els.pluginTest) {
      els.pluginTest.addEventListener('click', () => {
        testPlugin().catch((error) =>
          App.toast(`测试插件失败: ${error.message}`, 'error')
        );
      });
    }
    if (els.pluginBuildStart) {
      els.pluginBuildStart.addEventListener('click', () => {
        startPluginBuild().catch((error) =>
          App.toast(`插件构建失败: ${error.message}`, 'error')
        );
      });
    }
    if (els.pluginOpenSettings) {
      els.pluginOpenSettings.addEventListener('click', () =>
        App.openSettings('build')
      );
    }
    if (els.log) {
      els.log.value = '';
    }
    if (els.pluginLog) {
      els.pluginLog.value = '';
    }
    setStatus('读取状态…', 'info');
    setPluginStatus('读取状态…', 'info');
    applyMode();
  }

  /**
   * 每次切换到本标签时刷新构建状态，并恢复正在运行的轮询。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function onActivate() {
    try {
      await loadState();
    } catch (error) {
      setStatus('读取状态失败', 'bad');
      App.toast(`读取构建状态失败: ${error.message}`, 'error');
    }
  }

  /**
   * 离开本标签时停止轮询；后台构建线程仍会继续。
   * @returns {void}
   */
  function onDeactivate() {
    if (state.timer) {
      window.clearTimeout(state.timer);
      state.timer = null;
    }
  }

  App.registerPage(PAGE_NAME, {
    init: init,
    onActivate: onActivate,
    onDeactivate: onDeactivate,
  });
})();
