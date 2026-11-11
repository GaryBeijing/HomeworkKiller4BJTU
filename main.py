# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-11 21:00
# 文件名: main.py
# 主要用途: 项目唯一入口：清理未完成更新 staging，创建并启动 HomeworkKiller4BJTU 主窗口。
# 文件版本: 4.5.0
"""HomeworkKiller4BJTU 入口。

本文件只负责实例化 :class:`hwklr.UI.WindowView` 并启动事件循环，
不承载任何业务逻辑。
"""
from __future__ import annotations

import logging

from hwklr.UI import WindowView
from hwklr.updater import bootstrap_current_version, cleanup_incomplete_update

__version__ = "4.5.0"
__all__ = ["main"]

_LOGGER: logging.Logger = logging.getLogger(__name__)


def main() -> None:
    """启动应用主窗口。

    所有 UI、功能与配置逻辑均由 ``hwklr`` 包实现；此函数仅做最外层启动。
    """
    # 清理上一次异常中断留下的 staging；版本化安装不会在启动时覆盖运行中的程序。
    cleanup_incomplete_update()
    # 若 current.json 指向另一个已安装版本，先启动它并退出（launcher 未接入时的兜底）。
    if bootstrap_current_version():
        return
    # 关键步骤：创建窗口（内部完成标签注册、服务端口选择与 pywebview 初始化）。
    window_view: WindowView = WindowView()
    window_view.run()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        main()
    except Exception:
        _LOGGER.exception("应用启动失败")
        raise
