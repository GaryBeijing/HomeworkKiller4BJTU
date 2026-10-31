/*
  作者: Gary
  编写日期: 2026-10-31 20:45
  最后更新: 2026-10-31 21:45
  文件名: hsr.js
  主要用途: “高铁纵横”页面逻辑：登录、列表渲染、二次确认、答题与结果弹窗。
  文件版本: 1.0.1
*/

(function () {
  'use strict';

  const PAGE_NAME = '高铁纵横';

  /** 页面运行状态。 */
  const state = {
    loggedIn: false,
    username: '',
    hasCredentials: false,
    exams: [],
    pendingExam: null,
    busy: false,
    autoTried: false,
    initialized: false,
    keydownHandler: null,
  };

  /** 页面元素缓存。 */
  const els = {};

  /**
   * 缓存页面元素引用。
   * @returns {void}
   */
  function cacheElements() {
    els.username = document.getElementById('hsr-username');
    els.password = document.getElementById('hsr-password');
    els.loginForm = document.getElementById('hsr-login-form');
    els.loginSubmit = document.getElementById('hsr-login-submit');
    els.logout = document.getElementById('hsr-logout');
    els.refresh = document.getElementById('hsr-refresh');
    els.loginStatus = document.getElementById('hsr-login-status');
    els.examBody = document.getElementById('hsr-exam-body');
    els.listHint = document.getElementById('hsr-list-hint');
    els.confirmModal = document.getElementById('hsr-confirm-modal');
    els.confirmText = document.getElementById('hsr-confirm-text');
    els.confirmOk = document.getElementById('hsr-confirm-ok');
    els.confirmCancel = document.getElementById('hsr-confirm-cancel');
    els.resultModal = document.getElementById('hsr-result-modal');
    els.resultSummary = document.getElementById('hsr-result-summary');
    els.resultDetails = document.getElementById('hsr-result-details');
    els.resultClose = document.getElementById('hsr-result-close');
  }

  /**
   * 更新登录状态提示。
   * @param {string} text 提示文本。
   * @param {'muted'|'error'|'success'} [kind] 样式类型。
   * @returns {void}
   */
  function setStatus(text, kind) {
    if (!els.loginStatus) {
      return;
    }
    const suffix = kind === 'error' ? ' error-text' : kind === 'success' ? ' success-text' : '';
    els.loginStatus.className = 'hint login-status' + suffix;
    els.loginStatus.textContent = text;
  }

  /**
   * 切换忙碌状态并控制全局加载遮罩。
   * @param {boolean} busy 是否忙碌。
   * @param {string} [message] 加载提示。
   * @returns {void}
   */
  function setBusy(busy, message) {
    state.busy = busy;
    const controls = [
      els.loginSubmit,
      els.logout,
      els.refresh,
      els.confirmOk,
      els.confirmCancel,
    ].filter(Boolean);
    controls.forEach((control) => {
      control.disabled = busy;
    });
    if (els.username) {
      els.username.disabled = busy;
    }
    if (els.password) {
      els.password.disabled = busy;
    }
    if (busy) {
      App.setLoading(true, message || '处理中…');
    } else {
      App.setLoading(false);
    }
  }

  /**
   * 读取后端登录状态并同步界面。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function refreshState() {
    const data = await App.callOk('get_state');
    state.loggedIn = Boolean(data.logged_in);
    state.username = data.username || '';
    state.hasCredentials = Boolean(data.has_credentials);
    if (els.username && !els.username.value) {
      els.username.value = state.username;
    }
    const bankCount = Number(data.bank_count || 0);
    const chapters = Array.isArray(data.bank_chapters) ? data.bank_chapters.length : 0;
    if (els.listHint) {
      els.listHint.textContent =
        `题库：${bankCount} 题，覆盖 ${chapters} 章。开始考试会消耗一次作答机会，请确认后再操作。`;
    }
    if (state.loggedIn) {
      setStatus(`已登录：${state.username || '当前账号'}`, 'success');
    } else if (state.hasCredentials) {
      setStatus('检测到本机已保存账号，正在尝试自动登录…', 'muted');
    } else {
      setStatus('登录成功后，账号密码只保存在本机 config.json。', 'muted');
    }
  }

  /**
   * 使用已保存凭据登录。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function loginSaved() {
    setBusy(true, '正在使用已保存账号登录（含验证码识别）…');
    try {
      const data = await App.callOk('login_saved');
      state.loggedIn = true;
      state.username = data.username || state.username;
      state.hasCredentials = true;
      setStatus(`已登录：${state.username}`, 'success');
      try {
        await loadExams(false);
      } catch (listError) {
        App.toast(`登录成功，但读取考试列表失败: ${listError.message}`, 'warn');
      }
    } finally {
      setBusy(false);
    }
  }

  /**
   * 处理自动登录流程。
   * @returns {Promise<boolean>} 是否通过已保存凭据成功登录。
   */
  async function autoLoginFlow() {
    if (state.loggedIn || !state.hasCredentials || state.autoTried) {
      return false;
    }
    state.autoTried = true;
    try {
      await loginSaved();
      return true;
    } catch (error) {
      setStatus(`自动登录失败：${error.message}`, 'error');
      return false;
    }
  }

  /**
   * 处理手动登录。
   * @param {SubmitEvent} event 表单提交事件。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function handleLogin(event) {
    event.preventDefault();
    if (state.busy) {
      return;
    }
    const username = (els.username.value || '').trim();
    const password = els.password.value || '';
    if (!username || !password) {
      setStatus('请输入学号/账号和密码。', 'error');
      return;
    }
    setBusy(true, '正在识别验证码并登录…');
    try {
      const data = await App.callOk('login', { username, password });
      state.loggedIn = true;
      state.username = data.username || username;
      state.hasCredentials = true;
      state.autoTried = true;
      els.password.value = '';
      setStatus(`登录成功：${state.username}`, 'success');
      App.toast('登录成功', 'success');
      try {
        await loadExams(false);
      } catch (listError) {
        App.toast(`登录成功，但读取考试列表失败: ${listError.message}`, 'warn');
      }
    } catch (error) {
      setStatus(`登录失败：${error.message}`, 'error');
      App.toast(`登录失败: ${error.message}`, 'error');
    } finally {
      setBusy(false);
    }
  }

  /**
   * 退出登录。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function handleLogout() {
    if (state.busy) {
      return;
    }
    setBusy(true, '正在退出登录…');
    try {
      await App.callOk('logout');
      state.loggedIn = false;
      state.exams = [];
      state.autoTried = true;
      setStatus('已退出登录。', 'muted');
      renderEmpty('请先登录');
      clearResult();
      App.toast('已退出登录', 'info');
    } catch (error) {
      setStatus(`退出登录失败：${error.message}`, 'error');
    } finally {
      setBusy(false);
    }
  }

  /**
   * 读取考试列表并渲染。
   * @param {boolean} showLoading 是否显示加载遮罩。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function loadExams(showLoading) {
    if (!state.loggedIn) {
      renderEmpty('请先登录');
      return;
    }
    if (showLoading) {
      App.setLoading(true, '正在读取考试列表…');
    }
    try {
      const data = await App.callOk('list_exams');
      state.exams = Array.isArray(data.records) ? data.records : [];
      renderExams();
    } finally {
      if (showLoading) {
        App.setLoading(false);
      }
    }
  }

  /**
   * 渲染空状态行。
   * @param {string} message 提示文本。
   * @returns {void}
   */
  function renderEmpty(message) {
    if (!els.examBody) {
      return;
    }
    els.examBody.innerHTML = '';
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 6;
    cell.className = 'table-empty';
    cell.textContent = message;
    row.appendChild(cell);
    els.examBody.appendChild(row);
  }

  /**
   * 创建表格单元格。
   * @param {string} text 文本内容。
   * @param {string} [className] 类名。
   * @returns {HTMLTableCellElement} 单元格。
   */
  function createCell(text, className) {
    const cell = document.createElement('td');
    if (className) {
      cell.className = className;
    }
    cell.textContent = text;
    return cell;
  }

  /**
   * 根据考试状态返回标签样式。
   * @param {Object} exam 考试记录。
   * @returns {string} 样式类名。
   */
  function statusClass(exam) {
    const status = String(exam.status || '');
    if (status.startsWith('可作答')) {
      return 'ok';
    }
    if (status.startsWith('未开始')) {
      return 'warn';
    }
    if (status.startsWith('已截止') || status.startsWith('次数用完')) {
      return 'bad';
    }
    return 'info';
  }

  /**
   * 渲染考试列表。
   * @returns {void}
   */
  function renderExams() {
    if (!els.examBody) {
      return;
    }
    els.examBody.innerHTML = '';
    if (state.exams.length === 0) {
      renderEmpty('当前没有可显示的考试。');
      return;
    }
    state.exams.forEach((exam, index) => {
      const row = document.createElement('tr');

      row.appendChild(createCell(String(index + 1)));
      row.appendChild(createCell(String(exam.chapterName || '未命名章节'), 'chapter-cell'));

      const used = exam.participateCount === null || exam.participateCount === undefined
        ? '-' : exam.participateCount;
      const total = exam.participateStrategy === null || exam.participateStrategy === undefined
        ? '-' : exam.participateStrategy;
      row.appendChild(createCell(`${used} / ${total}`));

      const score = exam.finalScore === null || exam.finalScore === undefined
        ? '-' : exam.finalScore;
      row.appendChild(createCell(String(score)));

      const statusCell = document.createElement('td');
      const pill = document.createElement('span');
      pill.className = `pill ${statusClass(exam)}`;
      pill.textContent = String(exam.status || '未知');
      statusCell.appendChild(pill);
      row.appendChild(statusCell);

      const actionCell = document.createElement('td');
      const action = document.createElement('button');
      action.type = 'button';
      action.className = 'btn small exam-action';
      action.textContent = '开始答题';
      action.disabled = !exam.available;
      if (!exam.available) {
        action.title = String(exam.status || '当前不可作答');
        action.classList.add('ghost');
      } else {
        action.classList.add('primary');
        action.addEventListener('click', () => openConfirm(exam));
      }
      actionCell.appendChild(action);
      row.appendChild(actionCell);

      els.examBody.appendChild(row);
    });
  }

  /**
   * 打开开始考试确认框。
   * @param {Object} exam 考试记录。
   * @returns {void}
   */
  function openConfirm(exam) {
    state.pendingExam = exam;
    if (els.confirmText) {
      els.confirmText.textContent =
        `即将开始《${exam.chapterName || '未命名章节'}》，这会消耗 1 次作答机会。确认后程序将自动答题并提交。`;
    }
    if (els.confirmModal) {
      els.confirmModal.classList.remove('hidden');
    }
  }

  /**
   * 关闭开始考试确认框。
   * @returns {void}
   */
  function closeConfirm() {
    state.pendingExam = null;
    if (els.confirmModal) {
      els.confirmModal.classList.add('hidden');
    }
  }

  /**
   * 确认开始考试并展示结果。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function confirmStart() {
    if (state.busy || !state.pendingExam) {
      return;
    }
    const exam = state.pendingExam;
    closeConfirm();
    setBusy(true, '正在开始考试、自动答题并提交…');
    try {
      const result = await App.callOk('start_exam', { exam_id: exam.id });
      renderResult(result);
      App.toast('试卷已提交', 'success');
      try {
        await loadExams(false);
      } catch (listError) {
        App.toast(`试卷已提交，但刷新列表失败: ${listError.message}`, 'warn');
      }
    } catch (error) {
      App.toast(`答题失败: ${error.message}`, 'error');
      // 答题可能已消耗次数，失败后尽量刷新列表。
      try {
        await loadExams(false);
      } catch (refreshError) {
        console.error(refreshError);
      }
    } finally {
      setBusy(false);
    }
  }

  /**
   * 创建统计块。
   * @param {string} label 标签。
   * @param {string} value 值。
   * @param {string} [valueClass] 值样式。
   * @param {boolean} [small] 是否使用小号字体。
   * @returns {HTMLElement} 统计块。
   */
  function createStat(label, value, valueClass, small) {
    const block = document.createElement('div');
    block.className = 'stat';
    const labelNode = document.createElement('div');
    labelNode.className = 'stat-label';
    labelNode.textContent = label;
    const valueNode = document.createElement('div');
    valueNode.className = 'stat-value' + (small ? ' small' : '') + (valueClass ? ' ' + valueClass : '');
    valueNode.textContent = value;
    block.appendChild(labelNode);
    block.appendChild(valueNode);
    return block;
  }

  /**
   * 创建题目列表。
   * @param {Array<{index: number, content: string}>} items 题目列表。
   * @returns {HTMLUListElement} 列表元素。
   */
  function createQuestionList(items) {
    const list = document.createElement('ul');
    list.className = 'detail-list';
    items.forEach((item) => {
      const li = document.createElement('li');
      li.textContent = `第 ${item.index} 题：${item.content || '（无题干）'}`;
      list.appendChild(li);
    });
    return list;
  }

  /**
   * 在弹出子窗口中渲染答题结果。
   * @param {Object} result 后端返回的结果。
   * @returns {void}
   */
  function renderResult(result) {
    if (!els.resultModal || !els.resultSummary || !els.resultDetails) {
      return;
    }
    els.resultSummary.innerHTML = '';
    els.resultDetails.innerHTML = '';

    const missing = Array.isArray(result.missing) ? result.missing : [];
    const risky = Array.isArray(result.risky) ? result.risky : [];
    const total = Number(result.total || 0);
    const hit = Number(result.hit_count || 0);
    const score = result.score === null || result.score === undefined ? '—' : String(result.score);

    els.resultSummary.appendChild(
      createStat('考试', String(result.exam_name || '—'), '', true)
    );
    els.resultSummary.appendChild(
      createStat('得分', score, 'ok')
    );
    els.resultSummary.appendChild(
      createStat('题库命中', `${hit} / ${total}`, hit === total ? 'ok' : 'bad')
    );
    els.resultSummary.appendChild(
      createStat('未命中', String(missing.length), missing.length ? 'bad' : 'ok')
    );

    if (missing.length > 0) {
      const details = document.createElement('details');
      details.open = true;
      const summary = document.createElement('summary');
      summary.textContent = `未命中题目（${missing.length}）`;
      details.appendChild(summary);
      details.appendChild(createQuestionList(missing));
      els.resultDetails.appendChild(details);
    }

    if (risky.length > 0) {
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = `按字母兜底的题目（${risky.length}）`;
      details.appendChild(summary);
      const note = document.createElement('p');
      note.className = 'risk-note';
      note.textContent = '这些题未能按选项原文匹配，已按题库字母兜底；若选项顺序被打乱，可能选错。';
      details.appendChild(note);
      details.appendChild(createQuestionList(risky));
      els.resultDetails.appendChild(details);
    }

    if (missing.length === 0 && risky.length === 0) {
      const note = document.createElement('p');
      note.className = 'hint';
      note.textContent = '全部题目均按选项原文命中题库。';
      els.resultDetails.appendChild(note);
    }

    els.resultModal.classList.remove('hidden');
    if (els.resultClose) {
      els.resultClose.focus();
    }
  }

  /**
   * 关闭答题结果弹窗。
   * @returns {void}
   */
  function clearResult() {
    if (els.resultModal) {
      els.resultModal.classList.add('hidden');
    }
    if (els.resultSummary) {
      els.resultSummary.innerHTML = '';
    }
    if (els.resultDetails) {
      els.resultDetails.innerHTML = '';
    }
  }

  /**
   * 绑定页面事件。
   * @returns {void}
   */
  function bindEvents() {
    if (els.loginForm) {
      els.loginForm.addEventListener('submit', handleLogin);
    }
    if (els.logout) {
      els.logout.addEventListener('click', handleLogout);
    }
    if (els.refresh) {
      els.refresh.addEventListener('click', async () => {
        if (!state.loggedIn) {
          App.toast('请先登录', 'warn');
          return;
        }
        if (state.busy) {
          return;
        }
        setBusy(true, '正在刷新考试列表…');
        try {
          await loadExams(false);
          App.toast('考试列表已刷新', 'success');
        } catch (error) {
          App.toast(`刷新失败: ${error.message}`, 'error');
        } finally {
          setBusy(false);
        }
      });
    }
    if (els.confirmOk) {
      els.confirmOk.addEventListener('click', confirmStart);
    }
    if (els.confirmCancel) {
      els.confirmCancel.addEventListener('click', closeConfirm);
    }
    if (els.confirmModal) {
      els.confirmModal.addEventListener('click', (event) => {
        if (event.target === els.confirmModal) {
          closeConfirm();
        }
      });
    }
    if (els.resultClose) {
      els.resultClose.addEventListener('click', clearResult);
    }
    if (els.resultModal) {
      els.resultModal.addEventListener('click', (event) => {
        if (event.target === els.resultModal) {
          clearResult();
        }
      });
    }
  }

  /**
   * 页面首次初始化。
   * @param {HTMLElement} container 内容容器。
   * @returns {void}
   */
  function init(container) {
    cacheElements();
    bindEvents();
    state.pendingExam = null;
    if (els.confirmModal) {
      els.confirmModal.classList.add('hidden');
    }
    if (els.resultModal) {
      els.resultModal.classList.add('hidden');
    }
    // 每次重新注入 HTML 后移除旧的全局键盘监听，避免重复绑定。
    if (state.keydownHandler) {
      document.removeEventListener('keydown', state.keydownHandler);
    }
    state.keydownHandler = (event) => {
      if (event.key !== 'Escape') {
        return;
      }
      // 结果弹窗优先关闭；没有结果弹窗时再关闭开始确认框。
      if (els.resultModal && !els.resultModal.classList.contains('hidden')) {
        clearResult();
        return;
      }
      closeConfirm();
    };
    document.addEventListener('keydown', state.keydownHandler);
    state.initialized = true;
  }

  /**
   * 每次切换到本标签时刷新状态与列表。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function onActivate() {
    if (!state.initialized) {
      return;
    }
    try {
      await refreshState();
    } catch (error) {
      setStatus(`读取状态失败：${error.message}`, 'error');
      App.toast(`读取状态失败: ${error.message}`, 'error');
      return;
    }
    const autoLoggedIn = await autoLoginFlow();
    if (state.loggedIn && !autoLoggedIn) {
      try {
        await loadExams(false);
      } catch (error) {
        App.toast(`读取考试列表失败: ${error.message}`, 'error');
      }
    } else if (!state.loggedIn) {
      renderEmpty('请先登录');
    }
  }

  App.registerPage(PAGE_NAME, { init: init, onActivate: onActivate });
})();
