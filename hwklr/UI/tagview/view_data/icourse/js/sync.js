/*
  作者: Gary
  编写日期: 2026-11-08 14:30
  最后更新: 2026-11-10 23:40
  文件名: sync.js
  主要用途: “中国大学慕课”页面题库同步进度。
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

  IC.startAnswerSync = async function () {
    const course = state.course && state.course.course;
    if (!course) {
      App.toast('请先选择课程', 'warn');
      return;
    }
    try {
      const data = await App.callOk('start_answer_sync', {
        term_id: Number(course.term_id),
        force: false,
      });
      updateSyncUI(data.sync || {});
      scheduleSyncPoll();
    } catch (error) {
      App.toast(error.message, 'error');
    }
  };

  IC.scheduleSyncPoll = function () {
    clearTimer('syncTimer');
    state.syncTimer = window.setTimeout(pollSync, SYNC_POLL_MS);
  };

  IC.pollSync = async function () {
    clearTimer('syncTimer');
    if (App.active !== PAGE_NAME) {
      return;
    }
    try {
      const data = await App.callOk('get_answer_sync');
      updateSyncUI(data);
      if (data.running) {
        scheduleSyncPoll();
      }
    } catch (error) {
      // 同步状态失败不打断主流程。
    }
  };

  IC.updateSyncUI = function (sync) {
    if (!sync) {
      return;
    }
    const message = els['i-sync-message'];
    const bar = els['i-sync-bar'];
    if (message) {
      if (sync.running) {
        message.textContent = '题库同步 ' + (sync.current || 0) + '/' + (sync.total || 0);
      } else if (sync.error) {
        message.textContent = '同步失败';
        message.title = sync.error;
      } else if (sync.done) {
        message.textContent = '同步完成 ' + (sync.cached || 0) + ' 项';
      } else {
        message.textContent = state.course ? '可同步当前课程题库' : '题库同步';
      }
    }
    if (bar) {
      const total = Number(sync.total || 0);
      const current = Number(sync.current || 0);
      bar.style.width = String(total > 0 ? Math.min(100, current * 100 / total) : 0) + '%';
    }
  };

})(window);
