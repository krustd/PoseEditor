"""负责图像显示与关键点交互的画布控件。"""

from typing import Optional

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from ..models import Keypoint, PoseData
from ..undo import KeypointChangeCommand, UndoStack


class Canvas(QWidget):
    keypoint_selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.image: Optional[QImage] = None
        self.pose_data = PoseData()
        self.scale = 1.0
        self.offset = QPointF(0, 0)
        self.selected_keypoint: Optional[Keypoint] = None
        self.dragging = False
        self.panning = False
        self.last_pos = QPointF()
        self.show_skeleton = True
        self.keypoint_opacity = 1.0
        self.undo_stack = UndoStack()
        self.drag_start_pos: Optional[QPointF] = None

        self.skeleton = [
            (0, 1),
            (0, 2),
            (1, 3),
            (2, 4),
            (5, 6),
            (5, 7),
            (7, 9),
            (6, 8),
            (8, 10),
            (5, 11),
            (6, 12),
            (11, 12),
            (11, 13),
            (13, 15),
            (12, 14),
            (14, 16),
        ]

        self.setMinimumSize(800, 600)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_image(self, image: QImage):
        self.image = image
        self.update()

    def set_pose_data(self, pose_data: PoseData):
        self.pose_data = pose_data
        self.update()

    def fit_to_window(self):
        """适应窗口大小 (显示全图)"""
        if not self.image:
            return
        widget_size = self.size()
        image_size = self.image.size()
        scale_x = widget_size.width() / image_size.width()
        scale_y = widget_size.height() / image_size.height()
        self.scale = min(scale_x, scale_y) * 0.9
        scaled_size = image_size * self.scale
        self.offset = QPointF(
            (widget_size.width() - scaled_size.width()) / 2,
            (widget_size.height() - scaled_size.height()) / 2,
        )
        self.update()

    def focus_on_pose(self):
        """聚焦于姿态所在的局部区域"""
        if not self.image or not self.pose_data.has_valid_keypoints():
            self.fit_to_window()
            return

        min_x, min_y, max_x, max_y = self.pose_data.get_bounding_box()

        bbox_w = max_x - min_x
        bbox_h = max_y - min_y

        if bbox_w < 10 or bbox_h < 10:
            self.fit_to_window()
            return

        padding_x = bbox_w * 0.5
        padding_y = bbox_h * 0.5

        target_x = min_x - padding_x / 2
        target_y = min_y - padding_y / 2
        target_w = bbox_w + padding_x
        target_h = bbox_h + padding_y

        widget_size = self.size()

        scale_x = widget_size.width() / target_w
        scale_y = widget_size.height() / target_h
        new_scale = min(scale_x, scale_y)

        self.scale = min(new_scale, 5.0)

        center_x = target_x + target_w / 2
        center_y = target_y + target_h / 2

        self.offset = QPointF(
            widget_size.width() / 2 - center_x * self.scale,
            widget_size.height() / 2 - center_y * self.scale,
        )

        self.update()

    def image_to_widget(self, point: QPointF) -> QPointF:
        return QPointF(
            point.x() * self.scale + self.offset.x(),
            point.y() * self.scale + self.offset.y(),
        )

    def widget_to_image(self, point: QPointF) -> QPointF:
        return QPointF(
            (point.x() - self.offset.x()) / self.scale,
            (point.y() - self.offset.y()) / self.scale,
        )

    def get_keypoint_at(self, pos: QPointF) -> Optional[Keypoint]:
        if not self.image:
            return None
        for kp in self.pose_data.keypoints:
            kp_pos = self.image_to_widget(QPointF(kp.x, kp.y))
            distance = (kp_pos - pos).manhattanLength()
            if distance < 10:
                return kp
        return None

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(50, 50, 50))

        if not self.image:
            return

        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        painter.drawImage(0, 0, self.image)
        painter.restore()

        if self.show_skeleton:
            self.draw_skeleton(painter)
        self.draw_keypoints(painter)

    # 骨骼连接的颜色分类
    SKELETON_COLORS = {
        (0, 1): QColor(100, 200, 100, 150),
        (0, 2): QColor(100, 200, 100, 150),
        (5, 6): QColor(100, 200, 100, 150),
        (11, 12): QColor(100, 200, 100, 150),
        (1, 3): QColor(255, 120, 100, 150),
        (5, 7): QColor(255, 120, 100, 150),
        (7, 9): QColor(255, 150, 80, 150),
        (5, 11): QColor(230, 100, 70, 150),
        (11, 13): QColor(230, 120, 80, 150),
        (13, 15): QColor(240, 150, 90, 150),
        (2, 4): QColor(80, 160, 255, 150),
        (6, 8): QColor(80, 160, 255, 150),
        (8, 10): QColor(110, 190, 255, 150),
        (6, 12): QColor(70, 120, 230, 150),
        (12, 14): QColor(90, 140, 240, 150),
        (14, 16): QColor(120, 170, 245, 150),
    }

    def draw_skeleton(self, painter: QPainter):
        if not self.image:
            return
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        for start_idx, end_idx in self.skeleton:
            start_kp = self.pose_data.keypoints[start_idx]
            end_kp = self.pose_data.keypoints[end_idx]
            color = self.SKELETON_COLORS.get(
                (start_idx, end_idx), QColor(100, 200, 100, 150)
            )
            painter.setPen(QPen(color, 2))
            painter.drawLine(
                QPointF(start_kp.x, start_kp.y), QPointF(end_kp.x, end_kp.y)
            )
        painter.restore()

    KEYPOINT_COLORS = {
        0: QColor(100, 220, 100),
        1: QColor(255, 120, 120),
        3: QColor(255, 80, 80),
        5: QColor(255, 100, 50),
        7: QColor(255, 140, 60),
        9: QColor(255, 180, 80),
        11: QColor(220, 80, 60),
        13: QColor(230, 120, 80),
        15: QColor(240, 160, 100),
        2: QColor(100, 180, 255),
        4: QColor(60, 140, 255),
        6: QColor(80, 120, 255),
        8: QColor(100, 160, 240),
        10: QColor(130, 200, 255),
        12: QColor(80, 80, 220),
        14: QColor(100, 120, 230),
        16: QColor(140, 160, 240),
    }

    def draw_keypoints(self, painter: QPainter):
        if not self.image:
            return
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)

        selected_color = QColor(255, 255, 0)
        selected_border = QColor(0, 0, 0)
        normal_border = QColor(0, 0, 0)

        for i, kp in enumerate(self.pose_data.keypoints):
            is_selected = self.selected_keypoint == kp
            base_color = self.KEYPOINT_COLORS.get(i, QColor(200, 200, 200))
            base_color.setAlpha(int(255 * self.keypoint_opacity))
            fill_color = selected_color if is_selected else base_color
            border_color = selected_border if is_selected else normal_border

            radius = 5 / self.scale
            pen_width = 1.5 / self.scale

            if kp.visibility == 1:
                painter.setBrush(QBrush(fill_color))
                painter.setPen(QPen(border_color, pen_width))
                painter.drawEllipse(QPointF(kp.x, kp.y), radius, radius)

            elif kp.visibility == 0:
                cross_size = radius * 0.9
                cross_pen = QPen(fill_color, pen_width * 2)
                cross_pen.setCapStyle(Qt.RoundCap)
                painter.setPen(cross_pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawLine(
                    QPointF(kp.x - cross_size, kp.y - cross_size),
                    QPointF(kp.x + cross_size, kp.y + cross_size),
                )
                painter.drawLine(
                    QPointF(kp.x - cross_size, kp.y + cross_size),
                    QPointF(kp.x + cross_size, kp.y - cross_size),
                )

        painter.restore()

    @staticmethod
    def _state_changed(old_state: Keypoint, new_state: Keypoint) -> bool:
        return (
            old_state.x != new_state.x
            or old_state.y != new_state.y
            or old_state.visibility != new_state.visibility
        )

    def _push_keypoint_change(
        self,
        keypoint_index: int,
        old_state: Keypoint,
        new_state: Keypoint,
    ) -> bool:
        # 位置与可见性都没有变化时，不产生撤销记录，避免历史污染。
        if not self._state_changed(old_state, new_state):
            return False
        command = KeypointChangeCommand(
            self.pose_data,
            keypoint_index,
            old_state,
            new_state,
        )
        self.undo_stack.push(command)
        return True

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if event.modifiers() & Qt.ControlModifier:
                if self.selected_keypoint:
                    image_pos = self.widget_to_image(event.pos())
                    keypoint_index = self.pose_data.keypoints.index(
                        self.selected_keypoint
                    )
                    old_state = self.selected_keypoint.copy()

                    self.selected_keypoint.x = image_pos.x()
                    self.selected_keypoint.y = image_pos.y()
                    self.selected_keypoint.visibility = 1

                    new_state = self.selected_keypoint.copy()
                    self._push_keypoint_change(keypoint_index, old_state, new_state)
                    self.update()
                    return

            self.selected_keypoint = self.get_keypoint_at(event.pos())
            if self.selected_keypoint:
                self.dragging = True
                self.drag_start_pos = QPointF(
                    self.selected_keypoint.x, self.selected_keypoint.y
                )
                self.keypoint_selected.emit(self.selected_keypoint.name)
            self.update()

        elif event.button() == Qt.RightButton:
            self.panning = True
            self.last_pos = event.pos()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging and self.selected_keypoint:
            image_pos = self.widget_to_image(event.pos())
            self.selected_keypoint.x = image_pos.x()
            self.selected_keypoint.y = image_pos.y()
            self.update()
        elif self.panning:
            delta = event.pos() - self.last_pos
            self.offset += delta
            self.last_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if (
            event.button() == Qt.LeftButton
            and self.dragging
            and self.selected_keypoint
            and self.drag_start_pos
        ):
            keypoint_index = self.pose_data.keypoints.index(self.selected_keypoint)
            old_state = Keypoint(
                self.selected_keypoint.name,
                self.drag_start_pos.x(),
                self.drag_start_pos.y(),
                self.selected_keypoint.visibility,
            )
            new_state = self.selected_keypoint.copy()
            self._push_keypoint_change(keypoint_index, old_state, new_state)
            self.dragging = False
            self.drag_start_pos = None
        elif event.button() == Qt.LeftButton:
            self.dragging = False
        elif event.button() == Qt.RightButton:
            self.panning = False

    def wheelEvent(self, event: QWheelEvent):
        if not self.image:
            return
        mouse_pos = event.position()
        image_pos_before = self.widget_to_image(mouse_pos)
        delta = event.angleDelta().y() / 120
        scale_factor = 1.1 if delta > 0 else 0.9
        new_scale = self.scale * scale_factor

        if 0.1 <= new_scale <= 20.0:
            # 计算缩放前后的差异，并调整偏移量以保持鼠标位置不变
            offset_delta = QPointF(
                (image_pos_before.x() * (new_scale - self.scale)),
                (image_pos_before.y() * (new_scale - self.scale)),
            )
            self.scale = new_scale
            self.offset -= offset_delta
            self.update()

    def keyPressEvent(self, event: QKeyEvent):
        if not self.selected_keypoint:
            return
        key = event.key()
        keypoint_index = self.pose_data.keypoints.index(self.selected_keypoint)
        old_state = self.selected_keypoint.copy()

        if key in [Qt.Key_S, Qt.Key_D, Qt.Key_Space]:
            if key == Qt.Key_S:
                self.selected_keypoint.visibility = 0
            elif key == Qt.Key_D:
                self.selected_keypoint.visibility = 1
            elif key == Qt.Key_Space:
                self.selected_keypoint.visibility = (
                    1 - self.selected_keypoint.visibility
                )

            new_state = self.selected_keypoint.copy()
            self._push_keypoint_change(keypoint_index, old_state, new_state)
            self.update()
