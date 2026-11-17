/*
  作者: Gary
  编写日期: 2026-11-08 14:30
  最后更新: 2026-11-10 23:40
  文件名: tasks.js
  主要用途: “中国大学慕课”页面任务表格、状态胶囊、勾选与全选逻辑。
  文件版本: 4.4.1
*/
(function (global) {
  'use strict';
  const IC = global.Icourse = global.Icourse || {};

  const PAGE_NAME = IC.PAGE_NAME;
  const POLL_MS = IC.POLL_MS;
  const LOGIN_POLL_MS = IC.LOGIN_POLL_MS;
  const SYNC_POLL_MS = IC.SYNC_POLL_MS;
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

  IC.tasksOfKind = function (kind) {
    if (!state.course || !state.course.course) {
      return [];
    }
    return (state.course.course.tasks || []).filter((task) => task.type === kind);
  };

  IC.tasksOfActiveType = function () {
    return tasksOfKind(state.activeType);
  };

  IC.selectedSet = function (kind) {
    if (!state.checked.has(kind)) {
      // 4.0.1：任务默认全部不选，由用户手动勾选或点“全选未完成”。
      state.checked.set(kind, new Set());
    }
    return state.checked.get(kind);
  };

  IC.renderTaskPlaceholder = function (message) {
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
  };

  function selectableTask(task) {
    if (task.status !== 'done') {
      return true;
    }
    return task.type === '作业'
      && Boolean((state.settings || {}).auto_peer_review);
  }

  IC.renderTasks = function () {
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
      checkbox.disabled = !selectableTask(task) || jobRunning();
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
  };

  IC.findJobTask = function (key) {
    if (!state.job || !Array.isArray(state.job.tasks)) {
      return null;
    }
    return state.job.tasks.find((item) => item.key === key) || null;
  };

  IC.statusPill = function (kind, text, title) {
    const pill = node('span', 'pill ' + kind, text);
    if (title) {
      pill.title = title;
    }
    return pill;
  };

  IC.statusIcon = function (type, options) {
    const opts = options || {};
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', opts.label || '');
    svg.classList.add('ic-status-icon', 'ic-status-icon--' + type);

    const add = (tag, attrs) => {
      const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
      Object.keys(attrs || {}).forEach((key) => el.setAttribute(key, attrs[key]));
      svg.appendChild(el);
      return el;
    };
    if (type === 'timed') {
      add('circle', { cx: '12', cy: '13', r: '7' });
      add('path', { d: 'M12 13V9' });
      add('path', { d: 'M12 13L15 15' });
      add('path', { d: 'M9 3H15' });
      add('path', { d: 'M12 3V6' });
    } else if (type === 'attempts') {
      add('circle', { cx: '12', cy: '12', r: '8.5' });
      add('text', {
        x: '12', y: '12.5', 'text-anchor': 'middle',
        'dominant-baseline': 'middle', 'font-size': '10',
        'font-weight': '600', stroke: 'none', fill: 'currentColor',
      }).textContent = String(opts.count == null ? '' : opts.count);
    } else {
      add('circle', { cx: '12', cy: '12', r: '8.5' });
      add('path', { d: 'M8.5 8.5L15.5 15.5' });
      add('path', { d: 'M15.5 8.5L8.5 15.5' });
    }
    const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
    title.textContent = opts.label || '';
    svg.appendChild(title);
    return svg;
  };

  function taskIcons(task) {
    const icons = [];
    if (task.attempts_exhausted) {
      icons.push(IC.statusIcon('exhausted', { label: '测验次数已用完' }));
    } else if (task.attempts_remaining !== null
        && task.attempts_remaining !== undefined) {
      const total = task.attempt_limit != null
        ? '（共 ' + task.attempt_limit + ' 次）' : '';
      icons.push(IC.statusIcon('attempts', {
        count: task.attempts_remaining,
        label: '剩余 ' + task.attempts_remaining + ' 次' + total,
      }));
    }
    if (task.time_limited) {
      icons.push(IC.statusIcon('timed', { label: '限时测验' }));
    }
    return icons;
  }

  IC.renderTaskStatus = function (cell, task, jobTask) {
    cell.innerHTML = '';
    const wrap = node('span', 'ic-status-wrap');
    const finish = (pill) => {
      taskIcons(task).forEach((icon) => wrap.appendChild(icon));
      if (pill) {
        wrap.appendChild(pill);
      }
      cell.appendChild(wrap);
    };
    if (jobTask) {
      if (jobTask.status === '等待队列') {
        finish(statusPill('queued', '等待队列'));
        return;
      }
      if (jobTask.status === '进行中') {
        finish(statusPill('info', '进行中'));
        return;
      }
      if (jobTask.status === '完成') {
        const full = jobTask.full_score;
        if (full === false && !task.attempts_exhausted) {
          finish(statusPill('todo-pill', '未完成',
            (jobTask.score_text ? '本次得分 ' + jobTask.score_text + '，' : '')
            + '未得满分'));
        } else if (jobTask.score_text) {
          const kind = 'done-pill';
          const title = full === false
            ? '次数已用完，本次得分 ' + jobTask.score_text
            : '得分';
          finish(statusPill(kind, jobTask.score_text, title));
        } else {
          finish(statusPill('done-pill', '完成'));
        }
        return;
      }
      if (jobTask.status === '已发布') {
        finish(statusPill('published-pill', '已发布'));
        return;
      }
      if (jobTask.status === '已填写') {
        finish(statusPill('filled-pill', '已填写',
          jobTask.message || '已填写'));
        return;
      }
      if (jobTask.status === '失败') {
        finish(statusPill('failed-pill', '失败', jobTask.error || ''));
        return;
      }
      if (jobTask.status === '已取消') {
        finish(statusPill(
          'todo-pill', '已取消', jobTask.message || jobTask.error || '任务已取消'
        ));
        return;
      }
      if (jobTask.status === '已跳过') {
        finish(statusPill('todo-pill', '已跳过', jobTask.message || ''));
        return;
      }
    }
    if (task.status === 'done') {
      finish(statusPill('done-pill', '完成'));
    } else {
      finish(statusPill('todo-pill',
        task.status === 'overdue' ? '未完成（已逾期）' : '未完成'));
    }
  };

  IC.updateSelectionUI = function () {
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
  };

  IC.countChecked = function () {
    let total = 0;
    state.checked.forEach((set) => {
      total += set.size;
    });
    return total;
  };

  IC.toggleSelectAll = function () {
    const checked = selectedSet(state.activeType);
    const tasks = tasksOfActiveType().filter((task) => task.status !== 'done');
    if (els['i-select-all'] && els['i-select-all'].checked) {
      tasks.forEach((task) => checked.add(task.key));
    } else {
      tasks.forEach((task) => checked.delete(task.key));
    }
    renderTasks();
    updateSelectionUI();
  };

  IC.selectUnsolved = function () {
    selectedSet(state.activeType);
    const checked = state.checked.get(state.activeType);
    tasksOfActiveType().forEach((task) => {
      if (task.status !== 'done') {
        checked.add(task.key);
      }
    });
    renderTasks();
    updateSelectionUI();
  };

})(window);