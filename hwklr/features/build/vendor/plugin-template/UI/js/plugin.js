/*
  作者: Gary
  编写日期: 2026-11-03 20:15
  文件名: plugin.js
  主要用途: 插件工程模板页面逻辑：注册页面并处理“让我们开始建造🔨”按钮。
  文件版本: 1.0.0
*/

(function () {
  'use strict';

  const PAGE_NAME = '__FEATURE_NAME__';

  /**
   * 页面初始化。
   * @param {HTMLElement} container 内容容器。
   * @returns {void}
   */
  function init(container) {
    const button = document.getElementById('plugin-template-start');
    if (button) {
      button.addEventListener('click', () => {
        App.callOk('hello')
          .then((data) => App.toast((data && data.message) || '开始建造吧！', 'success'))
          .catch((error) => App.toast(`调用失败: ${error.message}`, 'error'));
      });
    }
  }

  /**
   * 每次切换到本标签时的回调。
   * @returns {void}
   */
  function onActivate() {
    // 示例插件没有需要刷新后的端数据。
  }

  App.registerPage(PAGE_NAME, { init: init, onActivate: onActivate });
})();
