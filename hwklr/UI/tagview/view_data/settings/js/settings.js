/*
  作者: Gary
  编写日期: 2026-10-31 20:45
  文件名: settings.js
  主要用途: “设置”页面逻辑：读取/保存账号密码，加载知识库与运行信息。
  文件版本: 1.0.0
*/

(function () {
  'use strict';

  const PAGE_NAME = '设置';

  /** 页面元素缓存。 */
  const els = {};

  /**
   * 缓存页面元素引用。
   * @returns {void}
   */
  function cacheElements() {
    els.form = document.getElementById('settings-form');
    els.username = document.getElementById('settings-username');
    els.password = document.getElementById('settings-password');
    els.save = document.getElementById('settings-save');
    els.togglePassword = document.getElementById('settings-toggle-password');
    els.status = document.getElementById('settings-status');
    els.version = document.getElementById('settings-version');
    els.port = document.getElementById('settings-port');
    els.bankBody = document.getElementById('settings-bank-body');
    els.refreshBanks = document.getElementById('settings-refresh-banks');
  }

  /**
   * 更新状态提示样式与文本。
   * @param {string} text 提示文本。
   * @param {'muted'|'error'|'success'} [kind] 样式类型。
   * @returns {void}
   */
  function setStatus(text, kind) {
    if (!els.status) {
      return;
    }
    const suffix = kind === 'error' ? ' error-text' : kind === 'success' ? ' success-text' : '';
    els.status.className = 'hint settings-status' + suffix;
    els.status.textContent = text;
  }

  /**
   * 读取并填充设置。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function loadSettings() {
    const data = await App.callOk('get_settings');
    if (els.username) {
      els.username.value = data.username || '';
    }
    if (els.password) {
      els.password.value = data.password || '';
    }
    if (els.version) {
      els.version.textContent = String(data.version || '—');
    }
    if (els.port) {
      els.port.textContent = data.port ? String(data.port) : '—';
    }
  }

  /**
   * 保存账号密码设置。
   * @param {SubmitEvent} event 表单提交事件。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function handleSave(event) {
    event.preventDefault();
    if (!els.username || !els.password) {
      return;
    }
    const username = els.username.value.trim();
    const password = els.password.value;
    if (!username || !password) {
      setStatus('账号和密码不能为空。', 'error');
      return;
    }
    const button = els.save;
    if (button) {
      button.disabled = true;
    }
    App.setLoading(true, '正在保存设置…');
    try {
      await App.callOk('save_settings', { username, password });
      setStatus('设置已保存，下次登录将使用新凭据。', 'success');
      App.toast('设置已保存', 'success');
    } catch (error) {
      setStatus(`保存失败：${error.message}`, 'error');
      App.toast(`保存失败: ${error.message}`, 'error');
    } finally {
      App.setLoading(false);
      if (button) {
        button.disabled = false;
      }
    }
  }

  /**
   * 渲染知识库表格。
   * @returns {void}
   */
  function renderBanks(banks) {
    if (!els.bankBody) {
      return;
    }
    els.bankBody.innerHTML = '';
    if (!Array.isArray(banks) || banks.length === 0) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 3;
      cell.className = 'table-empty';
      cell.textContent = '未找到知识库文件。';
      row.appendChild(cell);
      els.bankBody.appendChild(row);
      return;
    }
    banks.forEach((bank) => {
      const row = document.createElement('tr');
      const featureCell = document.createElement('td');
      featureCell.textContent = String(bank.feature || '—');
      const versionCell = document.createElement('td');
      versionCell.textContent = 'v' + String(bank.version || '—');
      const countCell = document.createElement('td');
      countCell.textContent = String(bank.count === undefined ? '—' : bank.count);
      row.appendChild(featureCell);
      row.appendChild(versionCell);
      row.appendChild(countCell);
      els.bankBody.appendChild(row);
    });
  }

  /**
   * 读取并渲染知识库信息。
   * @param {boolean} [showLoading] 是否显示全局加载遮罩。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function loadBanks(showLoading) {
    if (showLoading) {
      App.setLoading(true, '正在读取知识库…');
    }
    try {
      const data = await App.callOk('get_bank_info');
      renderBanks(data.banks || []);
    } finally {
      if (showLoading) {
        App.setLoading(false);
      }
    }
  }

  /**
   * 绑定页面事件。
   * @returns {void}
   */
  function bindEvents() {
    if (els.form) {
      els.form.addEventListener('submit', handleSave);
    }
    if (els.togglePassword && els.password) {
      els.togglePassword.addEventListener('click', () => {
        const visible = els.password.type === 'text';
        els.password.type = visible ? 'password' : 'text';
        els.togglePassword.textContent = visible ? '显示密码' : '隐藏密码';
      });
    }
    if (els.refreshBanks) {
      els.refreshBanks.addEventListener('click', async () => {
        els.refreshBanks.disabled = true;
        try {
          await loadBanks(true);
          App.toast('知识库信息已刷新', 'success');
        } catch (error) {
          App.toast(`读取知识库失败: ${error.message}`, 'error');
        } finally {
          els.refreshBanks.disabled = false;
        }
      });
    }
  }

  /**
   * 页面首次初始化。
   * @param {HTMLElement} container 内容容器。
   * @returns {void}
   */
  function init(container) {
    cacheElements();
    bindEvents();
  }

  /**
   * 每次切换到本标签时重新读取设置与知识库。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function onActivate() {
    try {
      await loadSettings();
      await loadBanks(false);
    } catch (error) {
      setStatus(`读取设置失败：${error.message}`, 'error');
      App.toast(`读取设置失败: ${error.message}`, 'error');
    }
  }

  App.registerPage(PAGE_NAME, { init: init, onActivate: onActivate });
})();
