/*
  作者: Gary
  编写日期: 2026-11-01 00:01
  最后更新: 2026-11-11 10:30
  文件名: cprog.js
  主要用途: “C程序设计”页面逻辑：课程/题目选择、设置跳转、启发模式分步弹窗、题解模式后台任务与结果弹窗（仅展示一次）。
  文件版本: 4.4.3
*/

(function () {
  'use strict';

  const PAGE_NAME = 'C程序设计';
  const MAX_ATTEMPTS = 5;

  /** 页面运行状态。 */
  const state = {
    initialized: false,
    courses: [],
    selectedCourseId: null,
    structure: null,
    activePartIndex: 0,
    selected: new Set(),
    mode: 'guide',
    solutionEnabled: false,
    busy: false,
    jobId: '',
    jobTimer: null,
    currentJob: null,
    analysis: null,
    analysisStep: 0,
    guideQueue: [],
    guideIndex: 0,
    drafts: {},
    lastConsequence: null,
    solutionItems: [],
    solutionIndex: 0,
    jobProblemStates: {},
    keydownHandler: null,
    lastNotifiedJobId: '',
    resultShownJobId: '',
  };

  /** 页面元素缓存。 */
  const els = {};

  /**
   * 缓存页面元素。
   * @returns {void}
   */
  function cacheElements() {
    els.accountBadge = document.getElementById('c-account-badge');
    els.openSettings = document.getElementById('c-open-settings');
    els.accountStatus = document.getElementById('c-account-status');
    els.refreshCourses = document.getElementById('c-refresh-courses');
    els.courseList = document.getElementById('c-course-list');
    els.modeGuide = document.getElementById('c-mode-guide');
    els.modeSolution = document.getElementById('c-mode-solution');
    els.modeLock = document.getElementById('c-mode-lock');
    els.modeInfo = document.getElementById('c-mode-info');
    els.modeTooltip = document.getElementById('c-mode-tooltip');
    els.modeHint = document.getElementById('c-mode-hint');
    els.partTabs = document.getElementById('c-part-tabs');
    els.problemBody = document.getElementById('c-problem-body');
    els.selectAllInput = document.getElementById('c-select-all-input');
    els.selectUnsolved = document.getElementById('c-select-unsolved');
    els.selectionHint = document.getElementById('c-selection-hint');
    els.start = document.getElementById('c-start');
    els.progressCard = document.getElementById('c-progress-card');
    els.progressPhase = document.getElementById('c-progress-phase');
    els.progressMessage = document.getElementById('c-progress-message');
    els.progressBar = document.getElementById('c-progress-bar');
    els.progressLog = document.getElementById('c-progress-log');
    els.analysisModal = document.getElementById('c-analysis-modal');
    els.analysisTitle = document.getElementById('c-analysis-title');
    els.analysisClose = document.getElementById('c-analysis-close');
    els.analysisStepper = document.getElementById('c-analysis-stepper');
    els.analysisBody = document.getElementById('c-analysis-body');
    els.analysisPrev = document.getElementById('c-analysis-prev');
    els.analysisNext = document.getElementById('c-analysis-next');
    els.solutionConfirm = document.getElementById('c-solution-confirm');
    els.solutionYes = document.getElementById('c-solution-yes');
    els.solutionNo = document.getElementById('c-solution-no');
    els.solutionResult = document.getElementById('c-solution-result');
    els.solutionResultTitle = document.getElementById('c-solution-result-title');
    els.solutionList = document.getElementById('c-solution-list');
    els.solutionWarning = document.getElementById('c-solution-warning');
    els.solutionCodeTitle = document.getElementById('c-solution-code-title');
    els.solutionExplanation = document.getElementById('c-solution-explanation');
    els.solutionCode = document.getElementById('c-solution-code');
    els.solutionNotes = document.getElementById('c-solution-notes');
    els.solutionResultClose = document.getElementById('c-solution-result-close');
  }

  /**
   * 创建节点并设置文本。
   * @param {string} tagName 标签名。
   * @param {string} className 类名。
   * @param {string} [text] 文本。
   * @returns {HTMLElement} 节点。
   */
  function node(tagName, className, text) {
    const item = document.createElement(tagName);
    if (className) {
      item.className = className;
    }
    if (text !== undefined) {
      item.textContent = text;
    }
    return item;
  }

  /**
   * 设置账号徽标。
   * @param {string} text 文本。
   * @param {string} kind 徽标样式。
   * @returns {void}
   */
  function setAccountBadge(text, kind) {
    if (!els.accountBadge) {
      return;
    }
    els.accountBadge.className = 'hero-badge';
    els.accountBadge.textContent = text;
    if (kind === 'ok' || kind === 'bad') {
      els.accountBadge.style.borderColor = kind === 'ok' ? '#9be3c5' : '#f0b4b4';
      els.accountBadge.style.color = kind === 'ok' ? '#d8ffee' : '#ffe0e0';
    }
  }

  /**
   * 设置账号提示文本。
   * @param {string} text 文本。
   * @returns {void}
   */
  function setAccountHint(text) {
    if (els.accountStatus) {
      els.accountStatus.textContent = text;
    }
  }

  /**
   * 切换全局忙碌状态。
   * @param {boolean} busy 是否忙碌。
   * @param {string} [message] 加载提示。
   * @returns {void}
   */
  function setBusy(busy, message) {
    state.busy = busy;
    if (busy) {
      App.setLoading(true, message || '处理中…');
    } else {
      App.setLoading(false);
    }
    updateModeUI();
    updateSelectionUI();
    if (els.refreshCourses) {
      els.refreshCourses.disabled = busy || jobRunning();
    }
  }

  /**
   * 判断当前是否有题解任务在运行。
   * @returns {boolean} 运行中返回 true。
   */
  function jobRunning() {
    if (!state.jobId) {
      return false;
    }
    if (!state.currentJob) {
      return true; // 已启动但尚未拿到第一份状态。
    }
    return Boolean(state.currentJob.running);
  }

  /**
   * 读取后端状态并更新模式开关。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function refreshState() {
    const data = await App.callOk('get_state');
    state.solutionEnabled = Boolean(data.solution_mode_enabled);
    if (!state.solutionEnabled && state.mode === 'solution') {
      state.mode = 'guide';
    }
    setAccountBadge(data.logged_in ? `已连接：${data.username || 'CITEL'}` : '未连接');
    setAccountHint(
      data.ai_ready
        ? '用户名已配置，AI 设置已就绪；账号密码统一在设置中管理。'
        : 'AI 设置未完成，请前往设置补充模型与 API Key。'
    );
    updateModeUI();
  }

  /**
   * 判断题目是否已经 AC。
   * @param {Object} problem 题目数据。
   * @returns {boolean} 已完成返回 true。
   */
  function isSolved(problem) {
    return Boolean(problem.solved || String(problem.my_result || '').startsWith('AC'));
  }

  /**
   * 渲染课程列表。
   * @returns {void}
   */
  function renderCourses() {
    if (!els.courseList) {
      return;
    }
    els.courseList.innerHTML = '';
    if (state.courses.length === 0) {
      els.courseList.appendChild(node('p', 'muted', '暂无课程，请点击“刷新课程”。'));
      return;
    }
    state.courses.forEach((course) => {
      const button = node('button', 'course-item', course.name || `课程 ${course.id}`);
      button.type = 'button';
      button.dataset.courseId = String(course.id);
      if (course.id === state.selectedCourseId) {
        button.classList.add('active');
      }
      button.disabled = state.busy || jobRunning();
      els.courseList.appendChild(button);
    });
  }

  /**
   * 加载课程列表。
   * @param {boolean} showLoading 是否显示加载遮罩。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function loadCourses(showLoading) {
    if (showLoading) {
      App.setLoading(true, '正在登录 CITEL 并读取课程…');
    }
    try {
      const data = await App.callOk('load_courses');
      state.courses = Array.isArray(data.courses) ? data.courses : [];
      setAccountBadge(`已连接：${data.username || 'CITEL'}`, 'ok');
      setAccountHint('已连接 CITEL。请选择课程，然后选择部分与题目。');
      renderCourses();
      const lastId = Number(data.last_course_id || 0);
      const target = state.courses.find((course) => course.id === lastId)
        || (state.courses.length === 1 ? state.courses[0] : null);
      if (target) {
        await selectCourse(target.id, false);
      }
    } catch (error) {
      setAccountBadge('连接失败', 'bad');
      setAccountHint(`连接 CITEL 失败：${error.message}`);
      if (els.courseList) {
        els.courseList.innerHTML = '';
        els.courseList.appendChild(node('p', 'error-text', error.message));
      }
      App.toast(`连接 CITEL 失败: ${error.message}`, 'error');
    } finally {
      if (showLoading) {
        App.setLoading(false);
      }
    }
  }

  /**
   * 选择并加载课程。
   * @param {number} courseId 课程 ID。
   * @param {boolean} [showLoading] 是否显示加载遮罩。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function selectCourse(courseId, showLoading) {
    if (state.busy || jobRunning()) {
      return;
    }
    state.selectedCourseId = courseId;
    state.selected.clear();
    state.jobProblemStates = {};
    renderCourses();
    if (showLoading !== false) {
      App.setLoading(true, '正在读取课程题目…');
    }
    try {
      const data = await App.callOk('select_course', { course_id: courseId });
      state.structure = data;
      state.activePartIndex = 0;
      renderParts();
      renderProblems();
      if (data.warning) {
        App.toast(data.warning, 'warn');
      }
    } catch (error) {
      App.toast(`读取课程失败: ${error.message}`, 'error');
      if (els.problemBody) {
        els.problemBody.innerHTML = '';
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 4;
        cell.className = 'table-empty';
        cell.textContent = `读取课程失败：${error.message}`;
        row.appendChild(cell);
        els.problemBody.appendChild(row);
      }
    } finally {
      if (showLoading !== false) {
        App.setLoading(false);
      }
    }
  }

  /**
   * 获取当前部分。
   * @returns {Object|null} 部分数据。
   */
  function currentPart() {
    if (!state.structure || !Array.isArray(state.structure.parts)) {
      return null;
    }
    return state.structure.parts[state.activePartIndex] || null;
  }

  /**
   * 渲染部分标签。
   * @returns {void}
   */
  function renderParts() {
    if (!els.partTabs) {
      return;
    }
    els.partTabs.innerHTML = '';
    const parts = state.structure && Array.isArray(state.structure.parts)
      ? state.structure.parts : [];
    parts.forEach((part, index) => {
      const button = node('button', 'part-tab', part.name || `部分 ${index + 1}`);
      button.type = 'button';
      button.dataset.partIndex = String(index);
      if (index === state.activePartIndex) {
        button.classList.add('active');
      }
      els.partTabs.appendChild(button);
    });
  }

  /**
   * 根据题目状态文本选择徽标样式。
   * @param {string} status 状态文本。
   * @returns {'ok'|'warn'|'bad'|'info'} 徽标样式。
   */
  function statusPillKind(status) {
    const text = String(status || '');
    if (text.startsWith('AC')) {
      return 'ok';
    }
    if (text === '未提交') {
      return 'info';
    }
    if (text === '等待队列') {
      return 'queued';
    }
    if (text === '生成题解') {
      return 'working';
    }
    if (text === '提交中') {
      return 'submitting';
    }
    if (text.startsWith('错误') || text.startsWith('AI错误')
        || text.includes('失败') || text.includes('无法') || text.includes('异常')
        || /^(WA|TLE|MLE|RE|CE|PE|OLE|TR|RJ|MC)/.test(text)) {
      return 'bad';
    }
    return text ? 'warn' : 'info';
  }

  /**
   * 用后端任务状态实时更新题目列表中的状态徽标。
   * @param {Array<Object>} problems 任务中的题目状态列表。
   * @returns {void}
   */
  function updateProblemPills(problems) {
    if (!Array.isArray(problems) || !els.problemBody) {
      return;
    }
    const map = {};
    problems.forEach((item) => {
      if (item && item.module_id !== undefined) {
        map[String(item.module_id)] = item;
      }
    });
    state.jobProblemStates = map;
    els.problemBody.querySelectorAll('tr[data-module-id]').forEach((row) => {
      const item = map[row.dataset.moduleId];
      if (!item || !item.status) {
        return;
      }
      const pill = row.querySelector('.pill[data-job-status]');
      if (!pill) {
        return;
      }
      pill.textContent = String(item.status);
      pill.className = 'pill ' + statusPillKind(item.status);
    });
  }

  /**
   * 渲染当前部分的题目列表。
   * @returns {void}
   */
  function renderProblems() {
    if (!els.problemBody) {
      return;
    }
    els.problemBody.innerHTML = '';
    const part = currentPart();
    if (!part) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 4;
      cell.className = 'table-empty';
      cell.textContent = '请先选择课程';
      row.appendChild(cell);
      els.problemBody.appendChild(row);
      updateSelectionUI();
      return;
    }
    part.problems.forEach((problem) => {
      const row = document.createElement('tr');
      row.dataset.moduleId = String(problem.module_id);
      const checkCell = document.createElement('td');
      checkCell.className = 'check-col';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.dataset.moduleId = String(problem.module_id);
      checkbox.checked = state.selected.has(problem.module_id);
      checkbox.disabled = isSolved(problem) || state.busy || jobRunning();
      checkCell.appendChild(checkbox);
      row.appendChild(checkCell);
      row.appendChild(node('td', '', String(problem.number)));
      row.appendChild(node('td', 'chapter-cell', String(problem.title || '未命名题目')));
      const statusCell = document.createElement('td');
      const jobState = state.jobProblemStates[String(problem.module_id)];
      const statusText = jobState && jobState.status
        ? jobState.status
        : (isSolved(problem) ? 'AC' : (problem.my_result || '未提交'));
      const pill = node('span', 'pill ' + statusPillKind(statusText), statusText);
      pill.dataset.jobStatus = '1';
      statusCell.appendChild(pill);
      row.appendChild(statusCell);
      els.problemBody.appendChild(row);
    });
    updateSelectionUI();
  }

  /**
   * 更新选择数量与开始按钮状态。
   * @returns {void}
   */
  function updateSelectionUI() {
    const count = state.selected.size;
    if (els.selectionHint) {
      els.selectionHint.textContent = `已选 ${count} 题`;
    }
    if (els.start) {
      const running = jobRunning();
      els.start.textContent = running ? '终止解题' : '开始学习';
      els.start.className = running ? 'btn danger-outline' : 'btn primary';
      els.start.disabled = running ? false : (count === 0 || state.busy);
    }
    const part = currentPart();
    if (els.selectAllInput) {
      const unsolved = part
        ? part.problems.filter((problem) => !isSolved(problem))
        : [];
      const allSelected = unsolved.length > 0 && unsolved.every((problem) => state.selected.has(problem.module_id));
      const someSelected = unsolved.some((problem) => state.selected.has(problem.module_id));
      els.selectAllInput.checked = allSelected;
      els.selectAllInput.indeterminate = someSelected && !allSelected;
      els.selectAllInput.disabled = unsolved.length === 0 || state.busy || jobRunning();
    }
  }

  /**
   * 更新模式开关显示。
   * @returns {void}
   */
  function updateModeUI() {
    if (!els.modeGuide || !els.modeSolution) {
      return;
    }
    els.modeGuide.classList.toggle('active', state.mode === 'guide');
    els.modeSolution.classList.toggle('active', state.mode === 'solution');
    els.modeSolution.disabled = !state.solutionEnabled || state.busy || jobRunning();
    els.modeSolution.classList.toggle('locked', !state.solutionEnabled);
    els.modeSolution.classList.toggle('solution-enabled', state.solutionEnabled);
    if (els.modeLock) {
      els.modeLock.style.display = state.solutionEnabled ? 'none' : 'inline-block';
    }
    if (els.modeHint) {
      els.modeHint.textContent = state.solutionEnabled
        ? (state.mode === 'solution'
          ? '题解模式：AI 将先生成思路，再生成带注释的完整题解并自动提交；仅在十分需要真实实例时使用。'
          : '启发模式：先看思路，再自己写代码；只有“大功告成”步骤才显示提交框。')
        : '题解模式未启用（请在设置中打开“启用题解模式”）；当前仅可使用启发模式。';
    }
  }

  /**
   * 请求切换到指定模式。
   * @param {'guide'|'solution'} mode 模式。
   * @returns {void}
   */
  function requestMode(mode) {
    if (mode === 'solution') {
      if (!state.solutionEnabled) {
        App.toast('题解模式未启用，请前往设置开启', 'warn');
        return;
      }
      if (els.solutionConfirm) {
        els.solutionConfirm.classList.remove('hidden');
      }
      return;
    }
    state.mode = 'guide';
    updateModeUI();
  }

  /**
   * 全选/取消全选当前部分未完成题目。
   * @param {boolean} checked 是否选中。
   * @returns {void}
   */
  function selectAllUnsolved(checked) {
    const part = currentPart();
    if (!part) {
      return;
    }
    part.problems.forEach((problem) => {
      if (isSolved(problem)) {
        return;
      }
      if (checked) {
        state.selected.add(problem.module_id);
      } else {
        state.selected.delete(problem.module_id);
      }
    });
    renderProblems();
  }

  /**
   * 更新本地题目状态。
   * @param {number} moduleId 模块 ID。
   * @param {string} status 新状态。
   * @param {boolean} [keepJobState] 是否保留题解任务的实时状态覆盖。
   * @returns {void}
   */
  function updateProblemStatus(moduleId, status, keepJobState) {
    if (!keepJobState) {
      delete state.jobProblemStates[String(moduleId)];
    }
    if (!state.structure) {
      return;
    }
    state.structure.parts.forEach((part) => {
      part.problems.forEach((problem) => {
        if (problem.module_id === moduleId) {
          problem.my_result = status;
          problem.solved = status.startsWith('AC');
        }
      });
    });
  }

  // ---------------------------------------------------------------- 启发模式
  /**
   * 启动启发模式队列。
   * @returns {void}
   */
  function startGuideMode() {
    state.guideQueue = Array.from(state.selected);
    state.guideIndex = 0;
    if (state.guideQueue.length === 0) {
      App.toast('请先选择题目', 'warn');
      return;
    }
    openGuideProblem(state.guideQueue[0]);
  }

  /**
   * 打开下一道题的启发讲解。
   * @returns {void}
   */
  function nextGuideProblem() {
    state.guideIndex += 1;
    if (state.guideIndex >= state.guideQueue.length) {
      closeAnalysis();
      App.toast('本部分题目学习完成', 'success');
      renderProblems();
      return;
    }
    openGuideProblem(state.guideQueue[state.guideIndex]);
  }

  /**
   * 加载一道题的启发讲解并打开弹窗。
   * @param {number} moduleId 模块 ID。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function openGuideProblem(moduleId) {
    App.setLoading(true, '正在生成启发式讲解（首次会调用 AI）…');
    try {
      const data = await App.callOk('analyze_problem', { module_id: moduleId });
      if (data.already_solved) {
        App.toast(`「${data.problem.title}」此前已 AC，跳过`, 'success');
        updateProblemStatus(moduleId, 'AC: Accepted');
        state.selected.delete(moduleId);
        nextGuideProblem();
        return;
      }
      state.analysis = data;
      state.analysisStep = 0;
      state.lastConsequence = null;
      if (data.ai_error) {
        App.toast(`AI 讲解不可用：${data.ai_error}；已显示题面摘要，仍可手动提交`, 'warn');
      }
      if (els.analysisModal) {
        els.analysisModal.classList.remove('hidden');
      }
      renderAnalysis();
    } catch (error) {
      App.toast(`生成讲解失败: ${error.message}`, 'error');
    } finally {
      App.setLoading(false);
    }
  }

  /**
   * 关闭启发弹窗。
   * @returns {void}
   */
  function closeAnalysis() {
    if (els.analysisModal) {
      els.analysisModal.classList.add('hidden');
    }
    state.analysis = null;
    state.lastConsequence = null;
    state.guideQueue = [];
    state.guideIndex = 0;
  }

  /**
   * 创建讲解文本块。
   * @param {string} title 标题。
   * @param {string} text 文本。
   * @returns {HTMLElement} 块。
   */
  function analysisBlock(title, text) {
    const block = node('div', 'analysis-block');
    block.appendChild(node('h4', '', title));
    block.appendChild(node('p', 'analysis-text', text || '（无内容）'));
    return block;
  }

  /**
   * 渲染当前讲解步骤。
   * @returns {void}
   */
  function renderAnalysis() {
    if (!state.analysis || !els.analysisBody) {
      return;
    }
    const data = state.analysis;
    const analysis = data.analysis || {};
    if (els.analysisTitle) {
      els.analysisTitle.textContent = `${data.problem.title} · 启发模式`;
    }
    if (els.analysisStepper) {
      els.analysisStepper.querySelectorAll('.step').forEach((button, index) => {
        button.classList.toggle('active', index === state.analysisStep);
      });
    }
    els.analysisBody.innerHTML = '';
    if (state.analysisStep === 0) {
      els.analysisBody.appendChild(analysisBlock('简化题干', analysis.simplified_statement));
      els.analysisBody.appendChild(analysisBlock('输入的含义', analysis.input_meaning));
      els.analysisBody.appendChild(analysisBlock('测试数据范围', analysis.test_data_range));
      els.analysisBody.appendChild(analysisBlock('示例输入输出', analysis.sample_io));
    } else if (state.analysisStep === 1) {
      els.analysisBody.appendChild(analysisBlock('解题思路（文字 + 伪代码）', analysis.logic));
    } else if (state.analysisStep === 2) {
      els.analysisBody.appendChild(analysisBlock('注意事项', analysis.precautions));
    } else {
      renderSuccessStep(data);
    }
    if (els.analysisPrev) {
      els.analysisPrev.disabled = state.analysisStep === 0;
    }
    if (els.analysisNext) {
      els.analysisNext.hidden = state.analysisStep === 3;
      els.analysisNext.textContent = state.analysisStep < 2 ? '下一步' : '进入大功告成';
    }
  }

  /**
   * 渲染“大功告成”步骤（只有此步骤显示提交代码框）。
   * @param {Object} data 讲解数据。
   * @returns {void}
   */
  function renderSuccessStep(data) {
    if (!els.analysisBody) {
      return;
    }
    const attempts = Number(data.attempts || 0);
    const remaining = Math.max(0, MAX_ATTEMPTS - attempts);
    const head = node('div', 'attempt-line');
    head.appendChild(node('span', '', `已提交 ${attempts}/${MAX_ATTEMPTS} 次，剩余 ${remaining} 次`));
    els.analysisBody.appendChild(head);

    const editor = document.createElement('textarea');
    editor.className = 'code-editor';
    editor.id = 'c-code-editor';
    editor.placeholder = '在这一步编写你的 C 语言解答，然后点击“提交并判题”。';
    editor.value = state.drafts[data.problem.module_id] || '';
    editor.addEventListener('input', () => {
      state.drafts[data.problem.module_id] = editor.value;
    });
    els.analysisBody.appendChild(editor);

    const row = node('div', 'row');
    row.style.marginTop = '10px';
    const submit = node('button', 'btn primary', '提交并判题');
    submit.type = 'button';
    const canSubmit = attempts < MAX_ATTEMPTS && !(state.lastConsequence && state.lastConsequence.is_ac);
    submit.disabled = !canSubmit;
    submit.addEventListener('click', () => submitGuideCode(data.problem.module_id));
    row.appendChild(submit);

    if (state.lastConsequence && !state.lastConsequence.is_ac) {
      const retryAi = node('button', 'btn ghost', '让 AI 根据错误改进思路');
      retryAi.type = 'button';
      retryAi.addEventListener('click', () => reanalyzeCurrent());
      row.appendChild(retryAi);
    }
    if (state.lastConsequence && (state.lastConsequence.is_ac || attempts >= MAX_ATTEMPTS)) {
      const next = node('button', 'btn ghost', '下一题');
      next.type = 'button';
      next.addEventListener('click', nextGuideProblem);
      row.appendChild(next);
    }
    els.analysisBody.appendChild(row);

    if (state.lastConsequence) {
      els.analysisBody.appendChild(renderConsequence(state.lastConsequence, attempts, remaining));
    }
  }

  /**
   * 渲染判题结果面板。
   * @param {Object} consequence 判题结果。
   * @param {number} attempts 已提交次数。
   * @param {number} remaining 剩余次数。
   * @returns {HTMLElement} 面板。
   */
  function renderConsequence(consequence, attempts, remaining) {
    const panel = node(
      'div',
      'consequence-panel ' + (consequence.is_ac ? 'ok' : 'bad')
    );
    panel.appendChild(node(
      'h4',
      '',
      consequence.is_ac
        ? 'AC：本题通过'
        : `未通过：${consequence.status || '未知状态'}`
    ));
    if (consequence.summary) {
      panel.appendChild(node('p', '', consequence.summary));
    }
    if (consequence.compile_message) {
      const compile = node('pre', 'compile-message', consequence.compile_message);
      panel.appendChild(compile);
    }
    const failed = Array.isArray(consequence.failed_cases) ? consequence.failed_cases : [];
    if (failed.length > 0) {
      const table = document.createElement('table');
      table.className = 'case-table';
      const thead = document.createElement('thead');
      const headRow = document.createElement('tr');
      ['#', '判题', '输入', '期望输出', '实际输出', '错误信息'].forEach((text) => {
        headRow.appendChild(node('th', '', text));
      });
      thead.appendChild(headRow);
      table.appendChild(thead);
      const tbody = document.createElement('tbody');
      failed.slice(0, 3).forEach((caseItem) => {
        const row = document.createElement('tr');
        row.appendChild(node('td', '', String(caseItem.no)));
        row.appendChild(node('td', '', String(caseItem.judge_result || '-')));
        row.appendChild(node('td', '', String(caseItem.test_input || '')));
        row.appendChild(node('td', '', String(caseItem.expected_output || '')));
        row.appendChild(node('td', '', String(caseItem.actual_output || '')));
        row.appendChild(node('td', '', String(caseItem.error_message || '')));
        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      panel.appendChild(table);
    }
    panel.appendChild(node(
      'p',
      'hint',
      `已提交 ${attempts}/${MAX_ATTEMPTS} 次，剩余 ${remaining} 次。`
    ));
    return panel;
  }

  /**
   * 提交启发模式当前代码。
   * @param {number} moduleId 模块 ID。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function submitGuideCode(moduleId) {
    const editor = document.getElementById('c-code-editor');
    const code = editor ? editor.value : '';
    if (!code.trim()) {
      App.toast('请先编写代码', 'warn');
      return;
    }
    state.drafts[moduleId] = code;
    App.setLoading(true, '正在提交并等待判题（可能需要数十秒）…');
    try {
      const data = await App.callOk('submit_problem', {
        module_id: moduleId,
        code,
      });
      state.lastConsequence = data.consequence;
      if (state.analysis) {
        state.analysis.attempts = data.attempts;
        state.analysis.remaining = data.remaining;
      }
      updateProblemStatus(moduleId, data.is_ac ? 'AC: Accepted' : data.consequence.status);
      if (data.is_ac) {
        state.selected.delete(moduleId);
      }
      renderProblems();
      renderAnalysis();
      if (data.is_ac) {
        App.toast('AC：本题通过', 'success');
      } else {
        App.toast(`未通过：${data.consequence.status}`, 'warn');
      }
    } catch (error) {
      App.toast(`提交失败: ${error.message}`, 'error');
    } finally {
      App.setLoading(false);
    }
  }

  /**
   * 根据上次错误重新生成讲解。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function reanalyzeCurrent() {
    if (!state.analysis) {
      return;
    }
    const moduleId = state.analysis.problem.module_id;
    App.setLoading(true, 'AI 正在根据判题错误改进讲解…');
    try {
      const data = await App.callOk('analyze_problem', {
        module_id: moduleId,
        refresh: true,
      });
      state.analysis = data;
      state.analysisStep = 0;
      renderAnalysis();
      if (data.ai_error) {
        App.toast(`AI 仍不可用：${data.ai_error}；已显示题面摘要`, 'warn');
      } else {
        App.toast('已根据判题结果更新讲解', 'success');
      }
    } catch (error) {
      App.toast(`重新分析失败: ${error.message}`, 'error');
    } finally {
      App.setLoading(false);
    }
  }

  // ---------------------------------------------------------------- 题解模式
  /**
   * 启动题解模式后台任务。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function startSolutionMode() {
    const moduleIds = Array.from(state.selected);
    if (moduleIds.length === 0) {
      App.toast('请先选择题目', 'warn');
      return;
    }
    if (!state.solutionEnabled) {
      App.toast('题解模式未启用，请前往设置开启', 'warn');
      return;
    }
    if (els.solutionConfirm) {
      els.solutionConfirm.classList.add('hidden');
    }
    if (els.progressCard) {
      els.progressCard.classList.remove('hidden');
    }
    if (els.progressLog) {
      els.progressLog.innerHTML = '';
    }
    App.setLoading(true, '正在启动题解模式…');
    try {
      const data = await App.callOk('start_solution_job', { module_ids: moduleIds });
      state.jobId = data.job_id;
      state.currentJob = null;
      state.resultShownJobId = '';
      state.lastNotifiedJobId = '';
      state.jobProblemStates = {};
      if (Array.isArray(data.problems)) {
        updateProblemPills(data.problems);
      } else {
        moduleIds.forEach((moduleId) => {
          state.jobProblemStates[String(moduleId)] = {
            module_id: moduleId,
            status: '等待队列',
          };
        });
        renderProblems();
      }
      updateModeUI();
      updateSelectionUI();
      renderCourses();
      setBusy(false);
      schedulePoll();
    } catch (error) {
      App.toast(`启动题解模式失败: ${error.message}`, 'error');
      App.setLoading(false);
    }
  }

  /**
   * 终止当前题解任务。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function cancelSolution() {
    if (!state.jobId) {
      return;
    }
    if (els.start) {
      els.start.disabled = true;
    }
    try {
      await App.callOk('cancel_solution_job', { job_id: state.jobId });
      App.toast('正在终止解题…', 'warn');
    } catch (error) {
      App.toast(`终止解题失败: ${error.message}`, 'error');
      updateSelectionUI();
    }
  }

  /**
   * 安排下一次任务状态轮询。
   * @returns {void}
   */
  function schedulePoll() {
    if (state.jobTimer) {
      window.clearTimeout(state.jobTimer);
    }
    state.jobTimer = window.setTimeout(pollJob, 800);
  }

  /**
   * 轮询题解任务状态并更新进度。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function pollJob() {
    if (!state.jobId) {
      return;
    }
    // 同一时间只保留一条轮询链，避免重复定时器。
    if (state.jobTimer) {
      window.clearTimeout(state.jobTimer);
      state.jobTimer = null;
    }
    try {
      const job = await App.callOk('get_solution_job', { job_id: state.jobId });
      state.currentJob = job;
      updateProblemPills(job.problems);
      updateProgress(job);
      if (job.done) {
        if (state.jobTimer) {
          window.clearTimeout(state.jobTimer);
          state.jobTimer = null;
        }
        updateModeUI();
        updateSelectionUI();
        applySolutionStatuses(job.result || {});
        // 任务结束后恢复课程按钮与部分标签（尤其是切换标签/手动刷新后完成时）。
        renderCourses();
        renderParts();
        // 结果只展示一次；切换标签再回来不重复弹出。
        if (App.active === PAGE_NAME && state.resultShownJobId !== state.jobId) {
          renderSolutionResult(job.result || {});
          state.resultShownJobId = state.jobId;
        }
        return;
      }
      schedulePoll();
    } catch (error) {
      App.toast(`读取题解进度失败: ${error.message}`, 'error');
      if (state.jobTimer) {
        window.clearTimeout(state.jobTimer);
        state.jobTimer = null;
      }
    }
  }

  /**
   * 更新进度卡片。
   * @param {Object} job 任务状态。
   * @returns {void}
   */
  function updateProgress(job) {
    if (els.progressCard) {
      els.progressCard.classList.remove('hidden');
    }
    const phaseMap = {
      starting: '准备中',
      analysis: '生成思路',
      solution: '生成题解',
      done: '已完成',
      error: '失败',
      idle: '空闲',
    };
    if (els.progressPhase) {
      els.progressPhase.className = 'pill ' + (job.phase === 'done' ? 'ok' : job.phase === 'error' ? 'bad' : 'info');
      els.progressPhase.textContent = phaseMap[job.phase] || job.phase || '进行中';
    }
    if (els.progressMessage) {
      els.progressMessage.textContent = job.message || '';
    }
    const total = Number(job.total || 0);
    const current = Number(job.current || 0);
    const percent = job.done ? 100 : total > 0 ? Math.min(100, Math.round(current / total * 100)) : 0;
    if (els.progressBar) {
      els.progressBar.style.width = `${percent}%`;
    }
    if (els.progressLog) {
      const events = Array.isArray(job.events) ? job.events : [];
      els.progressLog.innerHTML = '';
      events.forEach((event) => {
        const line = node('div', `log-line ${event.level || 'info'}`, `[${event.time}] ${event.message}`);
        els.progressLog.appendChild(line);
      });
      els.progressLog.scrollTop = els.progressLog.scrollHeight;
    }
  }

  /**
   * 将题解结果写回本地题目状态。
   * @param {Object} result 任务结果。
   * @returns {void}
   */
  function applySolutionStatuses(result) {
    (result.ac || []).forEach((item) => updateProblemStatus(item.module_id, 'AC: Accepted', true));
    (result.already_ac || []).forEach((item) => updateProblemStatus(item.module_id, 'AC: Accepted', true));
    (result.failed || []).forEach((item) => updateProblemStatus(item.module_id, item.status || '未通过', true));
    renderProblems();
  }

  /**
   * 渲染题解结果弹窗。
   * @param {Object} result 任务结果。
   * @returns {void}
   */
  function renderSolutionResult(result) {
    if (!els.solutionResult) {
      return;
    }
    state.solutionItems = [];
    const ac = Array.isArray(result.ac) ? result.ac : [];
    const failed = Array.isArray(result.failed) ? result.failed : [];
    const already = Array.isArray(result.already_ac) ? result.already_ac : [];
    ac.forEach((item) => state.solutionItems.push({ kind: 'ac', data: item }));
    already.forEach((item) => state.solutionItems.push({ kind: 'already', data: item }));
    failed.forEach((item) => state.solutionItems.push({ kind: 'failed', data: item }));

    if (els.solutionList) {
      els.solutionList.innerHTML = '';
      const sections = [
        { title: `AC 题解（${ac.length}）`, kind: 'ac', items: ac },
        { title: `此前已通过（${already.length}）`, kind: 'already', items: already },
        { title: `未通过（${failed.length}）`, kind: 'failed', items: failed },
      ];
      sections.forEach((section) => {
        if (section.items.length === 0) {
          return;
        }
        els.solutionList.appendChild(node('h4', '', section.title));
        section.items.forEach((item) => {
          const index = state.solutionItems.findIndex(
            (entry) => entry.kind === section.kind && entry.data === item
          );
          const button = node('button', 'solution-item' + (section.kind === 'failed' ? ' failed' : ''), item.title || '未命名题目');
          button.type = 'button';
          button.dataset.index = String(index);
          els.solutionList.appendChild(button);
        });
      });
    }
    state.solutionIndex = 0;
    renderSolutionDetail();
    els.solutionResult.classList.remove('hidden');
    if (els.solutionResultTitle) {
      els.solutionResultTitle.textContent = '题解结果';
    }
    if (state.lastNotifiedJobId !== state.jobId) {
      state.lastNotifiedJobId = state.jobId;
      App.toast(
        `题解模式完成：AC ${ac.length} 题，失败 ${failed.length} 题，此前已通过 ${already.length} 题`,
        failed.length ? 'warn' : 'success'
      );
    }
  }

  /**
   * 渲染当前选中的题解/失败详情。
   * @returns {void}
   */
  function renderSolutionDetail() {
    const item = state.solutionItems[state.solutionIndex];
    if (!item) {
      if (els.solutionCodeTitle) {
        els.solutionCodeTitle.textContent = '没有可展示的题解';
      }
      if (els.solutionCode) {
        els.solutionCode.textContent = '';
      }
      return;
    }
    if (els.solutionList) {
      els.solutionList.querySelectorAll('.solution-item').forEach((button) => {
        button.classList.toggle('active', Number(button.dataset.index) === state.solutionIndex);
      });
    }
    if (els.solutionResultTitle) {
      els.solutionResultTitle.textContent = item.kind === 'ac'
        ? `${item.data.title}-AC题解范例`
        : '题解结果';
    }
    if (els.solutionWarning) {
      els.solutionWarning.textContent =
        '题解模式仅建议在十分需要真实实例时使用；平时请使用启发模式自行完成。';
    }
    if (els.solutionCodeTitle) {
      els.solutionCodeTitle.textContent = item.kind === 'ac'
        ? `${item.data.title}-AC题解范例`
        : `${item.data.title}（${item.kind === 'already' ? '此前已通过' : '未通过'}）`;
    }
    if (item.kind === 'ac') {
      if (els.solutionExplanation) {
        els.solutionExplanation.textContent = item.data.explanation || '';
      }
      if (els.solutionCode) {
        els.solutionCode.textContent = item.data.code || '';
        els.solutionCode.classList.remove('hidden');
      }
      if (els.solutionNotes) {
        els.solutionNotes.textContent = item.data.notes || '';
      }
    } else if (item.kind === 'failed') {
      if (els.solutionExplanation) {
        els.solutionExplanation.textContent =
          `状态：${item.data.status || '未通过'}\n${item.data.summary || ''}` +
          (item.data.compile_message ? `\n\n编译信息：\n${item.data.compile_message}` : '');
      }
      if (els.solutionCode) {
        els.solutionCode.textContent = '';
        els.solutionCode.classList.add('hidden');
      }
      if (els.solutionNotes) {
        els.solutionNotes.textContent = `已尝试 ${item.data.attempts || 0} 次。`;
      }
    } else {
      if (els.solutionExplanation) {
        els.solutionExplanation.textContent = '该题此前已经 AC，无需再次生成题解。';
      }
      if (els.solutionCode) {
        els.solutionCode.textContent = '';
        els.solutionCode.classList.add('hidden');
      }
      if (els.solutionNotes) {
        els.solutionNotes.textContent = '';
      }
    }
  }

  /**
   * 启动当前模式。
   * @returns {void}
   */
  function startLearning() {
    if (state.selected.size === 0) {
      App.toast('请先选择题目', 'warn');
      return;
    }
    if (state.mode === 'solution') {
      startSolutionMode();
    } else {
      startGuideMode();
    }
  }

  // ---------------------------------------------------------------- 事件
  /**
   * 绑定固定元素事件。
   * @returns {void}
   */
  function bindEvents() {
    if (els.openSettings) {
      els.openSettings.addEventListener('click', () => {
        // 跳到 C 程序设计对应的设置板块。
        App.openSettings('c_programming');
      });
    }
    if (els.refreshCourses) {
      els.refreshCourses.addEventListener('click', async () => {
        if (state.busy || jobRunning()) {
          return;
        }
        setBusy(true, '正在刷新课程…');
        try {
          await loadCourses(false);
        } finally {
          setBusy(false);
        }
      });
    }
    if (els.courseList) {
      els.courseList.addEventListener('click', (event) => {
        const button = event.target.closest('.course-item');
        if (!button || state.busy || jobRunning()) {
          return;
        }
        selectCourse(Number(button.dataset.courseId));
      });
    }
    if (els.partTabs) {
      els.partTabs.addEventListener('click', (event) => {
        const button = event.target.closest('.part-tab');
        if (!button || state.busy || jobRunning()) {
          return;
        }
        state.activePartIndex = Number(button.dataset.partIndex);
        state.selected.clear();
        renderParts();
        renderProblems();
      });
    }
    if (els.problemBody) {
      els.problemBody.addEventListener('change', (event) => {
        const input = event.target;
        if (!input || input.type !== 'checkbox' || !input.dataset.moduleId) {
          return;
        }
        const moduleId = Number(input.dataset.moduleId);
        if (input.checked) {
          state.selected.add(moduleId);
        } else {
          state.selected.delete(moduleId);
        }
        updateSelectionUI();
      });
    }
    if (els.selectAllInput) {
      els.selectAllInput.addEventListener('change', () => {
        selectAllUnsolved(Boolean(els.selectAllInput.checked));
      });
    }
    if (els.selectUnsolved) {
      els.selectUnsolved.addEventListener('click', () => selectAllUnsolved(true));
    }
    if (els.start) {
      els.start.addEventListener('click', () => {
        if (jobRunning()) {
          cancelSolution();
        } else {
          startLearning();
        }
      });
    }
    if (els.modeGuide) {
      els.modeGuide.addEventListener('click', () => requestMode('guide'));
    }
    if (els.modeSolution) {
      els.modeSolution.addEventListener('click', () => requestMode('solution'));
    }
    if (els.modeInfo && els.modeTooltip) {
      els.modeInfo.addEventListener('click', () => {
        els.modeTooltip.classList.toggle('hidden');
      });
    }
    if (els.solutionYes) {
      els.solutionYes.addEventListener('click', () => {
        if (els.solutionConfirm) {
          els.solutionConfirm.classList.add('hidden');
        }
        if (state.solutionEnabled) {
          state.mode = 'solution';
          updateModeUI();
          App.toast('已进入题解模式，请确认题目后点击“开始学习”。', 'warn');
        }
      });
    }
    if (els.solutionNo) {
      els.solutionNo.addEventListener('click', () => {
        if (els.solutionConfirm) {
          els.solutionConfirm.classList.add('hidden');
        }
        state.mode = 'guide';
        updateModeUI();
      });
    }
    if (els.analysisClose) {
      els.analysisClose.addEventListener('click', closeAnalysis);
    }
    if (els.analysisPrev) {
      els.analysisPrev.addEventListener('click', () => {
        if (state.analysisStep > 0) {
          state.analysisStep -= 1;
          renderAnalysis();
        }
      });
    }
    if (els.analysisNext) {
      els.analysisNext.addEventListener('click', () => {
        if (state.analysisStep < 3) {
          state.analysisStep += 1;
          renderAnalysis();
        }
      });
    }
    if (els.analysisStepper) {
      els.analysisStepper.addEventListener('click', (event) => {
        const button = event.target.closest('.step');
        if (!button) {
          return;
        }
        const step = Number(button.dataset.step);
        if (step >= 0 && step <= 3) {
          state.analysisStep = step;
          renderAnalysis();
        }
      });
    }
    if (els.solutionResultClose) {
      els.solutionResultClose.addEventListener('click', () => {
        if (els.solutionResult) {
          els.solutionResult.classList.add('hidden');
        }
      });
    }
    if (els.solutionList) {
      els.solutionList.addEventListener('click', (event) => {
        const button = event.target.closest('.solution-item');
        if (!button) {
          return;
        }
        state.solutionIndex = Number(button.dataset.index);
        renderSolutionDetail();
      });
    }
    if (els.solutionResult) {
      els.solutionResult.addEventListener('click', (event) => {
        if (event.target === els.solutionResult) {
          els.solutionResult.classList.add('hidden');
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
    if (els.analysisModal) {
      els.analysisModal.classList.add('hidden');
    }
    if (els.solutionConfirm) {
      els.solutionConfirm.classList.add('hidden');
    }
    if (els.solutionResult) {
      els.solutionResult.classList.add('hidden');
    }
    if (state.keydownHandler) {
      document.removeEventListener('keydown', state.keydownHandler);
    }
    state.keydownHandler = (event) => {
      if (event.key !== 'Escape') {
        return;
      }
      if (els.solutionResult && !els.solutionResult.classList.contains('hidden')) {
        els.solutionResult.classList.add('hidden');
        return;
      }
      if (els.analysisModal && !els.analysisModal.classList.contains('hidden')) {
        closeAnalysis();
      }
    };
    document.addEventListener('keydown', state.keydownHandler);
    state.initialized = true;
  }

  /**
   * 每次切换到本标签时刷新状态、课程与题目。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function onActivate() {
    if (!state.initialized) {
      return;
    }
    try {
      await refreshState();
    } catch (error) {
      App.toast(`读取 C 程序设计状态失败: ${error.message}`, 'error');
      return;
    }
    // 标签切换会重新注入 HTML；先恢复缓存的课程、部分与题目。
    if (state.courses.length === 0) {
      await loadCourses(false);
      return;
    }
    // 未完成任务或尚未展示结果时先轮询一次，更新 currentJob 后再统一渲染。
    if (state.jobId && (!state.currentJob || state.currentJob.running
        || state.resultShownJobId !== state.jobId)) {
      await pollJob();
    }
    renderCachedView();
  }

  /**
   * 根据内存中的课程/部分/题目状态重新渲染当前页面。
   * 标签切换会重建 DOM，必须重新渲染，否则课程与部分标签会消失。
   * @returns {void}
   */
  function renderCachedView() {
    renderCourses();
    if (state.structure) {
      renderParts();
      renderProblems();
    }
    updateSelectionUI();
    updateModeUI();
  }

  App.registerPage(PAGE_NAME, { init: init, onActivate: onActivate });
})();
