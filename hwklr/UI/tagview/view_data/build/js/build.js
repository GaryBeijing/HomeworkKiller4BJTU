/*
  作者: Gary
  编写日期: 2026-11-01 12:40
  文件名: build.js
  主要用途: “构建”页面逻辑：读取构建状态、版本号校验、启动后台构建并轮询日志。
  文件版本: 2.1.0
*/

(function () {
  'use strict';

  const PAGE_NAME = '构建';
  const VERSION_PATTERN = /^\d+\.\d+\.\d+$/;
  const POLL_INTERVAL = 700;
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
    devBuild: false,
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
    els.dev = document.getElementById('build-dev');
    els.status = document.getElementById('build-status');
    els.log = document.getElementById('build-log');
    els.start = document.getElementById('build-start');
    els.openSettings = document.getElementById('build-open-settings');
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
   * 渲染静态构建状态。
   * @param {Object} data 服务端状态。
   * @returns {void}
   */
  function renderState(data) {
    const tool = data.tool || {};
    state.toolAvailable = Boolean(tool.available);
    state.devFormat = String(data.dev_format || 'executable');
    state.buildable = data.buildable !== false;

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

    // 仅在用户尚未填写自定义版本时使用当前程序版本作为默认值。
    state.defaultVersion = String(data.version || '');
    if (!state.versionValue) {
      applyVersion(state.defaultVersion);
    } else {
      applyVersion(state.versionValue);
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

    state.running = Boolean(job.running);
    const phase = String(job.phase || 'idle');
    const kind =
      phase === 'error' ? 'bad' : phase === 'done' ? 'ok' : 'info';
    setStatus(PHASE_LABELS[phase] || '构建中', kind);
    if (els.start) {
      els.start.disabled = state.running || !state.buildable;
    }

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
      App.toast('版本号不合法！请填写 x.x.x 形式（例如 2.1.0）', 'error');
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
    if (els.dev) {
      els.dev.checked = state.devBuild;
      els.dev.addEventListener('change', () => {
        state.devBuild = Boolean(els.dev.checked);
      });
    }
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
    if (els.log) {
      els.log.value = '';
    }
    setStatus('读取状态…', 'info');
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
