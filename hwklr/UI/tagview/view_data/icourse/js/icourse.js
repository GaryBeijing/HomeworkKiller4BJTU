/*
  作者: Gary
  编写日期: 2026-11-08 14:30
  最后更新: 2026-11-10 23:40
  文件名: icourse.js
  主要用途: “中国大学慕课”页面激活入口与 App.registerPage 注册。
  文件版本: 4.4.1
*/
(function (global) {
  'use strict';
  const IC = global.Icourse = global.Icourse || {};

  const state = IC.state;
  const onActivate = (...args) => IC.onActivate(...args);
  const init = (...args) => IC.init(...args);
  const onDeactivate = (...args) => IC.onDeactivate(...args);
  const onCancelLoading = (...args) => IC.onCancelLoading(...args);
  const validateLogin = (...args) => IC.validateLogin(...args);
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

  IC.onActivate = async function () {
    if (!state.initialized) {
      return;
    }
    state.autoTried = false;
    try {
      await refreshState();
    } catch (error) {
      App.toast('读取慕课状态失败：' + error.message, 'error');
    }
    if (state.job && state.job.running) {
      scheduleJobPoll();
      renderAll();
      return;
    }
    if (state.job && state.job.done) {
      showJobResult(state.job);
    }
    if (state.loginJob && state.loginJob.running) {
      scheduleLoginPoll();
      setLoadingForLogin(true);
      await waitForLogin();
      setLoadingForLogin(false);
      if (state.loggedIn && !state.courses.length) {
        await loadCourses(false);
      }
      return;
    }
    if (state.loginBlocked) {
      showRelogin();
      setAccountStatus('登录失败', 'bad');
      renderAll();
      return;
    }
    // 4.2.0：标签激活时校验登录态，而不是点击“开始完成”时。
    const valid = await validateLogin();
    if (valid) {
      if (!state.courses.length) {
        await loadCourses(false);
      } else {
        renderAll();
      }
      return;
    }
    state.loggedIn = false;
    await beginAutoLogin(true);
    if (state.loggedIn && !state.courses.length) {
      await loadCourses(false);
    }
  };

  App.registerPage(IC.PAGE_NAME, {
    init: IC.init,
    onActivate: IC.onActivate,
    onDeactivate: IC.onDeactivate,
    onCancelLoading: IC.onCancelLoading,
  });

})(window);
