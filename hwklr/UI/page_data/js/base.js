/*
  作者: Gary
  编写日期: 2026-10-31 20:45
  最后更新: 2026-11-08 17:20
  文件名: base.js
  主要用途: 前端公共逻辑：标签栏、设置锁定/跳转、资源加载、桥接调用、提示与加载状态。
  文件版本: 4.0.1
*/

(function () {
  'use strict';

  /** 全局运行状态。 */
  const state = {
    tags: [],
    active: null,
    meta: {},
    pages: new Map(),
    cssPromises: new Map(),
    jsPromises: new Map(),
    bridgePromise: null,
    activationToken: 0,
    activating: '',
    settingsTarget: '',
    cancelActivation: null,
    loadingVisible: false,
    pendingCancels: new Set(),
  };

  /**
   * 按 id 获取元素。
   * @param {string} id 元素 id。
   * @returns {HTMLElement|null} 元素或 null。
   */
  function element(id) {
    return document.getElementById(id);
  }

  /**
   * 创建用于展示错误的 DOM 节点。
   * @param {string} tagName 标签名。
   * @param {string} className 类名。
   * @param {string} text 文本内容。
   * @returns {HTMLElement} 新节点。
   */
  function createNode(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) {
      node.className = className;
    }
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  /**
   * 请求并解析 JSON。
   * @param {string} url 请求地址。
   * @returns {Promise<any>} 解析后的 JSON。
   */
  async function fetchJson(url) {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`请求失败 (${response.status}): ${url}`);
    }
    return response.json();
  }

  /**
   * 等待 pywebview 桥接就绪。
   * @returns {Promise<void>} 桥接可用时 resolve。
   */
  function waitForBridge() {
    if (window.pywebview && window.pywebview.api) {
      return Promise.resolve();
    }
    if (!state.bridgePromise) {
      state.bridgePromise = new Promise((resolve, reject) => {
        const timer = window.setTimeout(() => {
          reject(new Error('桥接初始化超时，请重启应用'));
        }, 12000);
        const done = () => {
          window.clearTimeout(timer);
          resolve();
        };
        if (window.pywebview && window.pywebview.api) {
          done();
          return;
        }
        window.addEventListener('pywebviewready', done, { once: true });
      });
    }
    return state.bridgePromise;
  }

  /**
   * 动态加载 CSS，同一地址只加载一次。
   * @param {string} url 样式地址。
   * @returns {Promise<void>} 加载完成时 resolve。
   */
  function loadCss(url) {
    if (state.cssPromises.has(url)) {
      return state.cssPromises.get(url);
    }
    const promise = new Promise((resolve, reject) => {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = url;
      link.onload = () => resolve();
      link.onerror = () => reject(new Error(`加载样式失败: ${url}`));
      document.head.appendChild(link);
    });
    state.cssPromises.set(url, promise);
    promise.catch(() => state.cssPromises.delete(url));
    return promise;
  }

  /**
   * 动态加载 JS，同一地址只加载一次。
   * @param {string} url 脚本地址。
   * @returns {Promise<void>} 加载完成时 resolve。
   */
  function loadScript(url) {
    if (state.jsPromises.has(url)) {
      return state.jsPromises.get(url);
    }
    const promise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = url;
      script.async = false;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error(`加载脚本失败: ${url}`));
      document.body.appendChild(script);
    });
    state.jsPromises.set(url, promise);
    promise.catch(() => state.jsPromises.delete(url));
    return promise;
  }

  /**
   * 注册标签页脚本提供的生命周期回调。
   * @param {string} name 标签名称。
   * @param {{init?: Function, onActivate?: Function, onDeactivate?: Function}} page 回调集合。
   * @returns {void}
   */
  function registerPage(name, page) {
    state.pages.set(name, page || {});
  }

  /**
   * 显示或隐藏全局加载遮罩。
   * @param {boolean} visible 是否显示。
   * @param {string} [text] 提示文本。
   * @returns {void}
   */
  function setLoading(visible, text, options) {
    const loading = element('loading');
    const label = element('loading-text');
    const cancel = element('loading-cancel');
    if (!loading) {
      return;
    }
    if (label && text) {
      label.textContent = text;
    }
    state.loadingVisible = Boolean(visible);
    // 4.0.1：所有全局加载遮罩都提供“取消加载”。
    if (cancel) {
      cancel.classList.toggle('hidden', !visible);
      cancel.disabled = !visible;
    }
    loading.classList.toggle('hidden', !visible);
  }

  /**
   * 取消当前加载（由加载遮罩上的“取消加载”按钮触发）。
   * 会中止当前标签激活，并让正在等待的桥接调用以超时错误失败。
   * @returns {void}
   */
  function cancelLoading() {
    const handler = state.cancelActivation;
    const hadActivation = typeof handler === 'function';
    if (hadActivation) {
      try {
        handler();
      } catch (error) {
        console.error(error);
      }
    }
    const error = new Error('加载超时：已取消加载');
    let rejected = 0;
    state.pendingCancels.forEach((reject) => {
      try {
        reject(error);
        rejected += 1;
      } catch (ignored) {
        // 忽略已经结束的调用。
      }
    });
    state.pendingCancels.clear();
    setLoading(false);
    if (!hadActivation && rejected === 0) {
      toast('加载超时，已取消加载', 'warn');
    }
  }

  /**
   * 显示一条自动消失的提示。
   * @param {string} message 提示内容。
   * @param {'info'|'success'|'error'|'warn'} [type] 提示类型。
   * @returns {void}
   */
  function toast(message, type) {
    const host = element('toast-host');
    if (!host) {
      return;
    }
    const node = createNode('div', `toast ${type || 'info'}`, String(message));
    host.appendChild(node);
    window.setTimeout(() => {
      node.classList.add('leaving');
      window.setTimeout(() => node.remove(), 260);
    }, 4200);
  }

  /**
   * 渲染顶部标签栏。
   * @returns {void}
   */
  function renderTabs() {
    const tabbar = element('tabbar');
    if (!tabbar) {
      return;
    }
    tabbar.innerHTML = '';
    state.tags.forEach((tag) => {
      const button = createNode('button', 'tab', tag.title || tag.name);
      button.type = 'button';
      button.setAttribute('role', 'tab');
      button.setAttribute('data-tag', tag.name);
      button.setAttribute('aria-selected', String(tag.name === state.active));
      button.title = tag.description || '';
      if (tag.name === state.active) {
        button.classList.add('active');
      }
      button.addEventListener('click', () => {
        activate(tag.name).catch((error) => toast(error.message, 'error'));
      });
      tabbar.appendChild(button);
    });
  }

  /**
   * 在内容区展示致命错误与重试按钮。
   * @param {string|null} name 目标标签名称。
   * @param {Error} error 错误对象。
   * @returns {void}
   */
  function renderFatal(name, error) {
    const host = element('content-host');
    if (!host) {
      return;
    }
    host.innerHTML = '';
    const panel = createNode('section', 'card fatal-panel');
    panel.appendChild(createNode('h2', '', '页面加载失败'));
    panel.appendChild(createNode('p', '', error && error.message ? error.message : '未知错误'));
    const retry = createNode('button', 'btn primary', '重试');
    retry.type = 'button';
    retry.addEventListener('click', () => {
      if (name) {
        activate(name, { force: true }).catch((err) => toast(err.message, 'error'));
      } else {
        init();
      }
    });
    panel.appendChild(retry);
    host.appendChild(panel);
  }

  /**
   * 重新拉取标签元数据（含必要设置状态）。
   * @returns {Promise<Array>} 最新标签列表。
   */
  async function refreshTags() {
    const tags = await fetchJson('/api/tags');
    state.tags = Array.isArray(tags) ? tags : [];
    renderTabs();
    return state.tags;
  }

  /**
   * 打开设置标签，并可指定需要高亮的设置板块。
   * @param {string} [groupId] 设置板块 ID。
   * @returns {void}
   */
  function openSettings(groupId) {
    state.settingsTarget = groupId || '';
    if (state.active === '设置') {
      const page = state.pages.get('设置');
      if (page && typeof page.highlightGroup === 'function') {
        page.highlightGroup(groupId || '');
      }
      return;
    }
    activate('设置').catch((error) => toast(error.message, 'error'));
  }

  /**
   * 取出并清空待高亮的设置板块。
   * @returns {string} 板块 ID。
   */
  function takeSettingsTarget() {
    const target = state.settingsTarget || '';
    state.settingsTarget = '';
    return target;
  }

  /**
   * 在锁定页面上覆盖灰白色遮罩。
   * @param {Object} tag 标签元数据。
   * @returns {void}
   */
  function applyLockOverlay(tag) {
    const host = element('content-host');
    if (!host) {
      return;
    }
    const page = host.querySelector('.tag-page') || host;
    if (page.querySelector('.settings-lock-overlay')) {
      return;
    }
    const overlay = createNode('div', 'settings-lock-overlay');
    const card = createNode('div', 'settings-lock-card');
    card.appendChild(createNode('div', 'settings-lock-icon', '!'));
    card.appendChild(createNode('h3', '', '你未完成必要的设置'));
    const missing = Array.isArray(tag.missing_settings) && tag.missing_settings.length
      ? `需要在设置中完成：${tag.missing_settings.join('、')}`
      : '请前往设置完成该功能的必要配置。';
    card.appendChild(createNode('p', '', missing));
    const go = createNode('button', 'btn primary', '去设置');
    go.type = 'button';
    go.addEventListener('click', () => openSettings(tag.settings_target || tag.settings_group));
    card.appendChild(go);
    overlay.appendChild(card);
    page.appendChild(overlay);
  }

  /**
   * 弹出“需要完成设置”的子窗口；关闭后显示锁定遮罩。
   * @param {Object} tag 标签元数据。
   * @returns {void}
   */
  function showSettingsRequired(tag) {
    const backdrop = createNode('div', 'modal-backdrop settings-required-backdrop');
    const modal = createNode('div', 'modal settings-required-modal');
    const close = createNode('button', 'modal-close', '×');
    close.type = 'button';
    close.setAttribute('aria-label', '关闭');
    close.addEventListener('click', () => {
      backdrop.remove();
      applyLockOverlay(tag);
    });
    modal.appendChild(close);
    modal.appendChild(createNode('h3', '', '请先完成必要设置'));
    const missing = Array.isArray(tag.missing_settings) && tag.missing_settings.length
      ? `使用「${tag.title}」前，请先在设置中完成：${tag.missing_settings.join('、')}。`
      : `使用「${tag.title}」前，请先在设置中完成必要配置。`;
    modal.appendChild(createNode('p', '', missing));
    const go = createNode('button', 'btn primary', '去设置');
    go.type = 'button';
    go.addEventListener('click', () => {
      backdrop.remove();
      openSettings(tag.settings_target || tag.settings_group);
    });
    modal.appendChild(go);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
  }

  /**
   * 激活指定标签页。
   * @param {string} name 标签名称。
   * @param {{force?: boolean}} [options] 选项。
   * @returns {Promise<void>} 激活完成时 resolve。
   */
  async function activate(name, options) {
    const opts = options || {};
    try {
      await refreshTags();
    } catch (error) {
      console.error(error);
    }
    const tag = state.tags.find((item) => item.name === name);
    if (!tag) {
      throw new Error(`未知标签: ${name}`);
    }
    if (!opts.force && state.active === name) {
      return;
    }
    // 防止 JS 初始化与 Python loaded 事件同时激活同一标签，导致重复登录/重复渲染。
    if (!opts.force && state.activating === name) {
      return;
    }
    state.activating = name;

    const token = ++state.activationToken;
    const activation = { cancelled: false };
    const cancelHandler = () => {
      activation.cancelled = true;
      const page = state.pages.get(name) || {};
      if (typeof page.onCancelLoading === 'function') {
        try {
          page.onCancelLoading();
        } catch (error) {
          console.error(error);
        }
      }
      setLoading(false);
    };
    state.cancelActivation = cancelHandler;
    const previous = state.tags.find((item) => item.name === state.active);
    if (previous) {
      const previousPage = state.pages.get(previous.name);
      if (previousPage && typeof previousPage.onDeactivate === 'function') {
        try {
          previousPage.onDeactivate();
        } catch (error) {
          console.error(error);
        }
      }
    }

    setLoading(true, `正在打开「${tag.title || tag.name}」…`, { cancellable: true });
    const ensureActive = () => {
      if (activation.cancelled) {
        throw new Error('登录超时：已取消加载');
      }
    };
    try {
      // 步骤 1：并行加载该标签的 CSS 与 JS。
      const cssList = Array.isArray(tag.css_urls) ? tag.css_urls : [];
      const jsList = Array.isArray(tag.js_urls) ? tag.js_urls : [];
      await Promise.all([...cssList.map(loadCss), ...jsList.map(loadScript)]);
      ensureActive();

      // 步骤 2：拉取 HTML 片段（标签栏以外的定制内容）。
      const response = await fetch(tag.html_url, { cache: 'no-store' });
      if (!response.ok) {
        throw new Error(`加载页面失败 (${response.status}): ${tag.html_url}`);
      }
      const html = await response.text();
      ensureActive();
      if (token !== state.activationToken) {
        return;
      }

      // 步骤 3：写入内容区并更新标签栏。
      const host = element('content-host');
      if (!host) {
        throw new Error('缺少内容容器');
      }
      host.innerHTML = html;
      state.active = name;
      renderTabs();

      // 步骤 4：每次激活都重新绑定页面回调。
      // 因为标签切换会重新注入 HTML，旧的 DOM 引用与事件监听已失效，
      // 必须让页面重新缓存元素并绑定事件。
      const page = state.pages.get(name) || {};
      if (typeof page.init === 'function') {
        await page.init(host);
      }
      ensureActive();

      // 步骤 5：必要设置未完成时，弹出提醒并跳过页面业务初始化。
      if (tag.settings_ok === false && name !== '设置' && name !== '关于') {
        showSettingsRequired(tag);
        return;
      }

      if (typeof page.onActivate === 'function') {
        await page.onActivate();
        ensureActive();
      }
    } catch (error) {
      if (activation.cancelled) {
        toast('登录超时，已取消加载', 'warn');
        return;
      }
      if (token !== state.activationToken) {
        return;
      }
      renderFatal(name, error);
      toast(`打开「${tag.title || tag.name}」失败: ${error.message}`, 'error');
    } finally {
      if (state.activating === name) {
        state.activating = '';
      }
      if (state.cancelActivation === cancelHandler) {
        state.cancelActivation = null;
      }
      if (token === state.activationToken) {
        setLoading(false);
      }
    }
  }

  /**
   * 调用当前标签的功能动作，返回原始结果。
   * @param {string} method 动作名称。
   * @param {Object} [params] 动作参数。
   * @returns {Promise<{ok: boolean, data?: any, error?: string}>} 原始结果。
   */
  async function call(method, params) {
    if (!state.active) {
      throw new Error('尚未激活任何标签');
    }
    await waitForBridge();
    const request = window.pywebview.api.call(
      state.active,
      method,
      params || {}
    );
    let result;
    if (state.loadingVisible) {
      // 遮罩显示期间允许“取消加载”立即让本次桥接调用以超时失败。
      let rejectCancel = null;
      const cancelled = new Promise((_, reject) => {
        rejectCancel = reject;
      });
      state.pendingCancels.add(rejectCancel);
      try {
        result = await Promise.race([request, cancelled]);
      } finally {
        state.pendingCancels.delete(rejectCancel);
      }
    } else {
      result = await request;
    }
    if (!result || typeof result !== 'object') {
      throw new Error('桥接返回格式异常');
    }
    return result;
  }

  /**
   * 调用当前标签的功能动作，失败时抛出异常。
   * @param {string} method 动作名称。
   * @param {Object} [params] 动作参数。
   * @returns {Promise<any>} 成功时的 data。
   */
  async function callOk(method, params) {
    const result = await call(method, params);
    if (!result.ok) {
      throw new Error(result.error || '操作失败');
    }
    return result.data;
  }

  /**
   * 初始化应用：读取标签与元信息，激活第一个标签。
   * @returns {Promise<void>} 初始化完成时 resolve。
   */
  async function init() {
    const cancelButton = element('loading-cancel');
    if (cancelButton) {
      cancelButton.addEventListener('click', cancelLoading);
    }
    setLoading(true, '正在初始化…');
    try {
      const [tags, meta] = await Promise.all([
        fetchJson('/api/tags'),
        fetchJson('/api/meta'),
      ]);
      state.tags = Array.isArray(tags) ? tags : [];
      state.meta = meta && typeof meta === 'object' ? meta : {};
      renderTabs();
      if (state.tags.length === 0) {
        throw new Error('没有可用的功能标签');
      }
      await activate(state.tags[0].name);
    } catch (error) {
      renderFatal(null, error);
      toast(`初始化失败: ${error.message}`, 'error');
    } finally {
      setLoading(false);
    }
  }

  // 对外暴露的最小 API，供各标签脚本使用。
  window.App = {
    init: init,
    activate: activate,
    call: call,
    callOk: callOk,
    toast: toast,
    setLoading: setLoading,
    cancelLoading: cancelLoading,
    registerPage: registerPage,
    refreshTags: refreshTags,
    openSettings: openSettings,
    takeSettingsTarget: takeSettingsTarget,
    get meta() {
      return state.meta;
    },
    get active() {
      return state.active;
    },
    get tags() {
      return state.tags.slice();
    },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
