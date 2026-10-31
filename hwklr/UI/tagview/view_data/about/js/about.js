/*
  作者: Gary
  编写日期: 2026-10-31 20:45
  文件名: about.js
  主要用途: “关于”页面逻辑：填充应用名称、版本、作者、描述、功能列表与声明。
  文件版本: 1.0.0
*/

(function () {
  'use strict';

  const PAGE_NAME = '关于';

  /** 页面元素缓存。 */
  const els = {};

  /**
   * 缓存页面元素引用。
   * @returns {void}
   */
  function cacheElements() {
    els.name = document.getElementById('about-name');
    els.description = document.getElementById('about-description');
    els.version = document.getElementById('about-version');
    els.versionBadge = document.getElementById('about-version-badge');
    els.authors = document.getElementById('about-authors');
    els.features = document.getElementById('about-features');
    els.disclaimer = document.getElementById('about-disclaimer');
  }

  /**
   * 渲染功能列表。
   * @param {Array<{name: string, description: string}>} features 功能列表。
   * @returns {void}
   */
  function renderFeatures(features) {
    if (!els.features) {
      return;
    }
    els.features.innerHTML = '';
    if (!Array.isArray(features) || features.length === 0) {
      const item = document.createElement('li');
      item.className = 'muted';
      item.textContent = '暂无功能信息。';
      els.features.appendChild(item);
      return;
    }
    features.forEach((feature) => {
      const item = document.createElement('li');
      const title = document.createElement('strong');
      title.textContent = String(feature.name || '未命名功能');
      item.appendChild(title);
      if (feature.description) {
        const description = document.createElement('span');
        description.className = 'feature-desc';
        description.textContent = String(feature.description);
        item.appendChild(description);
      }
      els.features.appendChild(item);
    });
  }

  /**
   * 使用元信息填充页面。
   * @param {Object} meta 应用元信息。
   * @returns {void}
   */
  function renderMeta(meta) {
    const version = String(meta.version || '—');
    const authors = Array.isArray(meta.authors) ? meta.authors : [];
    if (els.name) {
      els.name.textContent = String(meta.name || 'HomeworkKiller4BJTU');
    }
    if (els.description) {
      els.description.textContent = String(meta.description || '');
    }
    if (els.version) {
      els.version.textContent = version;
    }
    if (els.versionBadge) {
      els.versionBadge.textContent = `Version ${version}`;
    }
    if (els.authors) {
      els.authors.textContent = authors.length > 0 ? authors.join('、') : '—';
    }
    if (els.disclaimer) {
      els.disclaimer.textContent = String(meta.disclaimer || '');
    }
    renderFeatures(meta.features || []);
    document.title = `${meta.name || 'HomeworkKiller4BJTU'} ${version}`;
  }

  /**
   * 页面首次初始化。
   * @param {HTMLElement} container 内容容器。
   * @returns {void}
   */
  function init(container) {
    cacheElements();
  }

  /**
   * 每次切换到本标签时读取元信息。
   * @returns {Promise<void>} 完成时 resolve。
   */
  async function onActivate() {
    try {
      const meta = await App.callOk('get_meta');
      renderMeta(meta);
    } catch (error) {
      // 桥接异常时退回到页面初始化时获取的元信息。
      if (App.meta && Object.keys(App.meta).length > 0) {
        renderMeta(App.meta);
      } else {
        App.toast(`读取应用信息失败: ${error.message}`, 'error');
      }
    }
  }

  App.registerPage(PAGE_NAME, { init: init, onActivate: onActivate });
})();
