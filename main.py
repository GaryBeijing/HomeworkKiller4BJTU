# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-11 10:00
# 文件名: main.py
# 主要用途: 项目唯一入口：应用待安装更新，创建并启动 HomeworkKiller4BJTU 主窗口。
# 文件版本: 4.4.3
"""HomeworkKiller4BJTU 入口。

本文件只负责实例化 :class:`hwklr.UI.WindowView` 并启动事件循环，
不承载任何业务逻辑。
"""
from __future__ import annotations

import logging

from hwklr.UI import WindowView
from hwklr.update_service import apply_pending_update

__version__ = "4.4.3"
__all__ = ["main"]

_LOGGER: logging.Logger = logging.getLogger(__name__)


def main() -> None:
    """启动应用主窗口。

    所有 UI、功能与配置逻辑均由 ``hwklr`` 包实现；此函数仅做最外层启动。
    """
    # 上次选择“稍后安装”时，先启动替换脚本并退出，由脚本重启新版本。
    if apply_pending_update():
        _LOGGER.info("已启动待安装更新，退出当前进程")
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
