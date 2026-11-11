/*
  作者: Gary
  编写日期: 2026-10-31 20:45
  最后更新: 2026-11-11 20:00
  文件名: settings.js
  主要用途: “设置”页面逻辑：动态分组、功能启用开关、tooltip 气泡、分组折叠、第三方扩展加载/启停、自动保存、alert 字段二次确认与知识库信息。
  文件版本: 4.4.3
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
    extensionData: null,
    extensionList: null,
    extensionLocal: null,
    extensionGit: null,
    // 用户展开的分组；通用分组默认展开，其余分组默认折叠，均可手动切换。
    expandedGroups: new Set(['general']),
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
   * 构建设置项名称行：名称 + 可选 (i) 帮助按钮与气泡。
   * @param {Object} field 字段定义。
   * @returns {HTMLElement} 名称行。
   */
  function buildFieldLabel(field) {
    const row = node('div', 'settings-label-row');
    row.appendChild(node('span', 'settings-field-label', field.label || field.key));
    const tooltip = String(field.tooltip || '').trim();
    if (!tooltip) {
      return row;
    }
    // #气泡标题使用设置项名称；alert 深黄、非必填浅灰，正文始终浅灰。
    const wrap = node('span', 'settings-info-wrap');
    const info = node('button', 'settings-info', 'i');
    info.type = 'button';
    info.setAttribute('aria-label', '查看设置说明');
    info.setAttribute('aria-expanded', 'false');
    const bubble = node('span', 'settings-tooltip');
    const title = node(
      'strong',
      'settings-tooltip-title',
      (field.label || field.key) + '：'
    );
    if (field.alert) {
      title.classList.add('alert');
    } else if (field.is_necessary === false) {
      title.classList.add('optional');
    }
    bubble.appendChild(title);
    bubble.appendChild(node('span', 'settings-tooltip-body', tooltip));
    wrap.appendChild(info);
    wrap.appendChild(bubble);
    info.addEventListener('click', (event) => {
      event.preventDefault();
      const pinned = wrap.classList.toggle('pinned');
      info.setAttribute('aria-expanded', String(pinned));
    });
    row.appendChild(wrap);
    return row;
  }

  /**
   * 更新功能分组头部的“启用 / 停用”文字状态。
   * @param {HTMLElement} card 分组卡片。
   * @param {boolean} enabled 是否启用。
   * @returns {void}
   */
  function syncGroupEnabledText(card, enabled) {
    const text = card.querySelector('.group-enabled-text');
    if (!text) {
      return;
    }
    text.className = 'group-enabled-text ' + (enabled ? 'on' : 'off');
    text.textContent = enabled ? '启用' : '停用';
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
      if (group.enabled_editable && typeof group.enabled === 'boolean') {
        syncGroupEnabledText(card, group.enabled);
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
   * 显示一个通用消息弹窗。
   * @param {string} title 标题。
   * @param {string} message 正文。
   * @param {string} [confirmText] 确认按钮文本。
   * @returns {void}
   */
  function showMessageModal(title, message, confirmText) {
    const backdrop = node('div', 'modal-backdrop settings-message-backdrop');
    const modal = node('div', 'modal settings-message-modal');
    modal.appendChild(node('h3', '', title));
    const body = node('p', 'settings-message-text', message);
    modal.appendChild(body);
    const actions = node('div', 'alert-confirm-actions');
    const confirm = node('button', 'btn primary', confirmText || '知道了');
    confirm.type = 'button';
    confirm.addEventListener('click', () => backdrop.remove());
    actions.appendChild(confirm);
    modal.appendChild(actions);
    backdrop.appendChild(modal);
    backdrop.addEventListener('click', (event) => {
      if (event.target === backdrop) {
        backdrop.remove();
      }
    });
    document.body.appendChild(backdrop);
    confirm.focus();
  }

  /**
   * 显示输入弹窗并返回用户输入。
   * @param {string} title 标题。
   * @param {string} label 输入框标签。
   * @param {string} [placeholder] 占位文本。
   * @returns {Promise<string>} 用户输入；取消时返回空字符串。
   */
  function showPromptModal(title, label, placeholder) {
    return new Promise((resolve) => {
      const backdrop = node('div', 'modal-backdrop settings-message-backdrop');
      const modal = node('div', 'modal settings-message-modal');
      modal.appendChild(node('h3', '', title));
      modal.appendChild(node('p', 'settings-message-text', label));
      const input = document.createElement('input');
      input.type = 'text';
      input.placeholder = placeholder || '';
      input.className = 'settings-prompt-input';
      modal.appendChild(input);
      const actions = node('div', 'alert-confirm-actions');
      const cancel = node('button', 'btn ghost', '取消');
      cancel.type = 'button';
      const confirm = node('button', 'btn primary', '确定');
      confirm.type = 'button';
      const finish = (value) => {
        backdrop.remove();
        resolve(value);
      };
      cancel.addEventListener('click', () => finish(''));
      confirm.addEventListener('click', () => finish(String(input.value || '').trim()));
      input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          finish(String(input.value || '').trim());
        }
      });
      actions.appendChild(cancel);
      actions.appendChild(confirm);
      modal.appendChild(actions);
      backdrop.appendChild(modal);
      backdrop.addEventListener('click', (event) => {
        if (event.target === backdrop) {
          finish('');
        }
      });
      document.body.appendChild(backdrop);
      input.focus();
    });
  }

  /**
   * 切换某个功能板块的启用状态。
   * @param {Object} group 设置分组。
   * @param {HTMLInputElement} input 开关输入。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function toggleGroupEnabled(group, input) {
    const enabled = Boolean(input.checked);
    input.disabled = true;
    try {
      const data = await App.callOk('set_group_enabled', {
        group_id: group.group_id,
        enabled,
      });
      updateGroupStatuses(data.groups || []);
      const card = input.closest('.settings-group');
      if (card) {
        syncGroupEnabledText(card, enabled);
      }
      await App.refreshTags();
      const stillActive = App.tags.some((tag) => tag.name === App.active);
      if (!stillActive && App.tags.length > 0) {
        await App.activate(App.tags[0].name);
      }
      App.toast(enabled ? '功能已启用' : '功能已停用', 'success');
    } catch (error) {
      input.checked = !enabled;
      const card = input.closest('.settings-group');
      if (card) {
        syncGroupEnabledText(card, !enabled);
      }
      App.toast(`切换失败: ${error.message}`, 'error');
    } finally {
      input.disabled = false;
    }
  }

  /**
   * 渲染第三方扩展列表。
   * @param {Object} data 扩展数据。
   * @returns {void}
   */
  function renderExtensionList(data) {
    if (!state.extensionList) {
      return;
    }
    const extensions = Array.isArray(data.extensions) ? data.extensions : [];
    if (state.extensionGit) {
      state.extensionGit.disabled = !data.git_available;
      state.extensionGit.title = data.git_available
        ? '从 Git 仓库加载扩展'
        : '未检测到 git，无法从 Git 仓库加载';
    }
    state.extensionList.innerHTML = '';
    if (extensions.length === 0) {
      state.extensionList.appendChild(node('p', 'muted', '尚未导入第三方扩展。'));
    }
    extensions.forEach((extension) => {
      const row = node('div', 'extension-row');
      const info = node('div', 'extension-info');
      const title = node('div', 'extension-title');
      title.appendChild(node('strong', '', String(extension.name || '未命名扩展')));
      title.appendChild(
        node('span', 'extension-version mono', String(extension.version_display || extension.version || ''))
      );
      if (extension.official) {
        title.appendChild(node('span', 'extension-official', '官方'));
      }
      info.appendChild(title);
      info.appendChild(
        node(
          'span',
          'extension-meta',
          `包名 ${extension.package || '—'} · 作者 ${extension.author || '—'} · 更新 ${extension.update_date || '—'}`
        )
      );
      row.appendChild(info);
      const switchLabel = node('label', 'switch');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = Boolean(extension.enabled);
      input.addEventListener('change', () => {
        setExtensionEnabled(extension.name, input.checked, input).catch((error) =>
          App.toast(`切换扩展失败: ${error.message}`, 'error')
        );
      });
      switchLabel.appendChild(input);
      switchLabel.appendChild(node('span', 'slider'));
      row.appendChild(switchLabel);
      state.extensionList.appendChild(row);
    });
    if (Array.isArray(data.errors) && data.errors.length > 0) {
      state.extensionList.appendChild(
        node('p', 'settings-field-help', `部分扩展加载失败：${data.errors.join('；')}`)
      );
    }
  }

  /**
   * 启用或停用第三方扩展。
   * @param {string} name 扩展标签名。
   * @param {boolean} enabled 是否启用。
   * @param {HTMLInputElement} input 开关输入。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function setExtensionEnabled(name, enabled, input) {
    input.disabled = true;
    try {
      const data = await App.callOk('set_extension_enabled', { name, enabled });
      renderExtensionList(data);
      await App.refreshTags();
      const stillActive = App.tags.some((tag) => tag.name === App.active);
      if (!stillActive && App.tags.length > 0) {
        await App.activate(App.tags[0].name);
      }
      App.toast(enabled ? '扩展已启用' : '扩展已停用', 'success');
    } catch (error) {
      input.checked = !enabled;
      App.toast(`切换扩展失败: ${error.message}`, 'error');
    } finally {
      input.disabled = false;
    }
  }

  /**
   * 读取扩展列表。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function loadExtensions() {
    if (!state.extensionList) {
      return;
    }
    try {
      const data = await App.callOk('get_extensions');
      state.extensionData = data;
      renderExtensionList(data);
    } catch (error) {
      App.toast(`读取扩展列表失败: ${error.message}`, 'error');
    }
  }

  /**
   * 从本地 zip 导入扩展。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function loadLocalExtension() {
    try {
      const picked = await App.callOk('pick_extension_zip');
      const path = String((picked && picked.path) || '');
      if (!path) {
        return;
      }
      App.setLoading(true, '正在导入扩展…');
      const result = await App.callOk('load_extension_zip', { path });
      await App.refreshTags();
      await loadExtensions();
      const extension = (result && result.extension) || {};
      showMessageModal(
        '导入成功',
        `已导入扩展「${extension.name || result.tab || '未知扩展'}」。可在下方列表中启用或停用。`,
        '好的'
      );
    } catch (error) {
      showMessageModal('导入失败', String(error.message || '未知错误'));
    } finally {
      App.setLoading(false);
    }
  }

  /**
   * 从 Git 仓库导入扩展。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function loadGitExtension() {
    const url = await showPromptModal(
      '从 Git 仓库加载',
      '请输入包含扩展结构的 Git 仓库地址：',
      'https://github.com/user/extension.git'
    );
    if (!url) {
      return;
    }
    try {
      App.setLoading(true, '正在克隆并导入扩展…');
      const result = await App.callOk('load_extension_git', { url });
      await App.refreshTags();
      await loadExtensions();
      const extension = (result && result.extension) || {};
      showMessageModal(
        '导入成功',
        `已从 Git 仓库导入扩展「${extension.name || result.tab || '未知扩展'}」。`,
        '好的'
      );
    } catch (error) {
      showMessageModal('导入失败', String(error.message || '未知错误'));
    } finally {
      App.setLoading(false);
    }
  }

  /**
   * 构建第三方扩展加载器字段。
   * @param {Object} group 设置分组。
   * @param {Object} field 字段定义。
   * @returns {HTMLElement} 字段容器。
   */
  function buildExtensionField(group, field) {
    const wrapper = node('div', 'settings-field extension-field');
    wrapper.appendChild(buildFieldLabel(field));
    const panel = node('div', 'extension-panel');
    const buttons = node('div', 'extension-buttons');
    const local = node('button', 'btn extension-local', '从本地加载');
    local.type = 'button';
    local.addEventListener('click', () => {
      loadLocalExtension().catch((error) =>
        App.toast(`导入扩展失败: ${error.message}`, 'error')
      );
    });
    const git = node('button', 'btn extension-git');
    git.type = 'button';
    git.innerHTML =
      '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">' +
      '<path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>' +
      '<span>从 Git 仓库加载</span>';
    git.addEventListener('click', () => {
      loadGitExtension().catch((error) =>
        App.toast(`导入扩展失败: ${error.message}`, 'error')
      );
    });
    buttons.appendChild(local);
    buttons.appendChild(git);
    const list = node('div', 'extension-list');
    panel.appendChild(buttons);
    panel.appendChild(list);
    wrapper.appendChild(panel);
    if (field.help) {
      wrapper.appendChild(node('p', 'settings-field-help', field.help));
    }
    state.extensionLocal = local;
    state.extensionGit = git;
    state.extensionList = list;
    state.extensionData = null;
    return wrapper;
  }

  /**
   * 构建一个设置字段。
   * @param {Object} group 设置分组。
   * @param {Object} field 字段定义。
   * @returns {HTMLElement} 字段容器。
   */
  function buildField(group, field) {
    if (field.kind === 'extensions') {
      return buildExtensionField(group, field);
    }
    // 可选填字段以灰字 + 左上角灰色星号标记；alert 字段标签使用深黄色。
    const classes = ['settings-field'];
    if (field.is_necessary === false) {
      classes.push('optional');
    }
    if (field.alert) {
      classes.push('alert-field');
    }
    const wrapper = node('div', classes.join(' '));

    // Feature 开发标记：只读显示功能与版本，复选框写入 dev / release。
    if (field.kind === 'features') {
      wrapper.appendChild(buildFieldLabel(field));
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
      text.appendChild(buildFieldLabel(field));
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

    wrapper.appendChild(buildFieldLabel(field));
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

    if (field.kind === 'file') {
      const fileWrap = node('div', 'file-picker-wrap');
      fileWrap.appendChild(input);
      const browse = node('button', 'btn ghost small', '选择');
      browse.type = 'button';
      browse.addEventListener('click', () => {
        App.callOk('pick_plugin_template')
          .then((data) => {
            const path = String((data && data.path) || '');
            if (!path) {
              return;
            }
            input.value = path;
            scheduleAutoSave(group.group_id, input);
          })
          .catch((error) =>
            App.toast(`选择模板失败: ${error.message}`, 'error')
          );
      });
      fileWrap.appendChild(browse);
      wrapper.appendChild(fileWrap);
    } else if (field.secret && field.kind !== 'select') {
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
    // 所有分组都可折叠；通用默认展开，其余默认折叠，只保留头部开关与状态。
    const collapsed = !state.expandedGroups.has(group.group_id);
    if (collapsed) {
      card.classList.add('collapsed');
    }
    const head = node('div', 'settings-group-head');
    const titleText = group.title || group.group_id;
    const toggle = node('button', 'settings-group-toggle');
    toggle.type = 'button';
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.appendChild(node('span', 'settings-group-title', titleText));
    toggle.appendChild(node('span', 'settings-group-chevron', '▾'));
    toggle.addEventListener('click', () => {
      const nextCollapsed = !card.classList.contains('collapsed');
      card.classList.toggle('collapsed', nextCollapsed);
      if (nextCollapsed) {
        state.expandedGroups.delete(group.group_id);
      } else {
        state.expandedGroups.add(group.group_id);
      }
      toggle.setAttribute('aria-expanded', String(!nextCollapsed));
    });
    head.appendChild(toggle);
    const actions = node('div', 'settings-group-head-actions');
    // #每个功能板块右上角的启用开关（设置/关于板块不会注册到这里）。
    if (group.enabled_editable) {
      const switchLabel = node('label', 'switch group-switch');
      switchLabel.title = group.enabled ? '点击停用该功能' : '点击启用该功能';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = group.enabled !== false;
      input.addEventListener('change', () => {
        toggleGroupEnabled(group, input).catch((error) =>
          App.toast(`切换失败: ${error.message}`, 'error')
        );
      });
      switchLabel.appendChild(input);
      switchLabel.appendChild(node('span', 'slider'));
      actions.appendChild(switchLabel);
      actions.appendChild(
        node(
          'span',
          'group-enabled-text ' + (group.enabled !== false ? 'on' : 'off'),
          group.enabled !== false ? '启用' : '停用'
        )
      );
    }
    const status = node(
      'span',
      'group-status ' + (group.complete ? 'ok' : 'missing'),
      group.complete ? '已完整' : '缺少设置'
    );
    actions.appendChild(status);
    head.appendChild(actions);
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
    state.extensionList = null;
    state.extensionLocal = null;
    state.extensionGit = null;
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
    await loadExtensions();
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
      await loadExtensions();
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
    // #从功能页跳转过来时自动展开目标分组，再滚动并高亮。
    state.expandedGroups.add(groupId);
    target.classList.remove('collapsed');
    const toggle = target.querySelector('.settings-group-toggle');
    if (toggle) {
      toggle.setAttribute('aria-expanded', 'true');
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
      // 每次进入设置页只展开“通用”和本次跳转来源，其余分组保持折叠。
      state.expandedGroups = new Set(['general']);
      const target = App.takeSettingsTarget ? App.takeSettingsTarget() : '';
      if (target) {
        state.expandedGroups.add(target);
      }
      await loadSettings();
      await loadBanks();
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
