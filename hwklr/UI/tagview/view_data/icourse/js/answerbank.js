/*
  作者: Gary
  编写日期: 2026-11-16 20:30
  最后更新: 2026-11-16 20:30
  文件名: answerbank.js
  主要用途: “中国大学慕课”题库浏览/搜索弹窗与课程目录后台刷新。
  文件版本: 4.6.7
*/
(function (global) {
  'use strict';
  const IC = global.Icourse = global.Icourse || {};
  const state = IC.state;
  const els = IC.els;
  const node = (...args) => IC.node(...args);

  IC.openAnswerBank = async function () {
    if (!state.course || !state.course.course) {
      App.toast('请先选择课程', 'warn');
      return;
    }
    if (els['i-bank-modal']) {
      els['i-bank-modal'].classList.remove('hidden');
    }
    if (els['i-bank-search']) {
      els['i-bank-search'].value = '';
    }
    state.bank = null;
    await IC.loadAnswerBank();
  };

  IC.hideAnswerBank = function () {
    if (els['i-bank-modal']) {
      els['i-bank-modal'].classList.add('hidden');
    }
  };

  IC.loadAnswerBank = async function () {
    if (!state.course || !state.course.course) {
      return;
    }
    const termId = Number(state.course.course.term_id || 0);
    const testId = Number((els['i-bank-test'] && els['i-bank-test'].value) || 0);
    const query = ((els['i-bank-search'] && els['i-bank-search'].value) || '').trim();
    if (els['i-bank-status']) {
      els['i-bank-status'].textContent = '正在读取题库…';
    }
    if (els['i-bank-list']) {
      els['i-bank-list'].innerHTML = '';
    }
    try {
      const data = await App.callOk('get_answer_bank', {
        term_id: termId,
        test_id: testId,
        query,
      });
      state.bank = data;
      renderTestOptions(data.tests || []);
      renderBank(data);
    } catch (error) {
      if (els['i-bank-status']) {
        els['i-bank-status'].textContent = '读取题库失败：' + error.message;
      }
    }
  };

  function renderTestOptions(tests) {
    const select = els['i-bank-test'];
    if (!select) {
      return;
    }
    const current = select.value || '0';
    select.innerHTML = '';
    const all = document.createElement('option');
    all.value = '0';
    all.textContent = '全部测验';
    select.appendChild(all);
    tests.forEach((test) => {
      const option = document.createElement('option');
      option.value = String(test.id);
      option.textContent = test.name + '（' + String(test.question_count || 0) + ' 题）';
      select.appendChild(option);
    });
    const values = Array.prototype.map.call(select.options, (item) => item.value);
    select.value = values.indexOf(current) >= 0 ? current : '0';
  }

  function renderBank(data) {
    const host = els['i-bank-list'];
    if (!host) {
      return;
    }
    host.innerHTML = '';
    const questions = data.questions || [];
    if (els['i-bank-status']) {
      const cached = (data.tests || []).filter((test) => test.question_count > 0).length;
      els['i-bank-status'].textContent = '共 ' + String(questions.length)
        + ' 道题；已缓存 ' + String(cached) + ' 个测验'
        + (data.query ? '；关键字“' + data.query + '”' : '');
    }
    if (!questions.length) {
      host.appendChild(node('p', 'muted',
        data.tests && data.tests.length
          ? '没有匹配的题目，换个关键字试试。'
          : '该课程题库尚未同步，请先在左侧点击“同步”。'));
      return;
    }
    questions.forEach((question, index) => {
      const card = node('article', 'ic-bank-item');
      const head = node('div', 'ic-bank-item-head');
      head.appendChild(node('span', 'pill info', question.type_label || question.type));
      head.appendChild(node('span', 'ic-bank-index', '第 ' + String(index + 1) + ' 题'));
      if (question.test_name) {
        head.appendChild(node('span', 'hint ic-bank-test-name', question.test_name));
      }
      card.appendChild(head);
      card.appendChild(node('p', 'ic-bank-title', question.title || '（无题干）'));
      if (question.options && question.options.length) {
        const options = node('ul', 'ic-bank-options');
        question.options.forEach((option, optionIndex) => {
          const item = node('li', option.answer ? 'correct' : '');
          const letter = String.fromCharCode(65 + optionIndex);
          item.appendChild(node('span', 'ic-bank-letter', letter + '.'));
          item.appendChild(node('span', '', option.text));
          if (option.answer) {
            item.appendChild(node('span', 'ic-bank-correct-mark', ' ✓'));
          }
          options.appendChild(item);
        });
        card.appendChild(options);
      }
      const answer = node('p', 'ic-bank-answer');
      answer.appendChild(node('strong', '', '答案：'));
      answer.appendChild(document.createTextNode(question.answer || '（题库未提供答案）'));
      card.appendChild(answer);
      host.appendChild(card);
    });
  }

  IC.startCatalogRefresh = async function () {
    const button = els['i-refresh-catalog'];
    if (button) {
      button.disabled = true;
      button.textContent = '更新中…';
    }
    try {
      const data = await App.callOk('start_catalog_refresh');
      await IC.pollCatalogRefresh(data.refresh || {});
    } catch (error) {
      if (button) {
        button.disabled = false;
        button.textContent = '更新目录';
      }
      App.toast('更新课程目录失败：' + error.message, 'error');
    }
  };

  IC.pollCatalogRefresh = async function (initial) {
    const button = els['i-refresh-catalog'];
    let snapshot = initial || {};
    if (snapshot.running) {
      if (button) {
        const total = Number(snapshot.total_pages || 0);
        button.textContent = total
          ? '目录 ' + String(snapshot.page || 0) + '/' + String(total)
          : '更新中…';
      }
      state.catalogTimer = window.setTimeout(async () => {
        try {
          const next = await App.callOk('get_catalog_refresh');
          await IC.pollCatalogRefresh(next);
        } catch (error) {
          if (button) {
            button.disabled = false;
            button.textContent = '更新目录';
          }
          App.toast('读取目录刷新进度失败：' + error.message, 'error');
        }
      }, 1200);
      return;
    }
    if (state.catalogTimer) {
      window.clearTimeout(state.catalogTimer);
      state.catalogTimer = null;
    }
    if (button) {
      button.disabled = false;
      button.textContent = '更新目录';
    }
    if (snapshot.error) {
      App.toast('课程目录刷新失败：' + snapshot.error, 'error');
      return;
    }
    if (snapshot.cancelled) {
      App.toast('课程目录刷新已取消', 'warn');
      return;
    }
    if (snapshot.done) {
      App.toast('课程目录已更新，共 ' + String(snapshot.fetched || 0) + ' 门', 'success');
      if (state.loggedIn) {
        await IC.loadCourses(false);
      }
      await IC.refreshState();
    }
  };

})(window);
