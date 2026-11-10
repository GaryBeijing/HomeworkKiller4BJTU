/*
  作者: Gary
  编写日期: 2026-11-08 14:30
  最后更新: 2026-11-10 23:40
  文件名: login.js
  主要用途: “中国大学慕课”页面自动登录、登录轮询与登录状态展示。
  文件版本: 4.4.1
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

  IC.setAccountStatus = function (text, kind) {
    const badge = els['i-account-badge'];
    if (!badge) {
      return;
    }
    badge.className = 'pill ' + (kind || 'info');
    badge.textContent = text;
  };

  IC.updateAccountBadge = function () {
    const job = state.loginJob;
    if (job && job.running) {
      setAccountStatus(
        job.phase === 'browser' ? '等待浏览器登录…' : '正在自动登录…',
        'info'
      );
      return;
    }
    if (job && job.phase === 'need_visible') {
      setAccountStatus('需要登录', 'warn');
      return;
    }
    if (state.loginBlocked) {
      setAccountStatus('登录失败', 'bad');
      return;
    }
    if (state.loggedIn) {
      const user = state.user || {};
      const label = user.nickName || user.nickname || user.realName
        || user.email || user.loginId || user.id || '当前账号';
      setAccountStatus('已登录：' + String(label), 'ok');
      return;
    }
    setAccountStatus('未登录', 'info');
  };

  IC.showRelogin = function () {
    if (els['i-relogin']) {
      els['i-relogin'].classList.remove('hidden');
    }
  };

  IC.resetLoginWaiter = function () {
    let resolve = null;
    const promise = new Promise((done) => {
      resolve = done;
    });
    state.loginWaiter = { promise: promise, resolve: resolve };
    return state.loginWaiter;
  };

  IC.resolveLoginWaiter = function () {
    const waiter = state.loginWaiter;
    state.loginWaiter = null;
    if (waiter && typeof waiter.resolve === 'function') {
      waiter.resolve();
    }
  };

  IC.waitForLogin = function () {
    return state.loginWaiter ? state.loginWaiter.promise : Promise.resolve();
  };

  IC.setLoadingForLogin = function (visible) {
    if (App.setLoading) {
      App.setLoading(
        visible,
        '正在自动登录中国大学慕课…',
        visible ? { cancellable: true } : undefined
      );
    }
  };

  IC.beginAutoLogin = async function (showMask) {
    if (state.loginBlocked || (state.loginJob && state.loginJob.running)) {
      return;
    }
    state.autoTried = true;
    hideLoginOverlay();
    showRelogin(false);
    setAccountStatus('正在自动登录…', 'info');
    if (showMask) {
      setLoadingForLogin(true);
    }
    try {
      await startLoginJob('auto');
      await waitForLogin();
    } catch (error) {
      if (!state.loginBlocked) {
        finalLoginFailure(error.message);
      }
    } finally {
      if (showMask) {
        setLoadingForLogin(false);
      }
    }
  };

  IC.startLoginJob = async function (mode) {
    resetLoginWaiter();
    let data;
    try {
      data = await App.callOk('start_login_job', { mode: mode, browser: 'auto' });
    } catch (error) {
      resolveLoginWaiter();
      throw error;
    }
    state.loginJobId = data.job_id;
    // 如果用户在请求返回前已点击“取消加载”，立即取消刚创建的任务。
    if (state.loginBlocked) {
      App.call('cancel_login_job', { job_id: data.job_id }).catch(() => {});
      resolveLoginWaiter();
      return;
    }
    state.loginJob = {
      job_id: data.job_id,
      running: true,
      done: false,
      phase: 'starting',
      message: mode === 'visible' ? '正在打开浏览器…' : '正在自动登录…',
      events: [],
      error: '',
      user: {},
    };
    applyLoginSnapshot(state.loginJob);
    scheduleLoginPoll();
  };

  IC.scheduleLoginPoll = function () {
    clearTimer('loginTimer');
    state.loginTimer = window.setTimeout(pollLogin, LOGIN_POLL_MS);
  };

  IC.pollLogin = async function () {
    clearTimer('loginTimer');
    if (App.active !== PAGE_NAME) {
      return;
    }
    try {
      const data = await App.callOk('get_login_job', { job_id: state.loginJobId });
      state.loginJob = data;
      applyLoginSnapshot(data);
      if (data.running) {
        scheduleLoginPoll();
      } else {
        handleLoginFinished(data);
      }
    } catch (error) {
      finalLoginFailure('读取登录状态失败：' + error.message);
    }
  };

  IC.applyLoginSnapshot = function (job) {
    state.loginJob = job;
    updateAccountBadge();
    if (els['i-relogin']) {
      els['i-relogin'].disabled = Boolean(job && job.running);
    }
    renderLogs();
    if (job.running && els['i-log-panel'] && els['i-log-panel'].classList.contains('hidden')) {
      // 自动登录时默认收起日志，避免遮挡任务区；用户可点“日志”查看。
    }
  };

  IC.handleLoginFinished = async function (job) {
    if (job.phase === 'need_visible') {
      state.loggedIn = false;
      showLoginPrompt(job);
      resolveLoginWaiter();
      return;
    }
    if (job.done && !job.error && !job.cancelled) {
      state.loggedIn = true;
      state.loginBlocked = false;
      state.user = job.user || state.user || {};
      hideLoginOverlay();
      showRelogin(false);
      updateAccountBadge();
      await refreshState();
      await loadCourses(false);
      renderAll();
      resolveLoginWaiter();
      return;
    }
    finalLoginFailure(job.error || '登录失败');
  };

  IC.showLoginPrompt = function (job) {
    if (state.loginBlocked) {
      return;
    }
    const text = els['i-login-overlay-text'];
    if (text) {
      const events = Array.isArray(job.events) ? job.events : [];
      const reason = (job.error || job.message || (events.length
        ? events[events.length - 1].message : '')).trim();
      text.textContent = '自动登录失败' + (reason ? '（' + reason + '）' : '')
        + '。是否在弹出的浏览器窗口中完成登录？';
    }
    showRelogin(false);
    setAccountStatus('需要登录', 'warn');
    if (els['i-login-overlay']) {
      els['i-login-overlay'].classList.remove('hidden');
    }
  };

  IC.hideLoginOverlay = function () {
    if (els['i-login-overlay']) {
      els['i-login-overlay'].classList.add('hidden');
    }
  };

  IC.acceptVisibleLogin = async function () {
    hideLoginOverlay();
    try {
      await startLoginJob('visible');
    } catch (error) {
      finalLoginFailure(error.message);
    }
  };

  IC.declineVisibleLogin = function () {
    hideLoginOverlay();
    finalLoginFailure('你选择了暂不登录。');
  };

  IC.finalLoginFailure = function (message) {
    state.loggedIn = false;
    state.loginBlocked = true;
    state.loginJob = state.loginJob || {};
    state.loginJob.running = false;
    hideLoginOverlay();
    showRelogin(true);
    setAccountStatus('登录失败', 'bad');
    if (els['i-log-lines']) {
      els['i-log-lines'].appendChild(node('div', 'log-line error',
        '[' + new Date().toLocaleTimeString() + '] ' + message));
    }
    App.toast(message, 'error');
    renderAll();
    resolveLoginWaiter();
  };

  IC.relogin = async function () {
    if (jobRunning()) {
      App.toast('任务运行中，暂不能刷新登录状态', 'warn');
      return;
    }
    state.loginBlocked = false;
    state.autoTried = false;
    showRelogin();
    setAccountStatus('正在刷新登录状态…', 'info');
    const valid = await validateLogin();
    if (valid) {
      App.toast('登录状态有效', 'success');
      renderAll();
      return;
    }
    await beginAutoLogin(false);
  };

  IC.validateLogin = async function () {
    try {
      const data = await App.callOk('validate_login');
      state.loggedIn = Boolean(data.logged_in);
      state.user = data.user || {};
      updateAccountBadge();
      if (!state.loggedIn && data.reason) {
        appendLog('warn', '登录态校验失败：' + data.reason);
      }
      return state.loggedIn;
    } catch (error) {
      state.loggedIn = false;
      appendLog('warn', '登录态校验失败：' + error.message);
      return false;
    }
  };

})(window);
