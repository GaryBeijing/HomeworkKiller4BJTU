/*
  作者: Gary
  编写日期: 2026-11-11 10:00
  最后更新: 2026-11-11 21:00
  文件名: update.js
  主要用途: 启动时检查新版本，展示 Release note，下载、准备并在用户确认后切换到版本化安装。
  文件版本: 4.5.0
*/

(function () {
  'use strict';

  const POLL_MS = 900;
  let pollTimer = null;
  let dialog = null;
  let lastStatus = '';

  /**
   * 创建元素。
   * @param {string} tagName 标签名。
   * @param {string} [className] 类名。
   * @param {string} [text] 文本。
   * @returns {HTMLElement} 节点。
   */
  function node(tagName, className, text) {
    const item = document.createElement(tagName);
    if (className) {
      item.className = className;
    }
    if (text !== undefined) {
      item.textContent = text;
    }
    return item;
  }

  /**
   * 调用 pywebview 更新桥接方法。
   * @param {string} name 方法名。
   * @param {...any} args 参数。
   * @returns {Promise<any>} 调用结果。
   */
  function callApi(name, ...args) {
    const bridge = window.pywebview && window.pywebview.api;
    if (!bridge || typeof bridge[name] !== 'function') {
      return Promise.reject(new Error('更新服务尚未就绪'));
    }
    return Promise.resolve(bridge[name](...args));
  }

  /**
   * 关闭当前更新弹窗。
   * @returns {void}
   */
  function closeDialog() {
    if (dialog) {
      dialog.remove();
      dialog = null;
    }
  }

  /**
   * 创建按钮。
   * @param {string} text 按钮文本。
   * @param {string} className 样式类。
   * @param {Function} handler 点击回调。
   * @returns {HTMLButtonElement} 按钮。
   */
  function button(text, className, handler) {
    const item = node('button', `btn ${className}`, text);
    item.type = 'button';
    item.addEventListener('click', handler);
    return item;
  }

  /**
   * 显示一个更新弹窗。
   * @param {string} title 标题。
   * @param {HTMLElement} body 正文节点。
   * @param {Array<HTMLButtonElement>} actions 按钮列表。
   * @returns {void}
   */
  function showDialog(title, body, actions) {
    closeDialog();
    const backdrop = node('div', 'modal-backdrop update-backdrop');
    const modal = node('div', 'modal update-modal');
    modal.appendChild(node('h3', '', title));
    modal.appendChild(body);
    const row = node('div', 'update-actions');
    actions.forEach((item) => row.appendChild(item));
    modal.appendChild(row);
    backdrop.appendChild(modal);
    backdrop.addEventListener('click', (event) => {
      if (event.target === backdrop) {
        closeDialog();
      }
    });
    document.body.appendChild(backdrop);
    dialog = backdrop;
  }

  /**
   * 显示“发现新版本”弹窗。
   * @param {Object} state 更新状态。
   * @returns {void}
   */
  function showAvailable(state) {
    const body = node('div', 'update-body');
    const version = String(state.latest || '');
    body.appendChild(
      node(
        'p',
        'update-version',
        `最新版本：${version}（当前 ${state.current || '未知'}）`
      )
    );
    body.appendChild(node('p', 'update-notes-label', 'Release note:'));
    const notes = node(
      'pre',
      'update-notes',
      String(state.notes || '该版本没有提供发布日志。')
    );
    body.appendChild(notes);
    showDialog('检测到新版本！准备好更新了吗？', body, [
      button('现在安装！', 'primary', () => {
        startDownload().catch(() => {});
      }),
      button('观望中...', 'danger-outline', () => {
        closeDialog();
      }),
    ]);
  }

  /**
   * 显示“更新已预备”弹窗。
   * @param {Object} state 更新状态。
   * @returns {void}
   */
  function showReady(state) {
    const body = node('div', 'update-body');
    if (state.can_install) {
      body.appendChild(
        node('p', 'update-text', '更新包已下载完成，可以立即安装并重启软件。')
      );
    } else {
      body.appendChild(
        node(
          'p',
          'update-text',
          '更新包已下载完成，但当前运行方式不支持自动安装；'
            + '请手动使用下载的更新包。'
        )
      );
      body.appendChild(
        node(
          'p',
          'update-path',
          String(state.download_path || '')
        )
      );
    }
    const actions = [];
    if (state.can_install) {
      actions.push(
        button('现在安装并重启软件', 'primary', () => {
          installUpdate(true).catch(() => {});
        })
      );
      actions.push(
        button('稍后安装', 'ghost', () => {
          installUpdate(false).catch(() => {});
        })
      );
    } else {
      actions.push(
        button('知道了', 'primary', () => {
          closeDialog();
        })
      );
    }
    showDialog('更新已预备！', body, actions);
  }

  /**
   * 开始下载更新。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function startDownload() {
    closeDialog();
    App.setLoading(true, '正在下载更新… 0%', { cancellable: false });
    try {
      const state = await callApi('start_update_download');
      if (state && state.status === 'available') {
        App.setLoading(false);
        App.toast('当前没有可下载的更新', 'warn');
        return;
      }
      applyState(state);
    } catch (error) {
      App.setLoading(false);
      App.toast(`下载更新失败: ${error.message}`, 'error');
    }
  }

  /**
   * 记录或执行安装。
   * @param {boolean} restart 是否立即重启安装。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function installUpdate(restart) {
    closeDialog();
    try {
      const result = await callApi('install_update', Boolean(restart));
      if (!result || !result.ok) {
        App.setLoading(false);
        App.toast(String((result && result.error) || '安装更新失败'), 'error');
        return;
      }
      if (!restart) {
        App.toast('将在下次启动时安装更新', 'success');
        return;
      }
      App.setLoading(true, '正在重启以完成更新…', { cancellable: false });
      // 正常情况下窗口会在 0.6 秒内关闭；超时则恢复界面。
      window.setTimeout(() => App.setLoading(false), 8000);
    } catch (error) {
      App.setLoading(false);
      App.toast(`安装更新失败: ${error.message}`, 'error');
    }
  }

  /**
   * 安排一次状态轮询。
   * @returns {void}
   */
  function schedulePoll() {
    if (pollTimer) {
      window.clearTimeout(pollTimer);
    }
    pollTimer = window.setTimeout(poll, POLL_MS);
  }

  /**
   * 读取更新状态。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function poll() {
    pollTimer = null;
    try {
      const state = await callApi('get_update_state');
      applyState(state);
    } catch (error) {
      // 桥接不可用时停止轮询，不影响主界面。
    }
  }

  /**
   * 根据状态更新界面。
   * @param {Object} state 更新状态。
   * @returns {void}
   */
  function applyState(state) {
    if (!state || typeof state !== 'object') {
      return;
    }
    const status = String(state.status || 'idle');
    if (status === 'checking' || status === 'downloading' || status === 'preparing') {
      schedulePoll();
    }
    if (status === 'downloading') {
      const progress = Number(state.progress || 0);
      App.setLoading(true, `正在下载更新… ${progress}%`, { cancellable: false });
    }
    if (status === 'preparing') {
      App.setLoading(true, '正在校验并准备更新…', { cancellable: false });
    }
    if (status === 'available' && lastStatus !== 'available') {
      showAvailable(state);
    }
    if (status === 'ready' && lastStatus !== 'ready') {
      App.setLoading(false);
      showReady(state);
    }
    if (status === 'error' && lastStatus !== 'error') {
      App.setLoading(false);
      App.toast(String(state.error || '检查更新失败'), 'error');
    }
    lastStatus = status;
  }

  /**
   * 等待桥接就绪后启动检查。
   * @returns {void}
   */
  function start() {
    if (window.pywebview && window.pywebview.api) {
      window.setTimeout(() => {
        callApi('check_update')
          .then((state) => applyState(state))
          .catch(() => {});
      }, 800);
      return;
    }
    window.addEventListener(
      'pywebviewready',
      () => {
        window.setTimeout(() => {
          callApi('check_update')
            .then((state) => applyState(state))
            .catch(() => {});
        }, 800);
      },
      { once: true }
    );
  }

  start();
})();
