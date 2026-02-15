"""应用程序入口。"""

import sys

from PySide6.QtWidgets import QApplication

from .main_window import PoseEditor


def main() -> None:
    # 图形应用生命周期由应用对象统一管理。
    app = QApplication(sys.argv)
    editor = PoseEditor()
    editor.show()
    # 进入事件循环并返回退出码。
    sys.exit(app.exec())
