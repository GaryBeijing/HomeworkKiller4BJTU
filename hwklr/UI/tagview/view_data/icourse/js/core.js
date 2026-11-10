/*
  作者: Gary
  编写日期: 2026-11-08 14:30
  最后更新: 2026-11-10 23:40
  文件名: core.js
  主要用途: “中国大学慕课”页面共享状态、DOM 缓存、事件绑定与加载/取消入口。
  文件版本: 4.4.1
*/
(function (global) {
  'use strict';
  const IC = global.Icourse = global.Icourse || {};

  const PAGE_NAME = '中国大学慕课';
  const POLL_MS = 800;
  const LOGIN_POLL_MS = 1000;
  const SYNC_POLL_MS = 1200;
  const PERCENT_INTERVAL_MS = 3000;

  const state = {
    initialized: false,
    loggedIn: false,
    user: {},
    courses: [],
    course: null,
    types: [],
    activeType: '',
    checked: new Map(),
    jobId: '',
    job: null,
    jobTimer: null,
    loginJobId: '',
    loginJob: null,
    loginWaiter: null,
    loginTimer: null,
    syncTimer: null,
    percentShown: new Map(),
    settings: {},
    loginBlocked: false,
    autoTried: false,
    logOpen: false,
    notifiedKeys: new Set(),
    resultShownJobId: '',
    keydownHandler: null,
  };

  const els = {};

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

  IC.node = function (tag, className, text) {
    const element = document.createElement(tag);
    if (className) {
      element.className = className;
    }
    if (text !== undefined) {
      element.textContent = text;
    }
    return element;
  };

  IC.on = function (element, event, handler) {
    if (element) {
      element.addEventListener(event, handler);
    }
  };

  IC.clearTimer = function (name) {
    if (state[name]) {
      window.clearTimeout(state[name]);
      state[name] = null;
    }
  };

  IC.cacheElements = function () {
    [
      'i-account-badge', 'i-relogin', 'i-open-settings', 'i-refresh-courses',
      'i-notice-stack',
      'i-course-list', 'i-sync-message', 'i-sync-answers', 'i-sync-bar',
      'i-course-title', 'i-course-meta', 'i-log-toggle', 'i-type-rail',
      'i-task-body', 'i-select-all', 'i-select-unsolved', 'i-selection-hint',
      'i-start', 'i-job-inline', 'i-job-phase', 'i-job-message', 'i-job-bar',
      'i-log-panel', 'i-log-lines', 'i-login-overlay',
      'i-login-overlay-text', 'i-login-decline', 'i-login-visible',
      'i-warning-modal', 'i-warning-detail', 'i-warning-cancel',
      'i-warning-confirm', 'i-result-modal', 'i-result-title',
      'i-result-summary', 'i-result-bank', 'i-result-list', 'i-result-close',
    ].forEach((id) => {
      els[id] = document.getElementById(id);
    });
  };

  IC.bindEvents = function () {
    on(els['i-refresh-courses'], 'click', () => loadCourses(true));
    on(els['i-relogin'], 'click', relogin);
    on(els['i-open-settings'], 'click', (event) => {
      event.preventDefault();
      if (App.openSettings) {
        App.openSettings('icourse');
      }
    });
    on(els['i-sync-answers'], 'click', startAnswerSync);
    on(els['i-log-toggle'], 'click', toggleLog);
    on(els['i-select-all'], 'change', toggleSelectAll);
    on(els['i-select-unsolved'], 'click', selectUnsolved);
    on(els['i-start'], 'click', () => {
      if (jobRunning()) {
        cancelJob();
      } else {
        requestStart();
      }
    });
    on(els['i-login-visible'], 'click', acceptVisibleLogin);
    on(els['i-login-decline'], 'click', declineVisibleLogin);
    on(els['i-warning-cancel'], 'click', hideWarning);
    on(els['i-warning-confirm'], 'click', confirmStart);
    if (els['i-warning-modal']) {
      els['i-warning-modal'].addEventListener('click', (event) => {
        if (event.target === els['i-warning-modal']) {
          hideWarning();
        }
      });
    }
    on(els['i-result-close'], 'click', hideResult);
    if (els['i-result-modal']) {
      els['i-result-modal'].addEventListener('click', (event) => {
        if (event.target === els['i-result-modal']) {
          hideResult();
        }
      });
    }
  };

  IC.init = function (container) {
    cacheElements();
    bindEvents();
    hideWarning();
    hideLoginOverlay();
    hideLog();
    if (state.keydownHandler) {
      document.removeEventListener('keydown', state.keydownHandler);
    }
    state.keydownHandler = (event) => {
      if (event.key === 'Escape') {
        hideWarning();
      }
    };
    document.addEventListener('keydown', state.keydownHandler);
    state.initialized = true;
  };

  IC.onDeactivate = function () {
    clearTimer('jobTimer');
    clearTimer('loginTimer');
    clearTimer('syncTimer');
  };

  IC.onCancelLoading = function () {
    if (state.loginJob && state.loginJob.running && state.loginJobId) {
      App.call('cancel_login_job', { job_id: state.loginJobId }).catch(() => {});
    }
    state.loginJob = state.loginJob || {};
    state.loginJob.running = false;
    state.loggedIn = false;
    state.loginBlocked = true;
    hideLoginOverlay();
    showRelogin(true);
    setAccountStatus('登录失败', 'bad');
    renderAll();
    resolveLoginWaiter();
  };

  IC.PAGE_NAME = PAGE_NAME;
  IC.POLL_MS = POLL_MS;
  IC.LOGIN_POLL_MS = LOGIN_POLL_MS;
  IC.SYNC_POLL_MS = SYNC_POLL_MS;
  IC.PERCENT_INTERVAL_MS = PERCENT_INTERVAL_MS;
  IC.state = state;
  IC.els = els;

})(window);
