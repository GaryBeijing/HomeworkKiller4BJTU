/*
  作者: Gary
  编写日期: 2026-10-31 20:45
  最后更新: 2026-11-03 21:50
  文件名: about.js
  主要用途: “关于”页面逻辑：填充软件信息、插件元信息表、功能列表与声明。
  文件版本: 3.0.0
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
    els.plugins = document.getElementById('about-plugins');
  }

  /**
   * 创建表格单元格。
   * @param {string} text 文本。
   * @param {string} [className] 类名。
   * @returns {HTMLTableCellElement} 单元格。
   */
  function cell(text, className) {
    const node = document.createElement('td');
    if (className) {
      node.className = className;
    }
    node.textContent = String(text === undefined || text === null ? '—' : text);
    return node;
  }

  /**
   * 渲染插件元信息表。
   * @param {Array<Object>} plugins 插件元信息。
   * @returns {void}
   */
  function renderPlugins(plugins) {
    if (!els.plugins) {
      return;
    }
    els.plugins.innerHTML = '';
    if (!Array.isArray(plugins) || plugins.length === 0) {
      const row = document.createElement('tr');
      const empty = document.createElement('td');
      empty.colSpan = 6;
      empty.className = 'table-empty';
      empty.textContent = '暂无插件信息。';
      row.appendChild(empty);
      els.plugins.appendChild(row);
      return;
    }
    plugins.forEach((plugin) => {
      const row = document.createElement('tr');
      row.appendChild(cell(plugin.name, 'plugin-name'));
      row.appendChild(cell(plugin.package_display, 'mono'));
      row.appendChild(cell(plugin.author));
      row.appendChild(cell(plugin.version_display, 'mono'));
      row.appendChild(cell(plugin.update_date));
      const stateCell = document.createElement('td');
      const badge = document.createElement('span');
      badge.className = 'plugin-state ' + (plugin.enabled ? 'on' : 'off');
      badge.textContent = plugin.enabled ? '已启用' : '已停用';
      stateCell.appendChild(badge);
      row.appendChild(stateCell);
      els.plugins.appendChild(row);
    });
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
    const version = String(meta.version_display || meta.version || '—');
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
      const software = meta.software && typeof meta.software === 'object' ? meta.software : {};
      els.authors.textContent = software.author
        ? String(software.author)
        : authors.length > 0
          ? authors.join('、')
          : '—';
    }
    if (els.disclaimer) {
      els.disclaimer.textContent = String(meta.disclaimer || '');
    }
    renderFeatures(meta.features || []);
    renderPlugins(meta.plugins || []);
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
