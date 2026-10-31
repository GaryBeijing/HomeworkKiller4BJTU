/*
  作者: Gary
  编写日期: 2026-10-31 20:45
  最后更新: 2026-11-01 01:15
  文件名: settings.js
  主要用途: “设置”页面逻辑：动态分组、失焦/开关自动保存、板块高亮与知识库信息。
  文件版本: 2.0.1
*/

(function () {
  'use strict';

  const PAGE_NAME = '设置';

  /** 页面元素缓存。 */
  const els = {};

  /** 页面状态。 */
  const state = {
    groups: [],
    busy: false,
    highlightTimer: null,
    pendingAutoSave: new Set(),
    autoSaveTimer: null,
    autoSaving: false,
  };

  /**
   * 缓存页面元素引用。
   * @returns {void}
   */
  function cacheElements() {
    els.groups = document.getElementById('settings-groups');
    els.save = document.getElementById('settings-save');
    els.status = document.getElementById('settings-status');
    els.version = document.getElementById('settings-version');
    els.port = document.getElementById('settings-port');
    els.bankBody = document.getElementById('settings-bank-body');
  }

  /**
   * 更新设置页状态提示。
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
   * 创建普通文本节点。
   * @param {string} tagName 标签名。
   * @param {string} className 类名。
   * @param {string} text 文本。
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
   * 读取字段当前值（统一为字符串）。
   * @param {HTMLElement} input 输入元素。
   * @returns {string} 当前值。
   */
  function fieldValue(input) {
    if (input.dataset.kind === 'switch') {
      return String(Boolean(input.checked));
    }
    return String(input.value);
  }

  /**
   * 判断字段是否相对上次保存发生了变化。
   * @param {HTMLElement} input 输入元素。
   * @returns {boolean} 有变化返回 true。
   */
  function fieldChanged(input) {
    return fieldValue(input) !== (input.dataset.initial || '');
  }

  /**
   * 安排一次自动保存。
   * @param {string} groupId 设置分组 ID。
   * @param {HTMLElement} input 触发字段。
   * @returns {void}
   */
  function scheduleAutoSave(groupId, input) {
    if (input && !fieldChanged(input)) {
      return;
    }
    state.pendingAutoSave.add(groupId);
    scheduleAutoSaveFlush();
  }

  /**
   * 重置自动保存防抖计时器。
   * @returns {void}
   */
  function scheduleAutoSaveFlush() {
    if (state.autoSaveTimer) {
      window.clearTimeout(state.autoSaveTimer);
    }
    state.autoSaveTimer = window.setTimeout(flushAutoSave, 260);
  }

  /**
   * 更新指定分组的“已保存初始值”。
   * @param {Array<string>} groupIds 分组 ID 列表。
   * @returns {void}
   */
  function updateInitialValues(groupIds) {
    const allowed = new Set(groupIds);
    if (!els.groups) {
      return;
    }
    els.groups.querySelectorAll('.settings-group').forEach((card) => {
      if (!allowed.has(card.dataset.group)) {
        return;
      }
      card.querySelectorAll('[data-key]').forEach((input) => {
        input.dataset.initial = fieldValue(input);
      });
    });
  }

  /**
   * 只更新分组状态徽标，避免自动保存时重建 DOM 丢失焦点。
   * @param {Array} groups 服务端返回的分组数据。
   * @returns {void}
   */
  function updateGroupStatuses(groups) {
    if (!els.groups || !Array.isArray(groups)) {
      return;
    }
    groups.forEach((group) => {
      const card = Array.from(els.groups.querySelectorAll('.settings-group'))
        .find((item) => item.dataset.group === group.group_id);
      if (!card) {
        return;
      }
      const badge = card.querySelector('.group-status');
      if (badge) {
        badge.className = 'group-status ' + (group.complete ? 'ok' : 'missing');
        badge.textContent = group.complete ? '已完整' : '缺少设置';
      }
    });
  }

  /**
   * 执行自动保存。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function flushAutoSave() {
    state.autoSaveTimer = null;
    if (state.busy || state.autoSaving) {
      if (state.pendingAutoSave.size > 0) {
        scheduleAutoSaveFlush();
      }
      return;
    }
    if (state.pendingAutoSave.size === 0) {
      return;
    }
    const groupIds = Array.from(state.pendingAutoSave);
    state.pendingAutoSave.clear();
    const groups = collectGroups(groupIds);
    state.autoSaving = true;
    try {
      const data = await App.callOk('save_settings', { groups });
      updateGroupStatuses(data.groups || []);
      updateInitialValues(groupIds);
      setStatus('设置已保存。', 'success');
      App.toast('设置已保存', 'success');
      await App.refreshTags();
    } catch (error) {
      setStatus(`自动保存失败：${error.message}`, 'error');
      App.toast(`自动保存失败: ${error.message}`, 'error');
    } finally {
      state.autoSaving = false;
      if (state.pendingAutoSave.size > 0) {
        scheduleAutoSaveFlush();
      }
    }
  }

  /**
   * 构建一个设置字段。
   * @param {Object} group 设置分组。
   * @param {Object} field 字段定义。
   * @returns {HTMLElement} 字段容器。
   */
  function buildField(group, field) {
    const wrapper = node('div', 'settings-field');
    const label = node('span', 'settings-field-label', field.label || field.key);

    if (field.kind === 'switch') {
      const row = node('div', 'switch-field');
      const text = node('div', 'switch-text');
      text.appendChild(label);
      if (field.help) {
        text.appendChild(node('p', 'settings-field-help', field.help));
      }
      row.appendChild(text);
      const switchLabel = node('label', 'switch');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = Boolean(field.value);
      input.dataset.group = group.group_id;
      input.dataset.key = field.key;
      input.dataset.kind = 'switch';
      input.dataset.initial = String(Boolean(field.value));
      input.addEventListener('change', () => scheduleAutoSave(group.group_id, input));
      switchLabel.appendChild(input);
      switchLabel.appendChild(node('span', 'slider'));
      row.appendChild(switchLabel);
      wrapper.appendChild(row);
      return wrapper;
    }

    wrapper.appendChild(label);
    let input;
    if (field.kind === 'select') {
      input = document.createElement('select');
      (field.options || []).forEach((option) => {
        const item = document.createElement('option');
        item.value = String(option.value);
        item.textContent = String(option.label);
        if (String(option.value) === String(field.value)) {
          item.selected = true;
        }
        input.appendChild(item);
      });
    } else if (field.kind === 'number') {
      input = document.createElement('input');
      input.type = 'number';
      input.value = field.value === null || field.value === undefined ? '' : String(field.value);
      if (field.min !== null && field.min !== undefined) {
        input.min = String(field.min);
      }
      if (field.max !== null && field.max !== undefined) {
        input.max = String(field.max);
      }
      if (field.step !== null && field.step !== undefined) {
        input.step = String(field.step);
      }
    } else {
      input = document.createElement('input');
      input.type = field.secret ? 'password' : 'text';
      input.value = field.value === null || field.value === undefined ? '' : String(field.value);
      if (field.placeholder) {
        input.placeholder = field.placeholder;
      }
    }
    input.dataset.group = group.group_id;
    input.dataset.key = field.key;
    input.dataset.kind = field.kind || 'text';
    input.dataset.initial = String(input.value);

    if (field.kind === 'select') {
      input.addEventListener('change', () => scheduleAutoSave(group.group_id, input));
    }
    input.addEventListener('blur', () => scheduleAutoSave(group.group_id, input));

    if (field.secret && field.kind !== 'select') {
      const secretWrap = node('div', 'secret-wrap');
      secretWrap.appendChild(input);
      const toggle = node('button', 'btn ghost small', '显示');
      toggle.type = 'button';
      toggle.addEventListener('click', () => {
        const visible = input.type === 'text';
        input.type = visible ? 'password' : 'text';
        toggle.textContent = visible ? '显示' : '隐藏';
      });
      secretWrap.appendChild(toggle);
      wrapper.appendChild(secretWrap);
    } else {
      wrapper.appendChild(input);
    }

    if (field.help) {
      wrapper.appendChild(node('p', 'settings-field-help', field.help));
    }
    return wrapper;
  }

  /**
   * 构建一个设置分组卡片。
   * @param {Object} group 分组数据。
   * @returns {HTMLElement} 分组卡片。
   */
  function buildGroup(group) {
    const card = node('section', 'settings-group');
    card.dataset.group = group.group_id;
    const head = node('div', 'settings-group-head');
    head.appendChild(node('h3', 'settings-group-title', group.title || group.group_id));
    const status = node(
      'span',
      'group-status ' + (group.complete ? 'ok' : 'missing'),
      group.complete ? '已完整' : '缺少设置'
    );
    head.appendChild(status);
    card.appendChild(head);
    if (group.description) {
      card.appendChild(node('p', 'settings-group-desc', group.description));
    }
    const fields = node('div', 'settings-fields');
    (group.fields || []).forEach((field) => fields.appendChild(buildField(group, field)));
    card.appendChild(fields);
    return card;
  }

  /**
   * 渲染所有设置分组。
   * @param {Array} groups 分组数据。
   * @returns {void}
   */
  function renderGroups(groups) {
    if (!els.groups) {
      return;
    }
    state.groups = Array.isArray(groups) ? groups : [];
    els.groups.innerHTML = '';
    if (state.groups.length === 0) {
      els.groups.appendChild(node('p', 'muted', '暂无可配置项。'));
      return;
    }
    state.groups.forEach((group) => els.groups.appendChild(buildGroup(group)));
  }

  /**
   * 渲染运行信息。
   * @param {Object} data 设置数据。
   * @returns {void}
   */
  function renderRuntime(data) {
    if (els.version) {
      els.version.textContent = String(data.version || '—');
    }
    if (els.port) {
      els.port.textContent = data.port ? String(data.port) : '—';
    }
  }

  /**
   * 读取并渲染设置。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function loadSettings() {
    const data = await App.callOk('get_settings');
    renderRuntime(data);
    renderGroups(data.groups || []);
  }

  /**
   * 收集分组当前输入值。
   * @param {Array<string>} [onlyGroupIds] 只收集这些分组；省略时收集全部。
   * @returns {Object} 分组值映射。
   */
  function collectGroups(onlyGroupIds) {
    const groups = {};
    if (!els.groups) {
      return groups;
    }
    const allowed = Array.isArray(onlyGroupIds) ? new Set(onlyGroupIds) : null;
    els.groups.querySelectorAll('.settings-group').forEach((card) => {
      const groupId = card.dataset.group;
      if (allowed && !allowed.has(groupId)) {
        return;
      }
      const values = {};
      card.querySelectorAll('[data-key]').forEach((input) => {
        const key = input.dataset.key;
        const kind = input.dataset.kind;
        if (kind === 'switch') {
          values[key] = Boolean(input.checked);
        } else if (kind === 'number') {
          values[key] = Number(input.value);
        } else {
          values[key] = input.value;
        }
      });
      groups[groupId] = values;
    });
    return groups;
  }

  /**
   * 保存所有设置。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function saveSettings() {
    if (state.busy) {
      return;
    }
    // 手动保存优先，取消尚未触发的自动保存。
    if (state.autoSaveTimer) {
      window.clearTimeout(state.autoSaveTimer);
      state.autoSaveTimer = null;
    }
    state.pendingAutoSave.clear();
    state.busy = true;
    if (els.save) {
      els.save.disabled = true;
    }
    App.setLoading(true, '正在保存设置…');
    try {
      const data = await App.callOk('save_settings', { groups: collectGroups() });
      renderRuntime(data);
      renderGroups(data.groups || []);
      setStatus('设置已保存。', 'success');
      App.toast('设置已保存', 'success');
      await App.refreshTags();
    } catch (error) {
      setStatus(`保存失败：${error.message}`, 'error');
      App.toast(`保存失败: ${error.message}`, 'error');
    } finally {
      App.setLoading(false);
      state.busy = false;
      if (els.save) {
        els.save.disabled = false;
      }
    }
  }

  /**
   * 高亮指定的设置板块并滚动到可见区域。
   * @param {string} groupId 板块 ID。
   * @returns {void}
   */
  function highlightGroup(groupId) {
    if (!groupId || !els.groups) {
      return;
    }
    const cards = Array.from(els.groups.querySelectorAll('.settings-group'));
    const target = cards.find((card) => card.dataset.group === groupId);
    if (!target) {
      return;
    }
    cards.forEach((card) => card.classList.remove('group-highlight'));
    target.classList.add('group-highlight');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (state.highlightTimer) {
      window.clearTimeout(state.highlightTimer);
    }
    state.highlightTimer = window.setTimeout(() => {
      target.classList.remove('group-highlight');
    }, 7000);
  }

  /**
   * 渲染知识库表格。
   * @param {Array} banks 知识库列表。
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
      row.appendChild(node('td', '', String(bank.feature || '—')));
      row.appendChild(node('td', '', 'v' + String(bank.version || '—')));
      row.appendChild(node('td', '', String(bank.count === undefined ? '—' : bank.count)));
      els.bankBody.appendChild(row);
    });
  }

  /**
   * 读取知识库信息。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function loadBanks() {
    const data = await App.callOk('get_bank_info');
    renderBanks(data.banks || []);
  }

  /**
   * 页面首次初始化。
   * @param {HTMLElement} container 内容容器。
   * @returns {void}
   */
  function init(container) {
    cacheElements();
    if (els.save) {
      els.save.addEventListener('click', saveSettings);
    }
  }

  /**
   * 每次切换到本标签时刷新设置与知识库，并处理来自锁定页面的高亮请求。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function onActivate() {
    try {
      await loadSettings();
      await loadBanks();
      const target = App.takeSettingsTarget ? App.takeSettingsTarget() : '';
      if (target) {
        window.setTimeout(() => highlightGroup(target), 60);
      }
    } catch (error) {
      setStatus(`读取设置失败：${error.message}`, 'error');
      App.toast(`读取设置失败: ${error.message}`, 'error');
    }
  }

  App.registerPage(PAGE_NAME, {
    init: init,
    onActivate: onActivate,
    highlightGroup: highlightGroup,
  });
})();
