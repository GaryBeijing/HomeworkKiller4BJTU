/*
  作者: Gary
  编写日期: 2026-11-08 14:30
  最后更新: 2026-11-10 23:40
  文件名: job.js
  主要用途: “中国大学慕课”页面完成任务启动、轮询、取消与结果弹窗。
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

  IC.jobRunning = function () {
    return Boolean(state.job && state.job.running);
  };

  IC.requestStart = function () {
    const keys = [];
    state.checked.forEach((set) => {
      set.forEach((key) => keys.push(key));
    });
    if (!keys.length) {
      App.toast('请先选择任务', 'warn');
      return;
    }
    if (els['i-warning-detail']) {
      const settings = state.settings || {};
      els['i-warning-detail'].textContent =
        '将处理 ' + keys.length + ' 个任务；最大并行数 '
        + (settings.workers || 1) + '；自动提交测验：'
        + (settings.submit_quizzes ? '开' : '关') + '；自动发布讨论：'
        + (settings.publish_discussions ? '开' : '关') + '。';
    }
    if (els['i-warning-modal']) {
      els['i-warning-modal'].classList.remove('hidden');
    }
  };

  IC.hideWarning = function () {
    if (els['i-warning-modal']) {
      els['i-warning-modal'].classList.add('hidden');
    }
  };

  IC.hideResult = function () {
    if (els['i-result-modal']) {
      els['i-result-modal'].classList.add('hidden');
    }
  };

  IC.showJobResult = function (job) {
    if (!job || job.cancelled || !job.job_id
      || state.resultShownJobId === job.job_id) {
      return;
    }
    const tasks = Array.isArray(job.tasks) ? job.tasks : [];
    const quizKinds = new Set(['测验', '随堂测验', '作业', '考试']);
    const skippedQuizzes = tasks.filter(
      (task) => task.status === '已跳过' && quizKinds.has(task.kind)
    );
    if (!skippedQuizzes.length) {
      return;
    }
    state.resultShownJobId = job.job_id;
    const result = job.result || {};
    const courseName = (state.course && state.course.course
      && state.course.course.name) || job.course_name || '当前课程';
    if (els['i-result-title']) {
      els['i-result-title'].textContent = '部分测验未能自动完成';
    }
    if (els['i-result-summary']) {
      els['i-result-summary'].textContent =
        '课程「' + courseName + '」任务结束：完成 '
        + (result.done || 0) + '，失败 ' + (result.failed || 0)
        + '，跳过 ' + (result.skipped || 0) + '。';
    }
    if (els['i-result-bank']) {
      const reasons = skippedQuizzes.map(
        (task) => task.message || task.error || ''
      );
      let bankText = '';
      if (reasons.some((text) => /题库未收录|系统异常/.test(text))) {
        bankText = '该课程未被 GinsMooc 题库收录（或题库查询失败），'
          + '测验无法自动作答。题库收录后可重新运行；也可以手动完成测验。';
      } else if (reasons.some((text) => /没有测验 id|testId/i.test(text))) {
        bankText = '部分测验单元没有 testId，无法定位测验页面，'
          + '因此无法自动作答。';
      } else if (reasons.some((text) => /SPOC/i.test(text))) {
        bankText = 'SPOC 课程暂不支持自动刷题。';
      }
      els['i-result-bank'].textContent = bankText;
      els['i-result-bank'].classList.toggle('hidden', !bankText);
    }
    if (els['i-result-list']) {
      els['i-result-list'].innerHTML = '';
      skippedQuizzes.forEach((task) => {
        const item = node('li');
        item.appendChild(node(
          'strong', '', (task.kind || '测验') + '「' + (task.title || '') + '」'
        ));
        item.appendChild(node(
          'span', 'result-reason', task.message || task.error || '题库未收录'
        ));
        els['i-result-list'].appendChild(item);
      });
    }
    if (els['i-result-modal']) {
      els['i-result-modal'].classList.remove('hidden');
    }
  };

  IC.confirmStart = async function () {
    hideWarning();
    const keys = [];
    state.checked.forEach((set) => {
      set.forEach((key) => keys.push(key));
    });
    const course = state.course && state.course.course;
    if (!course || !keys.length) {
      return;
    }
    if (els['i-start']) {
      els['i-start'].disabled = true;
    }
    App.toast('正在校验登录状态并启动任务…', 'info');
    try {
      const data = await App.callOk('start_completion_job', {
        term_id: Number(course.term_id),
        task_keys: keys,
      });
      state.jobId = data.job_id;
      state.job = data;
      state.percentShown = new Map();
      state.notifiedKeys = new Set();
      state.resultShownJobId = '';
      hideResult();
      clearNotices();
      renderJob(data);
      renderTasks();
      updateSelectionUI();
      scheduleJobPoll();
    } catch (error) {
      if (/登录|Cookie|会话/i.test(error.message)) {
        state.loggedIn = false;
        state.loginBlocked = false;
        state.user = {};
        showRelogin(false);
        setAccountStatus('登录失效，正在重新登录…', 'warn');
        renderAll();
        await beginAutoLogin(false);
      } else {
        App.toast(error.message, 'error');
      }
    } finally {
      updateSelectionUI();
    }
  };

  IC.scheduleJobPoll = function () {
    clearTimer('jobTimer');
    state.jobTimer = window.setTimeout(pollJob, POLL_MS);
  };

  IC.pollJob = async function () {
    clearTimer('jobTimer');
    if (App.active !== PAGE_NAME) {
      return;
    }
    try {
      const data = await App.callOk('get_completion_job', { job_id: state.jobId });
      state.job = data;
      renderJob(data);
      renderTasks();
      updateSelectionUI();
      if (data.running) {
        scheduleJobPoll();
      } else if (data.done) {
        const result = data.result || {};
        App.toast('任务结束：完成 ' + (result.done || 0) + '，失败 '
          + (result.failed || 0) + '，跳过 ' + (result.skipped || 0), 'info');
        await refreshCourseState();
        showJobResult(data);
      }
    } catch (error) {
      App.toast('读取任务状态失败：' + error.message, 'error');
    }
  };

  IC.refreshCourseState = async function () {
    try {
      const data = await App.callOk('get_course');
      state.course = data;
      state.types = data.types || [];
      state.checked = new Map();
      state.percentShown = new Map();
      renderAll();
    } catch (error) {
      // 刷新失败保留当前视图。
    }
  };

  IC.cancelJob = async function () {
    if (els['i-start']) {
      els['i-start'].disabled = true;
    }
    try {
      await App.callOk('cancel_completion_job', { job_id: state.jobId });
      App.toast('已请求取消任务', 'warn');
    } catch (error) {
      App.toast(error.message, 'error');
      updateSelectionUI();
    }
  };

  IC.renderJob = function (job) {
    const inline = els['i-job-inline'];
    if (!inline) {
      return;
    }
    if (!job || !job.job_id) {
      inline.classList.add('hidden');
      return;
    }
    inline.classList.remove('hidden');
    if (els['i-job-phase']) {
      const labels = {
        idle: '准备中', starting: '准备中', login: '登录', db: '题库',
        video: '刷课', document: '刷文档', quiz: '刷题', discussion: '讨论',
        serial: '处理中', verifying: '刷新状态', done: '完成',
        error: '失败', cancelled: '已取消',
      };
      els['i-job-phase'].textContent = labels[job.phase] || job.phase || '处理中';
      els['i-job-phase'].className = 'pill '
        + (job.phase === 'error' ? 'failed-pill'
          : (job.phase === 'done' ? 'done-pill'
            : (job.phase === 'cancelled' ? 'todo-pill' : 'info')));
    }
    if (els['i-job-message']) {
      els['i-job-message'].textContent = job.message || '';
      els['i-job-message'].title = job.error || job.message || '';
    }
    if (els['i-job-bar']) {
      const total = Number(job.total || 0);
      const current = Number(job.current || 0);
      els['i-job-bar'].style.width = String(
        total > 0 ? Math.min(100, current * 100 / total) : 0
      ) + '%';
    }
    showFilledNotices(job);
  };

})(window);
