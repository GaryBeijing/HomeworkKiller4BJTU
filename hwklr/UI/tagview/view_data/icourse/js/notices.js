/*
  作者: Gary
  编写日期: 2026-11-08 14:30
  最后更新: 2026-11-11 10:00
  文件名: notices.js
  主要用途: “中国大学慕课”页面提示条、日志与截图提醒（留存数据关闭时不显示路径）。
  文件版本: 4.4.3
*/
(function (global) {
  'use strict';
  const IC = global.Icourse = global.Icourse || {};

  const PAGE_NAME = IC.PAGE_NAME;
  const POLL_MS = IC.POLL_MS;
  const LOGIN_POLL_MS = IC.LOGIN_POLL_MS;
  const SYNC_POLL_MS = IC.SYNC_POLL_MS;
  const PERCENT_INTERVAL_MS = IC.PERCENT_INTERVAL_MS;
  const state = IC.state;
  const els = IC.els;
  const node = (...args) => IC.node(...args);
  const cacheElements = (...args) => IC.cacheElements(...args);
  const bindEvents = (...args) => IC.bindEvents(...args);
  const on = (...args) => IC.on(...args);
  const init = (...args) => IC.init(...args);
  const onActivate = (...args) => IC.onActivate(...args);
  const validateLogin = (...args) => IC.validateLogin(...args);
  const onDeactivate = (...args) => IC.onDeactivate(...args);
  const onCancelLoading = (...args) => IC.onCancelLoading(...args);
  const clearTimer = (...args) => IC.clearTimer(...args);
  const refreshState = (...args) => IC.refreshState(...args);
  const applyState = (...args) => IC.applyState(...args);
  const setAccountStatus = (...args) => IC.setAccountStatus(...args);
  const updateAccountBadge = (...args) => IC.updateAccountBadge(...args);
  const showRelogin = (...args) => IC.showRelogin(...args);
  const resetLoginWaiter = (...args) => IC.resetLoginWaiter(...args);
  const resolveLoginWaiter = (...args) => IC.resolveLoginWaiter(...args);
  const waitForLogin = (...args) => IC.waitForLogin(...args);
  const setLoadingForLogin = (...args) => IC.setLoadingForLogin(...args);
  const beginAutoLogin = (...args) => IC.beginAutoLogin(...args);
  const startLoginJob = (...args) => IC.startLoginJob(...args);
  const scheduleLoginPoll = (...args) => IC.scheduleLoginPoll(...args);
  const pollLogin = (...args) => IC.pollLogin(...args);
  const applyLoginSnapshot = (...args) => IC.applyLoginSnapshot(...args);
  const handleLoginFinished = (...args) => IC.handleLoginFinished(...args);
  const showLoginPrompt = (...args) => IC.showLoginPrompt(...args);
  const hideLoginOverlay = (...args) => IC.hideLoginOverlay(...args);
  const acceptVisibleLogin = (...args) => IC.acceptVisibleLogin(...args);
  const declineVisibleLogin = (...args) => IC.declineVisibleLogin(...args);
  const finalLoginFailure = (...args) => IC.finalLoginFailure(...args);
  const relogin = (...args) => IC.relogin(...args);
  const loadCourses = (...args) => IC.loadCourses(...args);
  const selectCourse = (...args) => IC.selectCourse(...args);
  const chooseDefaultType = (...args) => IC.chooseDefaultType(...args);
  const renderAll = (...args) => IC.renderAll(...args);
  const renderCourses = (...args) => IC.renderCourses(...args);
  const renderCourse = (...args) => IC.renderCourse(...args);
  const renderTypes = (...args) => IC.renderTypes(...args);
  const tasksOfKind = (...args) => IC.tasksOfKind(...args);
  const tasksOfActiveType = (...args) => IC.tasksOfActiveType(...args);
  const selectedSet = (...args) => IC.selectedSet(...args);
  const renderTaskPlaceholder = (...args) => IC.renderTaskPlaceholder(...args);
  const renderTasks = (...args) => IC.renderTasks(...args);
  const findJobTask = (...args) => IC.findJobTask(...args);
  const statusPill = (...args) => IC.statusPill(...args);
  const renderTaskStatus = (...args) => IC.renderTaskStatus(...args);
  const updateSelectionUI = (...args) => IC.updateSelectionUI(...args);
  const countChecked = (...args) => IC.countChecked(...args);
  const toggleSelectAll = (...args) => IC.toggleSelectAll(...args);
  const selectUnsolved = (...args) => IC.selectUnsolved(...args);
  const startAnswerSync = (...args) => IC.startAnswerSync(...args);
  const scheduleSyncPoll = (...args) => IC.scheduleSyncPoll(...args);
  const pollSync = (...args) => IC.pollSync(...args);
  const updateSyncUI = (...args) => IC.updateSyncUI(...args);
  const jobRunning = (...args) => IC.jobRunning(...args);
  const requestStart = (...args) => IC.requestStart(...args);
  const hideWarning = (...args) => IC.hideWarning(...args);
  const hideResult = (...args) => IC.hideResult(...args);
  const showJobResult = (...args) => IC.showJobResult(...args);
  const confirmStart = (...args) => IC.confirmStart(...args);
  const scheduleJobPoll = (...args) => IC.scheduleJobPoll(...args);
  const pollJob = (...args) => IC.pollJob(...args);
  const refreshCourseState = (...args) => IC.refreshCourseState(...args);
  const cancelJob = (...args) => IC.cancelJob(...args);
  const renderJob = (...args) => IC.renderJob(...args);
  const clearNotices = (...args) => IC.clearNotices(...args);
  const showTagNotice = (...args) => IC.showTagNotice(...args);
  const showFilledNotices = (...args) => IC.showFilledNotices(...args);
  const toggleLog = (...args) => IC.toggleLog(...args);
  const hideLog = (...args) => IC.hideLog(...args);
  const appendLog = (...args) => IC.appendLog(...args);
  const renderLogs = (...args) => IC.renderLogs(...args);

  IC.clearNotices = function () {
    if (els['i-notice-stack']) {
      els['i-notice-stack'].innerHTML = '';
    }
  };

  IC.showTagNotice = function (message) {
    const stack = els['i-notice-stack'];
    if (!stack) {
      return;
    }
    const item = node('div', 'ic-notice');
    item.appendChild(node('span', 'ic-notice-text', message));
    const close = node('button', 'ic-notice-close', '×');
    close.type = 'button';
    close.setAttribute('aria-label', '关闭提示');
    close.addEventListener('click', () => item.remove());
    item.appendChild(close);
    stack.appendChild(item);
    while (stack.children.length > 3) {
      stack.removeChild(stack.firstChild);
    }
  };

  IC.showFilledNotices = function (job) {
    if (!job || !Array.isArray(job.tasks)) {
      return;
    }
    job.tasks.forEach((task) => {
      if (task.status !== '已填写' || state.notifiedKeys.has(task.key)) {
        return;
      }
      state.notifiedKeys.add(task.key);
      // #关闭“留存数据”后不显示截图路径，避免给出不存在的文件。
      const path = task.screenshot
        || (task.result && task.result.screenshot)
        || '';
      const label = task.kind === '讨论' ? '讨论截图' : '答案截图';
      showTagNotice(
        (task.kind || '任务') + '「' + (task.title || '') + '」已填写'
        + (path ? '，' + label + '已保存至 ' + path : '。')
      );
    });
  };

  IC.toggleLog = function () {
    state.logOpen = !state.logOpen;
    if (els['i-log-panel']) {
      els['i-log-panel'].classList.toggle('hidden', !state.logOpen);
    }
    if (state.logOpen) {
      renderLogs();
    }
  };

  IC.hideLog = function () {
    state.logOpen = false;
    if (els['i-log-panel']) {
      els['i-log-panel'].classList.add('hidden');
    }
  };

  IC.appendLog = function (level, message) {
    if (!els['i-log-lines']) {
      return;
    }
    els['i-log-lines'].appendChild(node('div', 'log-line ' + level,
      '[' + new Date().toLocaleTimeString() + '] ' + message));
    els['i-log-lines'].scrollTop = els['i-log-lines'].scrollHeight;
  };

  IC.renderLogs = function () {
    const host = els['i-log-lines'];
    if (!host) {
      return;
    }
    const jobEvents = state.job && Array.isArray(state.job.events)
      ? state.job.events : [];
    const loginEvents = state.loginJob && Array.isArray(state.loginJob.events)
      ? state.loginJob.events : [];
    const events = jobEvents.length ? jobEvents : loginEvents;
    if (!events.length) {
      return;
    }
    host.innerHTML = '';
    events.slice(-120).forEach((event) => {
      host.appendChild(node('div', 'log-line ' + (event.level || 'info'),
        '[' + (event.time || '') + '] ' + (event.message || '')));
    });
    host.scrollTop = host.scrollHeight;
  };

})(window);
