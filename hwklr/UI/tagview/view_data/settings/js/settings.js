/*
  作者: Gary
  编写日期: 2026-10-31 20:45
  最后更新: 2026-11-01 13:05
  文件名: settings.js
  主要用途: “设置”页面逻辑：动态分组、Feature 开发标记表、失焦/开关自动保存、alert 字段二次确认、板块高亮与知识库信息。
  文件版本: 2.1.3
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
    // 字段首次渲染时的值：用于判断高级设置是否偏离初始值。
    baselines: new Map(),
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
    // 开关与 Feature 开发标记都是复选框，按选中状态取值。
    if (input.dataset.kind === 'switch' || input.dataset.kind === 'feature') {
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
   * 生成字段基线的唯一键。
   * @param {string} groupId 分组 ID。
   * @param {string} key 字段键。
   * @returns {string} 唯一键。
   */
  function baselineKey(groupId, key) {
    return `${groupId}::${key}`;
  }

  /**
   * 计算输入元素对应的基线键；Feature 表格按“字段键 + 功能名”区分每一行。
   * @param {HTMLElement} input 输入元素。
   * @returns {string} 基线键。
   */
  function baselineId(input) {
    const suffix = input.dataset.feature
      ? `${input.dataset.key}:${input.dataset.feature}`
      : input.dataset.key;
    return baselineKey(input.dataset.group, suffix);
  }

  /**
   * 记录字段首次渲染时的值（用于判断高级设置是否偏离初始值）。
   * @param {string} groupId 分组 ID。
   * @param {string} key 字段键。
   * @param {string} value 初始值。
   * @returns {void}
   */
  function rememberBaseline(groupId, key, value) {
    const id = baselineKey(groupId, key);
    if (!state.baselines.has(id)) {
      state.baselines.set(id, value);
    }
  }

  /**
   * 判断字段保存前是否需要弹出警告。
   * 仅深黄色标记的 alert 字段且值确实偏离初始值时才提示；
   * 普通字段直接自动保存。
   * @param {HTMLElement} input 输入元素。
   * @returns {boolean} 需要警告返回 true。
   */
  function needsAlertConfirm(input) {
    if (input.dataset.alert !== 'true' || !fieldChanged(input)) {
      return false;
    }
    const baseline = state.baselines.get(baselineId(input));
    return baseline !== undefined && fieldValue(input) !== baseline;
  }

  /**
   * 弹出高级设置修改确认窗口。
   * @param {HTMLElement} input 触发提示的输入元素。
   * @returns {Promise<boolean>} 用户确认返回 true，取消返回 false。
   */
  function showAlertModal(input) {
    return new Promise((resolve) => {
      const label = input.dataset.label || input.dataset.key;
      const baseline = state.baselines.get(baselineId(input));
      const turningOn =
        (input.dataset.kind === 'switch' || input.dataset.kind === 'feature') &&
        Boolean(input.checked) &&
        baseline !== 'true';
      const backdrop = node('div', 'modal-backdrop alert-confirm-backdrop');
      const modal = node('div', 'modal alert-confirm-modal');
      modal.appendChild(
        node('h3', '', `注意：正在${turningOn ? '开启' : '修改'}${label}`)
      );
      // 提示内容按原样换行展示（换行样式见 settings.css 的 .alert-confirm-text）。
      const body = node(
        'p',
        'alert-confirm-text',
        '随意修改高级设置可能导致功能失效！\n如果你不清楚你在做什么，请不要继续'
      );
      modal.appendChild(body);

      const actions = node('div', 'alert-confirm-actions');
      const cancel = node('button', 'btn ghost', '取消');
      cancel.type = 'button';
      const confirm = node('button', 'btn primary', '我清楚我在做什么');
      confirm.type = 'button';
      actions.appendChild(cancel);
      actions.appendChild(confirm);
      modal.appendChild(actions);
      backdrop.appendChild(modal);

      let settled = false;
      /**
       * 关闭弹窗并返回用户选择。
       * @param {boolean} accepted 是否确认。
       * @returns {void}
       */
      const finish = (accepted) => {
        if (settled) {
          return;
        }
        settled = true;
        backdrop.remove();
        resolve(accepted);
      };
      cancel.addEventListener('click', () => finish(false));
      confirm.addEventListener('click', () => finish(true));
      // 点击遮罩视为取消，避免误操作后弹窗无法关闭。
      backdrop.addEventListener('click', (event) => {
        if (event.target === backdrop) {
          finish(false);
        }
      });
      document.body.appendChild(backdrop);
      confirm.focus();
    });
  }

  /**
   * 收集指定分组中需要确认的高级设置字段。
   * @param {Array<string>|null} onlyGroupIds 限定分组；null 表示全部。
   * @returns {Array<HTMLElement>} 需要确认的输入元素。
   */
  function findAlertInputs(onlyGroupIds) {
    if (!els.groups) {
      return [];
    }
    const allowed = Array.isArray(onlyGroupIds) ? new Set(onlyGroupIds) : null;
    return Array.from(els.groups.querySelectorAll('[data-key]')).filter((input) => {
      if (allowed && !allowed.has(input.dataset.group)) {
        return false;
      }
      return needsAlertConfirm(input);
    });
  }

  /**
   * 依次询问所有被修改的高级设置。
   * @param {Array<string>|null} onlyGroupIds 限定分组；null 表示全部。
   * @returns {Promise<{ok: boolean, inputs: Array<HTMLElement>}>} 是否确认及涉及的字段。
   */
  async function confirmAlertChanges(onlyGroupIds) {
    const inputs = findAlertInputs(onlyGroupIds);
    for (const input of inputs) {
      const accepted = await showAlertModal(input);
      if (!accepted) {
        return { ok: false, inputs };
      }
    }
    return { ok: true, inputs };
  }

  /**
   * 取消保存时把高级设置字段还原为上次保存的值。
   * @param {Array<HTMLElement>} inputs 字段列表。
   * @returns {void}
   */
  function revertAlertInputs(inputs) {
    inputs.forEach((input) => {
      if (input.dataset.kind === 'switch' || input.dataset.kind === 'feature') {
        input.checked = input.dataset.initial === 'true';
      } else {
        input.value = input.dataset.initial || '';
      }
    });
  }

  /**
   * 判断分组中是否仍有未保存的改动。
   * @param {string} groupId 分组 ID。
   * @returns {boolean} 有改动返回 true。
   */
  function hasPendingChange(groupId) {
    if (!els.groups) {
      return false;
    }
    const card = Array.from(els.groups.querySelectorAll('.settings-group'))
      .find((item) => item.dataset.group === groupId);
    if (!card) {
      return false;
    }
    return Array.from(card.querySelectorAll('[data-key]')).some(
      (input) => fieldChanged(input)
    );
  }

  /**
   * 取消高级设置后，把仍有其他改动的分组重新加入自动保存队列。
   * @param {Array<string>} groupIds 分组 ID 列表。
   * @returns {void}
   */
  function requeueChangedGroups(groupIds) {
    groupIds.forEach((groupId) => {
      if (hasPendingChange(groupId)) {
        state.pendingAutoSave.add(groupId);
      }
    });
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
    state.autoSaving = true;
    try {
      // #高级设置改动必须先经用户确认；取消则回滚并只保存其余普通改动。
      const verdict = await confirmAlertChanges(groupIds);
      if (!verdict.ok) {
        revertAlertInputs(verdict.inputs);
        setStatus('已取消保存高级设置。');
        requeueChangedGroups(groupIds);
        return;
      }
      const groups = collectGroups(groupIds);
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
    // 可选填字段以灰字 + 左上角灰色星号标记；alert 字段标签使用深黄色。
    const classes = ['settings-field'];
    if (field.is_necessary === false) {
      classes.push('optional');
    }
    if (field.alert) {
      classes.push('alert-field');
    }
    const wrapper = node('div', classes.join(' '));
    const label = node('span', 'settings-field-label', field.label || field.key);

    // Feature 开发标记：只读显示功能与版本，复选框写入 dev / release。
    if (field.kind === 'features') {
      wrapper.appendChild(label);
      const table = node('div', 'settings-feature-table');
      const head = node('div', 'settings-feature-row head');
      head.appendChild(node('span', 'feature-name', 'Feature'));
      head.appendChild(node('span', 'feature-version', '版本'));
      head.appendChild(node('span', 'feature-dev', '开发构建'));
      table.appendChild(head);
      (field.rows || []).forEach((row) => {
        const item = node('div', 'settings-feature-row');
        item.appendChild(node('span', 'feature-name', String(row.name || '')));
        item.appendChild(
          node('span', 'feature-version mono', String(row.version || '0.0.0'))
        );
        const cell = node('div', 'feature-dev');
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = Boolean(row.dev);
        input.dataset.group = group.group_id;
        input.dataset.key = field.key;
        input.dataset.feature = String(row.name || '');
        input.dataset.kind = 'feature';
        input.dataset.initial = String(Boolean(row.dev));
        input.dataset.alert = String(Boolean(field.alert));
        input.dataset.label = `开发构建：${row.name}`;
        rememberBaseline(
          group.group_id,
          `${field.key}:${row.name}`,
          String(Boolean(row.dev))
        );
        input.addEventListener('change', () =>
          scheduleAutoSave(group.group_id, input)
        );
        cell.appendChild(input);
        item.appendChild(cell);
        table.appendChild(item);
      });
      wrapper.appendChild(table);
      if (field.help) {
        wrapper.appendChild(node('p', 'settings-field-help', field.help));
      }
      return wrapper;
    }

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
      input.dataset.alert = String(Boolean(field.alert));
      input.dataset.label = field.label || field.key;
      rememberBaseline(group.group_id, field.key, String(Boolean(field.value)));
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
    input.dataset.alert = String(Boolean(field.alert));
    input.dataset.label = field.label || field.key;
    // 记录首次渲染值作为高级设置警告的初始值基准。
    rememberBaseline(group.group_id, field.key, String(input.value));

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
        if (kind === 'feature') {
          // #features 字段把每一行聚合成 {功能名: "dev"|"release"}。
          if (!values[key] || typeof values[key] !== 'object') {
            values[key] = {};
          }
          values[key][input.dataset.feature] = input.checked ? 'dev' : 'release';
        } else if (kind === 'switch') {
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
    try {
      // #保存前先确认高级设置改动；用户取消时不提交任何改动。
      const verdict = await confirmAlertChanges(null);
      if (!verdict.ok) {
        revertAlertInputs(verdict.inputs);
        setStatus('已取消保存高级设置。');
        return;
      }
      App.setLoading(true, '正在保存设置…');
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
