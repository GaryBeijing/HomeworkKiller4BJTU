/*
  作者: Gary
  编写日期: 2026-11-08 14:30
  最后更新: 2026-11-10 23:40
  文件名: courses.js
  主要用途: “中国大学慕课”页面课程列表、任务类型、任务表格与勾选状态渲染。
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

  IC.refreshState = async function () {
    const data = await App.callOk('get_state');
    applyState(data);
  };

  IC.applyState = function (data) {
    state.loggedIn = Boolean(data.logged_in);
    state.user = data.user || {};
    state.courses = data.courses || [];
    state.settings = data.settings || {};
    if (data.course && data.course.course) {
      state.course = data.course;
      state.types = data.course.types || [];
    }
    if (data.login_job && data.login_job.job_id) {
      state.loginJob = data.login_job;
      if (data.login_job.running) {
        state.loginJobId = data.login_job.job_id;
      }
    }
    if (data.job && data.job.job_id) {
      state.job = data.job;
      state.jobId = data.job.job_id;
    }
    if (state.loginJob) {
      applyLoginSnapshot(state.loginJob);
    } else {
      updateAccountBadge();
    }
    updateSyncUI(data.answer_sync || ((state.course || {}).answer_sync));
    renderAll();
    if (state.loginJob && state.loginJob.phase === 'need_visible'
        && !state.loginBlocked && !state.loggedIn) {
      showLoginPrompt(state.loginJob);
    }
  };

  IC.loadCourses = async function (showToast) {
    if (!state.loggedIn) {
      return;
    }
    if (els['i-course-list']) {
      els['i-course-list'].innerHTML = '';
      els['i-course-list'].appendChild(node('p', 'muted', '正在读取课程…'));
    }
    try {
      const data = await App.callOk('load_courses');
      state.courses = data.courses || [];
      state.user = data.user || state.user;
      updateAccountBadge();
      renderCourses();
      if (showToast) {
        App.toast('课程列表已刷新', 'success');
      }
    } catch (error) {
      appendLog('error', '获取课程失败：' + error.message);
      if (!state.autoTried) {
        state.loggedIn = false;
        await beginAutoLogin();
      } else {
        finalLoginFailure('获取课程失败：' + error.message);
      }
    }
  };

  IC.selectCourse = async function (termId) {
    if (jobRunning()) {
      App.toast('任务运行中，暂不能切换课程', 'warn');
      return;
    }
    renderTaskPlaceholder('正在读取课程任务…');
    try {
      const data = await App.callOk('select_course', { term_id: Number(termId) });
      state.course = data;
      state.types = data.types || [];
      state.checked = new Map();
      state.job = null;
      state.jobId = '';
      state.percentShown = new Map();
      state.notifiedKeys = new Set();
      clearNotices();
      state.activeType = chooseDefaultType();
      renderAll();
      if ((data.answer_sync || {}).running) {
        scheduleSyncPoll();
      }
    } catch (error) {
      renderTaskPlaceholder('读取课程任务失败');
      App.toast('读取课程任务失败：' + error.message, 'error');
    }
  };

  IC.chooseDefaultType = function () {
    const types = state.types || [];
    if (!types.length) {
      return '';
    }
    const preferred = types.find((item) => item.kind === '视频' && item.pending > 0);
    if (preferred) {
      return preferred.kind;
    }
    const pending = types.find((item) => item.pending > 0);
    return (pending || types[0]).kind;
  };

  IC.renderAll = function () {
    renderCourses();
    renderCourse();
    renderTypes();
    renderTasks();
    updateSelectionUI();
    renderJob(state.job);
    renderLogs();
  };

  IC.renderCourses = function () {
    const host = els['i-course-list'];
    if (!host) {
      return;
    }
    host.innerHTML = '';
    if (!state.loggedIn) {
      host.appendChild(node('p', 'muted', '登录后可选择课程。'));
      return;
    }
    if (!state.courses.length) {
      host.appendChild(node('p', 'muted', '暂无课程，点击“刷新”。'));
      return;
    }
    state.courses.forEach((course) => {
      const button = node('button', 'course-item');
      button.type = 'button';
      button.dataset.termId = String(course.term_id);
      const title = node('span', '', course.name || ('课程 ' + course.term_id));
      const pending = Number((course.summary || {}).pending || 0);
      const sub = node('span', 'course-sub',
        (course.school || '') + (course.is_spoc ? ' · SPOC' : ' · MOOC')
        + (pending ? ' · 待办 ' + pending : ''));
      button.appendChild(title);
      button.appendChild(sub);
      if (state.course && state.course.course
          && Number(state.course.course.term_id) === Number(course.term_id)) {
        button.classList.add('active');
      }
      button.addEventListener('click', () => selectCourse(course.term_id));
      host.appendChild(button);
    });
  };

  IC.renderCourse = function () {
    if (!els['i-course-title'] || !els['i-course-meta']) {
      return;
    }
    if (!state.course || !state.course.course) {
      els['i-course-title'].textContent = '任务';
      els['i-course-meta'].textContent = '';
      return;
    }
    const course = state.course.course;
    els['i-course-title'].textContent = course.name || '任务';
    const catalog = state.course.catalog || {};
    els['i-course-meta'].textContent = [
      course.school || '',
      course.is_spoc ? 'SPOC' : 'MOOC',
      catalog.available ? '题库已收录' : '题库未收录',
    ].filter(Boolean).join(' · ');
  };

  IC.renderTypes = function () {
    const host = els['i-type-rail'];
    if (!host) {
      return;
    }
    host.innerHTML = '';
    const types = state.types || [];
    if (!types.length) {
      host.appendChild(node('p', 'muted', '暂无'));
      return;
    }
    types.forEach((item) => {
      const button = node('button', 'ic-type-item');
      button.type = 'button';
      button.dataset.kind = item.kind;
      button.appendChild(node('span', '', item.kind));
      button.appendChild(node('span', 'ic-type-count',
        String(item.pending) + '/' + String(item.total)));
      if (item.kind === state.activeType) {
        button.classList.add('active');
      }
      button.addEventListener('click', () => {
        state.activeType = item.kind;
        renderTypes();
        renderTasks();
        updateSelectionUI();
      });
      host.appendChild(button);
    });
  };

})(window);