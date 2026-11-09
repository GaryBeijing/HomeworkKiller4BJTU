/*
  作者: Gary
  编写日期: 2026-11-08 14:30
  最后更新: 2026-11-09 20:40
  文件名: icourse.js
  主要用途: “中国大学慕课”标签页逻辑：自动登录、课程选择、任务勾选、批量完成、进度轮询、题库同步与任务结果提醒。
  文件版本: 4.3.2
*/
(function () {
  'use strict';

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

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) {
      element.className = className;
    }
    if (text !== undefined) {
      element.textContent = text;
    }
    return element;
  }

  function cacheElements() {
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
  }

  function bindEvents() {
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
  }

  function on(element, event, handler) {
    if (element) {
      element.addEventListener(event, handler);
    }
  }

  function init(container) {
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
  }

  async function onActivate() {
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
  }

  /**
   * 通过无头浏览器校验当前登录态，不清理已选课程。
   * @returns {Promise<boolean>} 是否有效。
   */
  async function validateLogin() {
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
  }

  function onDeactivate() {
    clearTimer('jobTimer');
    clearTimer('loginTimer');
    clearTimer('syncTimer');
  }

  /**
   * 全局加载遮罩点击“取消加载”时调用：取消后台登录并回到失败态。
   * @returns {void}
   */
  function onCancelLoading() {
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
  }

  function clearTimer(name) {
    if (state[name]) {
      window.clearTimeout(state[name]);
      state[name] = null;
    }
  }

  // ------------------------------------------------------------------ 状态
  async function refreshState() {
    const data = await App.callOk('get_state');
    applyState(data);
  }

  function applyState(data) {
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
  }

  function setAccountStatus(text, kind) {
    const badge = els['i-account-badge'];
    if (!badge) {
      return;
    }
    badge.className = 'pill ' + (kind || 'info');
    badge.textContent = text;
  }

  function updateAccountBadge() {
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
  }

  function showRelogin() {
    if (els['i-relogin']) {
      els['i-relogin'].classList.remove('hidden');
    }
  }

  // ------------------------------------------------------------------ 自动登录
  function resetLoginWaiter() {
    let resolve = null;
    const promise = new Promise((done) => {
      resolve = done;
    });
    state.loginWaiter = { promise: promise, resolve: resolve };
    return state.loginWaiter;
  }

  function resolveLoginWaiter() {
    const waiter = state.loginWaiter;
    state.loginWaiter = null;
    if (waiter && typeof waiter.resolve === 'function') {
      waiter.resolve();
    }
  }

  function waitForLogin() {
    return state.loginWaiter ? state.loginWaiter.promise : Promise.resolve();
  }

  function setLoadingForLogin(visible) {
    if (App.setLoading) {
      App.setLoading(
        visible,
        '正在自动登录中国大学慕课…',
        visible ? { cancellable: true } : undefined
      );
    }
  }

  async function beginAutoLogin(showMask) {
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
  }

  async function startLoginJob(mode) {
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
  }

  function scheduleLoginPoll() {
    clearTimer('loginTimer');
    state.loginTimer = window.setTimeout(pollLogin, LOGIN_POLL_MS);
  }

  async function pollLogin() {
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
  }

  function applyLoginSnapshot(job) {
    state.loginJob = job;
    updateAccountBadge();
    if (els['i-relogin']) {
      els['i-relogin'].disabled = Boolean(job && job.running);
    }
    renderLogs();
    if (job.running && els['i-log-panel'] && els['i-log-panel'].classList.contains('hidden')) {
      // 自动登录时默认收起日志，避免遮挡任务区；用户可点“日志”查看。
    }
  }

  async function handleLoginFinished(job) {
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
  }

  function showLoginPrompt(job) {
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
  }

  function hideLoginOverlay() {
    if (els['i-login-overlay']) {
      els['i-login-overlay'].classList.add('hidden');
    }
  }

  async function acceptVisibleLogin() {
    hideLoginOverlay();
    try {
      await startLoginJob('visible');
    } catch (error) {
      finalLoginFailure(error.message);
    }
  }

  function declineVisibleLogin() {
    hideLoginOverlay();
    finalLoginFailure('你选择了暂不登录。');
  }

  function finalLoginFailure(message) {
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
  }

  async function relogin() {
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
  }

  // ------------------------------------------------------------------ 课程
  async function loadCourses(showToast) {
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
  }

  async function selectCourse(termId) {
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
  }

  function chooseDefaultType() {
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
  }

  function renderAll() {
    renderCourses();
    renderCourse();
    renderTypes();
    renderTasks();
    updateSelectionUI();
    renderJob(state.job);
    renderLogs();
  }

  function renderCourses() {
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
  }

  function renderCourse() {
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
  }

  function renderTypes() {
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
  }

  function tasksOfKind(kind) {
    if (!state.course || !state.course.course) {
      return [];
    }
    return (state.course.course.tasks || []).filter((task) => task.type === kind);
  }

  function tasksOfActiveType() {
    return tasksOfKind(state.activeType);
  }

  function selectedSet(kind) {
    if (!state.checked.has(kind)) {
      // 4.0.1：任务默认全部不选，由用户手动勾选或点“全选未完成”。
      state.checked.set(kind, new Set());
    }
    return state.checked.get(kind);
  }

  function renderTaskPlaceholder(message) {
    const body = els['i-task-body'];
    if (!body) {
      return;
    }
    body.innerHTML = '';
    const row = node('tr');
    const cell = node('td', 'table-empty', message);
    cell.colSpan = 3;
    row.appendChild(cell);
    body.appendChild(row);
  }

  function renderTasks() {
    const body = els['i-task-body'];
    if (!body) {
      return;
    }
    body.innerHTML = '';
    if (!state.course || !state.course.course) {
      renderTaskPlaceholder(state.loggedIn ? '请先选择课程' : '登录后选择课程');
      return;
    }
    const tasks = tasksOfActiveType();
    if (!tasks.length) {
      renderTaskPlaceholder('该类型下没有任务');
      return;
    }
    const checked = selectedSet(state.activeType);
    tasks.forEach((task) => {
      const row = node('tr');
      row.dataset.key = task.key;
      row.dataset.kind = task.type;

      const checkCell = node('td', 'check-col');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = checked.has(task.key);
      checkbox.disabled = task.status === 'done' || jobRunning();
      checkbox.addEventListener('change', () => {
        if (checkbox.checked) {
          checked.add(task.key);
        } else {
          checked.delete(task.key);
        }
        updateSelectionUI();
      });
      checkCell.appendChild(checkbox);
      row.appendChild(checkCell);

      const nameCell = node('td');
      nameCell.appendChild(node('span', 'ic-task-name', task.name || '—'));
      const parts = [task.type || '', task.chapter || '', task.lesson || '']
        .filter(Boolean);
      nameCell.appendChild(node('span', 'ic-task-sub', parts.join(' · ')));
      row.appendChild(nameCell);

      const statusCell = node('td');
      renderTaskStatus(statusCell, task, findJobTask(task.key));
      row.appendChild(statusCell);
      body.appendChild(row);
    });
  }

  function findJobTask(key) {
    if (!state.job || !Array.isArray(state.job.tasks)) {
      return null;
    }
    return state.job.tasks.find((item) => item.key === key) || null;
  }

  function statusPill(kind, text, title) {
    const pill = node('span', 'pill ' + kind, text);
    if (title) {
      pill.title = title;
    }
    return pill;
  }

  function renderTaskStatus(cell, task, jobTask) {
    cell.innerHTML = '';
    if (jobTask) {
      if (jobTask.status === '等待队列') {
        cell.appendChild(statusPill('queued', '等待队列'));
        return;
      }
      if (jobTask.status === '进行中') {
        const pill = node('span', 'pill progress-pill');
        const fill = node('span', 'pill-progress-fill');
        const text = node('span', 'pill-progress-text', jobTask.percent_text || '0%');
        pill.appendChild(fill);
        pill.appendChild(text);
        const shown = state.percentShown.get(task.key);
        const now = Date.now();
        const percent = Number(jobTask.percent || 0);
        if (!shown || now - shown.at >= PERCENT_INTERVAL_MS || percent >= 100) {
          state.percentShown.set(task.key, { at: now, percent: percent });
          fill.style.width = String(Math.max(0, Math.min(100, percent))) + '%';
          text.textContent = Math.round(percent) + '%';
        } else {
          fill.style.width = String(Math.max(0, Math.min(100, shown.percent))) + '%';
          text.textContent = Math.round(shown.percent) + '%';
        }
        cell.appendChild(pill);
        return;
      }
      if (jobTask.status === '完成') {
        if (jobTask.score_text) {
          const full = jobTask.full_score;
          const kind = full === false ? 'failed-pill' : 'done-pill';
          cell.appendChild(statusPill(kind, jobTask.score_text,
            full === false ? '未得满分' : '得分'));
        } else {
          cell.appendChild(statusPill('done-pill', '完成'));
        }
        return;
      }
      if (jobTask.status === '已发布') {
        cell.appendChild(statusPill('published-pill', '已发布'));
        return;
      }
      if (jobTask.status === '已填写') {
        cell.appendChild(statusPill('filled-pill', '已填写',
          jobTask.message || '已填写'));
        return;
      }
      if (jobTask.status === '失败') {
        cell.appendChild(statusPill('failed-pill', '失败', jobTask.error || ''));
        return;
      }
      if (jobTask.status === '已取消') {
        cell.appendChild(statusPill(
          'todo-pill', '已取消', jobTask.message || jobTask.error || '任务已取消'
        ));
        return;
      }
      if (jobTask.status === '已跳过') {
        cell.appendChild(statusPill('todo-pill', '已跳过', jobTask.message || ''));
        return;
      }
    }
    if (task.status === 'done') {
      cell.appendChild(statusPill('done-pill', '完成'));
    } else {
      cell.appendChild(statusPill('todo-pill',
        task.status === 'overdue' ? '未完成（已逾期）' : '未完成'));
    }
  }

  function updateSelectionUI() {
    const checked = state.checked.get(state.activeType) || new Set();
    const tasks = tasksOfActiveType();
    const selectable = tasks.filter((task) => task.status !== 'done');
    if (els['i-select-all']) {
      const checkedCount = selectable.filter((task) => checked.has(task.key)).length;
      els['i-select-all'].checked = selectable.length > 0
        && checkedCount === selectable.length;
      els['i-select-all'].indeterminate = checkedCount > 0
        && checkedCount < selectable.length;
      els['i-select-all'].disabled = jobRunning() || selectable.length === 0;
    }
    const total = countChecked();
    if (els['i-selection-hint']) {
      els['i-selection-hint'].textContent = '已选 ' + total + ' 个任务';
    }
    const running = jobRunning();
    if (els['i-start']) {
      els['i-start'].textContent = running ? '终止任务' : '开始完成';
      els['i-start'].className = running ? 'btn danger-outline' : 'btn primary';
      els['i-start'].disabled = running ? false : (total === 0 || !state.loggedIn);
    }
    if (els['i-relogin']) {
      els['i-relogin'].disabled = running
        || Boolean(state.loginJob && state.loginJob.running);
    }
  }

  function countChecked() {
    let total = 0;
    state.checked.forEach((set) => {
      total += set.size;
    });
    return total;
  }

  function toggleSelectAll() {
    const checked = selectedSet(state.activeType);
    const tasks = tasksOfActiveType().filter((task) => task.status !== 'done');
    if (els['i-select-all'] && els['i-select-all'].checked) {
      tasks.forEach((task) => checked.add(task.key));
    } else {
      tasks.forEach((task) => checked.delete(task.key));
    }
    renderTasks();
    updateSelectionUI();
  }

  function selectUnsolved() {
    selectedSet(state.activeType);
    const checked = state.checked.get(state.activeType);
    tasksOfActiveType().forEach((task) => {
      if (task.status !== 'done') {
        checked.add(task.key);
      }
    });
    renderTasks();
    updateSelectionUI();
  }

  // ------------------------------------------------------------------ 题库同步
  async function startAnswerSync() {
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
  }

  function scheduleSyncPoll() {
    clearTimer('syncTimer');
    state.syncTimer = window.setTimeout(pollSync, SYNC_POLL_MS);
  }

  async function pollSync() {
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
  }

  function updateSyncUI(sync) {
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
  }

  // ------------------------------------------------------------------ 开始完成
  function jobRunning() {
    return Boolean(state.job && state.job.running);
  }

  function requestStart() {
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
  }

  function hideWarning() {
    if (els['i-warning-modal']) {
      els['i-warning-modal'].classList.add('hidden');
    }
  }

  function hideResult() {
    if (els['i-result-modal']) {
      els['i-result-modal'].classList.add('hidden');
    }
  }

  function showJobResult(job) {
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
  }

  async function confirmStart() {
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
  }

  function scheduleJobPoll() {
    clearTimer('jobTimer');
    state.jobTimer = window.setTimeout(pollJob, POLL_MS);
  }

  async function pollJob() {
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
  }

  async function refreshCourseState() {
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
  }

  async function cancelJob() {
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
  }

  function renderJob(job) {
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
  }

  function clearNotices() {
    if (els['i-notice-stack']) {
      els['i-notice-stack'].innerHTML = '';
    }
  }

  function showTagNotice(message) {
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
  }

  function showFilledNotices(job) {
    if (!job || !Array.isArray(job.tasks)) {
      return;
    }
    job.tasks.forEach((task) => {
      if (task.status !== '已填写' || state.notifiedKeys.has(task.key)) {
        return;
      }
      state.notifiedKeys.add(task.key);
      const label = task.kind === '讨论' ? '讨论截图' : '答案截图';
      const path = task.screenshot
        || (task.result && task.result.screenshot)
        || 'artifacts/icourse/';
      showTagNotice(
        (task.kind || '任务') + '「' + (task.title || '') + '」已填写，'
        + label + '已保存至 ' + path
      );
    });
  }

  // ------------------------------------------------------------------ 日志
  function toggleLog() {
    state.logOpen = !state.logOpen;
    if (els['i-log-panel']) {
      els['i-log-panel'].classList.toggle('hidden', !state.logOpen);
    }
    if (state.logOpen) {
      renderLogs();
    }
  }

  function hideLog() {
    state.logOpen = false;
    if (els['i-log-panel']) {
      els['i-log-panel'].classList.add('hidden');
    }
  }

  function appendLog(level, message) {
    if (!els['i-log-lines']) {
      return;
    }
    els['i-log-lines'].appendChild(node('div', 'log-line ' + level,
      '[' + new Date().toLocaleTimeString() + '] ' + message));
    els['i-log-lines'].scrollTop = els['i-log-lines'].scrollHeight;
  }

  function renderLogs() {
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
  }

  App.registerPage(PAGE_NAME, {
    init: init,
    onActivate: onActivate,
    onDeactivate: onDeactivate,
    onCancelLoading: onCancelLoading,
  });
})();
