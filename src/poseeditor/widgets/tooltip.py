"""延迟显示工具提示的辅助组件。"""

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QToolTip


class DelayedTooltipFilter(QObject):
    """事件过滤器：鼠标悬浮 2 秒后再显示工具提示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(2000)  # 2秒延迟
        self.timer.timeout.connect(self._show_tooltip)
        self.current_widget = None
        self.global_pos = None

    def _show_tooltip(self):
        if self.current_widget and self.global_pos:
            QToolTip.showText(
                self.global_pos, self.current_widget.toolTip(), self.current_widget
            )

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Enter:
            self.current_widget = obj
            self.timer.start()
        elif event.type() == QEvent.Leave:
            self.timer.stop()
            self.current_widget = None
            QToolTip.hideText()
        elif event.type() == QEvent.MouseMove:
            self.global_pos = (
                event.globalPosition().toPoint()
                if hasattr(event, "globalPosition")
                else event.globalPos()
            )
        elif event.type() == QEvent.ToolTip:
            # 阻止默认工具提示显示，改由定时器控制显示时机。
            return True
        return False
