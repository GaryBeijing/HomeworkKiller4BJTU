/*
  作者: Gary
  编写日期: 2026-11-12 13:00
  最后更新: 2026-11-12 13:00
  文件名: welcome.js
  主要用途: 首次启动/版本升级欢迎弹窗：展示协议与更新说明，确认后记录当前版本。
  文件版本: 4.6.1
*/

(function () {
  'use strict';

  /** 弹窗运行时状态。 */
  const state = {
    payload: null,
    page: 0,
    backdrop: null,
    closing: false,
  };

  /**
   * 创建带类名与文本的 DOM 节点。
   * @param {string} tagName 标签名。
   * @param {string} [className] 类名。
   * @param {string} [text] 文本内容。
   * @returns {HTMLElement} 新节点。
   */
  function node(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    if (text !== undefined) {
      element.textContent = text;
    }
    return element;
  }

  /**
   * 创建一条横向分界线。
   * @returns {HTMLHRElement} 分界线元素。
   */
  function divider() {
    return node('hr', 'welcome-divider');
  }

  /**
   * 请求 JSON 数据。
   * @param {string} url 请求地址。
   * @returns {Promise<any>} 解析后的 JSON。
   */
  async function fetchJson(url) {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`请求失败 (${response.status}): ${url}`);
    }
    return response.json();
  }

  /**
   * 构建欢迎弹窗头部。
   * @param {Object} payload 后端返回的欢迎数据。
   * @returns {HTMLElement} 头部节点。
   */
  function buildHeader(payload) {
    const header = node('header', 'welcome-header');
    header.appendChild(
      node('h2', 'welcome-title', payload.title || '欢迎使用北交作业助手！')
    );
    header.appendChild(
      node(
        'p',
        'welcome-subtitle',
        payload.subtitle || '让我们共创北交美好生活( •̀ᴗ•́ )و'
      )
    );
    return header;
  }

  /**
   * 构建协议页内容。
   * @param {Object} payload 后端返回的欢迎数据。
   * @returns {HTMLElement} 协议页节点。
   */
  function buildAgreementPage(payload) {
    const page = node('section', 'welcome-page');
    page.setAttribute('data-page', 'agreement');
    page.appendChild(
      node(
        'p',
        'welcome-prompt',
        payload.agreement_heading || '使用本软件前，您需要知悉我们的协议：'
      )
    );
    const scroll = node('div', 'welcome-scroll');
    const text = node(
      'pre',
      'welcome-agreement-text',
      payload.agreement || '暂无协议内容。'
    );
    scroll.appendChild(text);
    page.appendChild(scroll);
    page.appendChild(divider());
    const footer = node('div', 'welcome-footer');
    const agree = node('button', 'btn primary', '我已知悉并同意');
    agree.type = 'button';
    agree.addEventListener('click', () => showPage(1));
    footer.appendChild(agree);
    page.appendChild(footer);
    return page;
  }

  /**
   * 构建更新说明页内容。
   * @param {Object} payload 后端返回的欢迎数据。
   * @returns {HTMLElement} 更新说明页节点。
   */
  function buildChangelogPage(payload) {
    const page = node('section', 'welcome-page hidden');
    page.setAttribute('data-page', 'changelog');
    page.appendChild(
      node('p', 'welcome-prompt', payload.updates_heading || '新功能一览！！')
    );
    const scroll = node('div', 'welcome-scroll welcome-changelog');
    const groups = Array.isArray(payload.changelog) ? payload.changelog : [];
    if (groups.length === 0) {
      scroll.appendChild(node('p', 'welcome-empty', '暂无更新说明。'));
    } else {
      // 步骤 1：按“分类标题 + 条目列表”渲染，标题前使用需求约定的圆点。
      groups.forEach((group) => {
        const block = node('div', 'welcome-changelog-group');
        block.appendChild(
          node('div', 'welcome-changelog-title', `· ${group.title || '更新内容'}`)
        );
        const list = node('ul', 'welcome-changelog-list');
        const items = Array.isArray(group.items) ? group.items : [];
        if (items.length === 0) {
          items.push('细节优化与问题修复');
        }
        items.forEach((item) => list.appendChild(node('li', '', String(item))));
        block.appendChild(list);
        scroll.appendChild(block);
      });
    }
    page.appendChild(scroll);
    page.appendChild(divider());
    const footer = node('div', 'welcome-footer');
    const start = node('button', 'btn primary', '知道了，开始使用→');
    start.type = 'button';
    start.addEventListener('click', () => {
      dismiss().catch((error) => console.error(error));
    });
    footer.appendChild(start);
    page.appendChild(footer);
    return page;
  }

  /**
   * 切换当前显示的页面。
   * @param {number} index 页面序号（0 协议，1 更新说明）。
   * @returns {void}
   */
  function showPage(index) {
    state.page = index === 1 ? 1 : 0;
    if (!state.backdrop) {
      return;
    }
    const pages = state.backdrop.querySelectorAll('.welcome-page');
    pages.forEach((page) => {
      const active = Number(page.getAttribute('data-page') === 'changelog');
      page.classList.toggle('hidden', active !== state.page);
    });
    const activePage = pages[state.page];
    if (activePage) {
      const button = activePage.querySelector('.welcome-footer .btn');
      if (button) {
        button.focus({ preventScroll: true });
      }
    }
  }

  /**
   * 等待 pywebview 桥接就绪。
   * @param {number} [timeout] 最长等待毫秒数。
   * @returns {Promise<boolean>} 桥接可用时 resolve true。
   */
  function waitForBridge(timeout) {
    if (window.pywebview && window.pywebview.api) {
      return Promise.resolve(true);
    }
    return new Promise((resolve) => {
      const timer = window.setTimeout(() => resolve(false), timeout || 3000);
      window.addEventListener(
        'pywebviewready',
        () => {
          window.clearTimeout(timer);
          resolve(Boolean(window.pywebview && window.pywebview.api));
        },
        { once: true }
      );
    });
  }

  /**
   * 移除弹窗并把当前版本记录为已确认。
   * @returns {Promise<void>} 关闭完成时 resolve。
   */
  async function dismiss() {
    if (state.closing) {
      return;
    }
    state.closing = true;
    const version = state.payload ? String(state.payload.version || '') : '';
    // 步骤 1：先写入配置；桥接失败也不阻塞关闭，下次启动会再次提示。
    try {
      const ready = await waitForBridge(3000);
      if (
        ready &&
        window.pywebview &&
        window.pywebview.api &&
        typeof window.pywebview.api.dismiss_welcome === 'function'
      ) {
        await window.pywebview.api.dismiss_welcome(version);
      }
    } catch (error) {
      console.error(error);
    }
    // 步骤 2：淡出并移除遮罩。
    const backdrop = state.backdrop;
    state.backdrop = null;
    state.payload = null;
    if (backdrop) {
      backdrop.classList.add('hidden');
      window.setTimeout(() => backdrop.remove(), 260);
    }
  }

  /**
   * 构建并插入欢迎弹窗。
   * @param {Object} payload 后端返回的欢迎数据。
   * @returns {void}
   */
  function render(payload) {
    const backdrop = node('div', 'modal-backdrop welcome-backdrop');
    const modal = node('div', 'modal welcome-modal');
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-label', payload.title || '欢迎使用北交作业助手');
    modal.appendChild(buildHeader(payload));
    modal.appendChild(divider());
    const pages = node('div', 'welcome-pages');
    pages.appendChild(buildAgreementPage(payload));
    pages.appendChild(buildChangelogPage(payload));
    modal.appendChild(pages);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    state.backdrop = backdrop;
    state.page = 0;
    showPage(0);
  }

  /**
   * 查询是否需要展示欢迎弹窗；需要时渲染。
   * @returns {Promise<void>} 处理完成时 resolve。
   */
  async function maybeShow() {
    if (state.backdrop) {
      return;
    }
    let payload = null;
    try {
      payload = await fetchJson('/api/welcome');
    } catch (error) {
      console.error(error);
      return;
    }
    if (!payload || payload.show !== true) {
      return;
    }
    state.payload = payload;
    state.closing = false;
    render(payload);
  }

  // 暴露给 base.js：首屏激活完成后调用。
  window.Welcome = {
    maybeShow: maybeShow,
  };
})();
