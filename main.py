import sys
import json
import shutil
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QStatusBar, QListWidget, QListWidgetItem, QPushButton,
    QFileDialog, QMessageBox, QSplitter, QFrame, QSpinBox, QGroupBox,
    QButtonGroup, QGridLayout, QInputDialog, QToolTip
)
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QObject, QTimer, QEvent
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QBrush, QColor, 
    QMouseEvent, QKeyEvent, QWheelEvent, QAction
)


class DelayedTooltipFilter(QObject):
    """事件过滤器：鼠标悬浮2秒后才显示tooltip"""
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
            QToolTip.showText(self.global_pos, self.current_widget.toolTip(), self.current_widget)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Enter:
            self.current_widget = obj
            self.timer.start()
        elif event.type() == QEvent.Leave:
            self.timer.stop()
            self.current_widget = None
            QToolTip.hideText()
        elif event.type() == QEvent.MouseMove:
            self.global_pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
        elif event.type() == QEvent.ToolTip:
            # 阻止默认tooltip显示，由我们的timer控制
            return True
        return False


class Keypoint:
    """关键点数据模型"""
    def __init__(self, name: str, x: float = 0, y: float = 0, visibility: int = 0):
        self.name = name
        self.x = x
        self.y = y
        self.visibility = visibility  # 0: 不可见/未标记, 1: 遮挡, 2: 可见
        
    def copy(self) -> 'Keypoint':
        return Keypoint(self.name, self.x, self.y, self.visibility)
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "visibility": self.visibility
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Keypoint':
        return cls(data["name"], data["x"], data["y"], data["visibility"])


class PoseData:
    """姿态数据模型 - 支持COCO风格JSON格式"""
    
    KEYPOINT_NAMES = [
        "nose", "left_eye", "right_eye", "left_ear", "right_ear",
        "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
        "left_wrist", "right_wrist", "left_hip", "right_hip",
        "left_knee", "right_knee", "left_ankle", "right_ankle"
    ]
    
    def __init__(self):
        self.keypoints = self._init_keypoints()
        
        # 保留原始检测数据（模型输出，不可修改）
        self.raw_id = 0
        self.raw_scores = []  # 模型置信度分数
        
        # 评分字段
        self.novelty = -1              # 姿势新奇度：0到5分
        self.environment_interaction = -1  # 环境互动性：0到5分
        self.person_fit = -1           # 人物契合度：0到5分
        
        # 跳过原因
        self.skip_reason = ""    # 空字符串表示不跳过，否则记录跳过原因

        # 兼容旧格式
        self.score = -1
        
    def copy(self) -> 'PoseData':
        new_pose = PoseData()
        new_pose.keypoints = [kp.copy() for kp in self.keypoints]
        new_pose.raw_id = self.raw_id
        new_pose.raw_scores = self.raw_scores.copy()
        new_pose.score = self.score
        new_pose.novelty = self.novelty
        new_pose.environment_interaction = self.environment_interaction
        new_pose.person_fit = self.person_fit
        new_pose.skip_reason = self.skip_reason
        return new_pose
        
    def _init_keypoints(self) -> List[Keypoint]:
        return [Keypoint(name) for name in self.KEYPOINT_NAMES]
    
    def to_dict(self) -> Dict[str, Any]:
        """输出为COCO风格格式"""
        return {
            "id": self.raw_id,
            "keypoints": [[kp.x, kp.y] for kp in self.keypoints],
            "scores": self.raw_scores if self.raw_scores else [0.0] * len(self.keypoints),
            "visibility": [kp.visibility for kp in self.keypoints],
            "novelty": self.novelty,
            "environment_interaction": self.environment_interaction,
            "person_fit": self.person_fit,
            "skip_reason": self.skip_reason
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PoseData':
        """从COCO风格格式加载（兼容新旧两种格式）"""
        pose = cls()
        
        # 读取评分字段
        pose.novelty = data.get("novelty", -1)
        pose.environment_interaction = data.get("environment_interaction", data.get("environment_fit", -1))
        pose.person_fit = data.get("person_fit", -1)
        pose.skip_reason = data.get("skip_reason", "")
        pose.score = data.get("score", -1)
        
        raw_kps = data.get("keypoints", [])
        
        # 判断格式：COCO风格 [[x,y], ...] vs 旧格式 [{"name":..., "x":..., ...}, ...]
        if raw_kps and isinstance(raw_kps[0], list):
            # ---- COCO风格格式 ----
            pose.raw_id = data.get("id", 0)
            pose.raw_scores = data.get("scores", [])
            visibility_list = data.get("visibility", [])
            
            for i, kp in enumerate(pose.keypoints):
                if i < len(raw_kps):
                    kp.x = raw_kps[i][0]
                    kp.y = raw_kps[i][1]
                # visibility: 优先用已标注的值，否则根据score阈值初始化
                if i < len(visibility_list):
                    kp.visibility = visibility_list[i]
                elif i < len(pose.raw_scores) and pose.raw_scores[i] > 0.3:
                    kp.visibility = 2  # 置信度高则默认可见
                    
        elif raw_kps and isinstance(raw_kps[0], dict):
            # ---- 旧的自定义格式（向后兼容） ----
            for i, kp_data in enumerate(raw_kps):
                if i < len(pose.keypoints):
                    pose.keypoints[i] = Keypoint.from_dict(kp_data)
        
        return pose
        
    def has_valid_keypoints(self) -> bool:
        """检查是否有有效的关键点坐标（不全为0）"""
        for kp in self.keypoints:
            if kp.x > 1 and kp.y > 1: # 简单的阈值判断
                return True
        return False
        
    def get_bounding_box(self) -> Tuple[float, float, float, float]:
        """获取所有非0关键点的包围盒 (min_x, min_y, max_x, max_y)"""
        xs = [kp.x for kp in self.keypoints if kp.x > 1]
        ys = [kp.y for kp in self.keypoints if kp.y > 1]
        
        if not xs or not ys:
            return (0, 0, 0, 0)
            
        return (min(xs), min(ys), max(xs), max(ys))


class UndoCommand:
    def undo(self): pass
    def redo(self): pass


class KeypointChangeCommand(UndoCommand):
    def __init__(self, pose_data: PoseData, keypoint_index: int, old_state: Keypoint, new_state: Keypoint):
        self.pose_data = pose_data
        self.keypoint_index = keypoint_index
        self.old_state = old_state
        self.new_state = new_state
        
    def _update_keypoint(self, state: Keypoint):
        current_kp = self.pose_data.keypoints[self.keypoint_index]
        current_kp.x = state.x
        current_kp.y = state.y
        current_kp.visibility = state.visibility
        
    def undo(self):
        self._update_keypoint(self.old_state)
        
    def redo(self):
        self._update_keypoint(self.new_state)


class UndoStack(QObject):
    can_undo_changed = Signal(bool)
    can_redo_changed = Signal(bool)
    
    def __init__(self):
        super().__init__()
        self.undo_stack = []
        self.redo_stack = []
        
    def push(self, command: UndoCommand):
        self.undo_stack.append(command)
        self.redo_stack.clear()
        self.can_undo_changed.emit(True)
        self.can_redo_changed.emit(False)
        
    def undo(self) -> bool:
        if not self.undo_stack: return False
        command = self.undo_stack.pop()
        command.undo()
        self.redo_stack.append(command)
        self.can_undo_changed.emit(bool(self.undo_stack))
        self.can_redo_changed.emit(True)
        return True
        
    def redo(self) -> bool:
        if not self.redo_stack: return False
        command = self.redo_stack.pop()
        command.redo()
        self.undo_stack.append(command)
        self.can_undo_changed.emit(True)
        self.can_redo_changed.emit(bool(self.redo_stack))
        return True
        
    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.can_undo_changed.emit(False)
        self.can_redo_changed.emit(False)


class Canvas(QWidget):
    keypoint_selected = Signal(str)
    
    def __init__(self):
        super().__init__()
        self.image = None
        self.pose_data = PoseData()
        self.scale = 1.0
        self.offset = QPointF(0, 0)
        self.selected_keypoint = None
        self.dragging = False
        self.panning = False
        self.last_pos = QPointF()
        self.show_skeleton = True
        self.keypoint_opacity = 1.0
        self.undo_stack = UndoStack()
        self.drag_start_pos = None
        
        self.skeleton = [
            (0, 1), (0, 2), (1, 3), (2, 4),
            (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
            (5, 11), (6, 12), (11, 12),
            (11, 13), (13, 15), (12, 14), (14, 16)
        ]
        
        self.setMinimumSize(800, 600)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        
    def set_image(self, image: QImage):
        self.image = image
        # 注意：这里不再自动调用 fit_to_window，由外部根据数据情况决定调用哪个缩放方法
        self.update()
        
    def set_pose_data(self, pose_data: PoseData):
        self.pose_data = pose_data
        self.update()
        
    def fit_to_window(self):
        """适应窗口大小 (显示全图)"""
        if not self.image: return
        widget_size = self.size()
        image_size = self.image.size()
        scale_x = widget_size.width() / image_size.width()
        scale_y = widget_size.height() / image_size.height()
        self.scale = min(scale_x, scale_y) * 0.9
        scaled_size = image_size * self.scale
        self.offset = QPointF(
            (widget_size.width() - scaled_size.width()) / 2,
            (widget_size.height() - scaled_size.height()) / 2
        )
        self.update()

    def focus_on_pose(self):
        """[新增功能] 聚焦于姿态所在的局部区域"""
        if not self.image or not self.pose_data.has_valid_keypoints():
            self.fit_to_window()
            return

        min_x, min_y, max_x, max_y = self.pose_data.get_bounding_box()
        
        # 计算包围盒宽高
        bbox_w = max_x - min_x
        bbox_h = max_y - min_y
        
        # 如果包围盒太小，回退到全图
        if bbox_w < 10 or bbox_h < 10:
            self.fit_to_window()
            return

        # 增加一些边距 (padding)
        padding_x = bbox_w * 0.5  # 左右各留50%宽度的空间
        padding_y = bbox_h * 0.5
        
        target_x = min_x - padding_x / 2
        target_y = min_y - padding_y / 2
        target_w = bbox_w + padding_x
        target_h = bbox_h + padding_y

        widget_size = self.size()
        
        # 计算缩放比例
        scale_x = widget_size.width() / target_w
        scale_y = widget_size.height() / target_h
        new_scale = min(scale_x, scale_y)
        
        # 限制最大放大倍数，防止模糊过度
        self.scale = min(new_scale, 5.0) 
        
        # 计算偏移量：使得 target_rect 的中心对齐 widget 的中心
        # image_pixel * scale + offset = screen_pixel
        # offset = screen_pixel_center - image_pixel_center * scale
        
        center_x = target_x + target_w / 2
        center_y = target_y + target_h / 2
        
        self.offset = QPointF(
            widget_size.width() / 2 - center_x * self.scale,
            widget_size.height() / 2 - center_y * self.scale
        )
        
        self.update()

    def image_to_widget(self, point: QPointF) -> QPointF:
        return QPointF(point.x() * self.scale + self.offset.x(),
                      point.y() * self.scale + self.offset.y())
    
    def widget_to_image(self, point: QPointF) -> QPointF:
        return QPointF((point.x() - self.offset.x()) / self.scale,
                      (point.y() - self.offset.y()) / self.scale)
    
    def get_keypoint_at(self, pos: QPointF) -> Optional[Keypoint]:
        if not self.image: return None
        for kp in self.pose_data.keypoints:
            kp_pos = self.image_to_widget(QPointF(kp.x, kp.y))
            distance = (kp_pos - pos).manhattanLength()
            if distance < 10:  
                return kp
        return None
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(50, 50, 50))
        
        if not self.image: return
            
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        painter.drawImage(0, 0, self.image)
        painter.restore()
        
        if self.show_skeleton:
            self.draw_skeleton(painter)
        self.draw_keypoints(painter)
        
    def draw_skeleton(self, painter: QPainter):
        if not self.image: return
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        pen = QPen(QColor(100, 200, 100, 150), 2)
        painter.setPen(pen)
        for start_idx, end_idx in self.skeleton:
            start_kp = self.pose_data.keypoints[start_idx]
            end_kp = self.pose_data.keypoints[end_idx]
            if start_kp.visibility > 0 and end_kp.visibility > 0:
                painter.drawLine(QPointF(start_kp.x, start_kp.y), 
                               QPointF(end_kp.x, end_kp.y))
        painter.restore()
        
    def draw_keypoints(self, painter: QPainter):
        if not self.image: return
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        
        # 统一颜色
        normal_color = QColor(0, 200, 255, int(255 * self.keypoint_opacity))
        normal_border = QColor(0, 0, 0)
        selected_color = QColor(255, 255, 0)
        selected_border = QColor(0, 0, 0)
        
        for i, kp in enumerate(self.pose_data.keypoints):
            is_selected = (self.selected_keypoint == kp)
            fill_color = selected_color if is_selected else normal_color
            border_color = selected_border if is_selected else normal_border
            
            radius = 5 / self.scale
            pen_width = 1.5 / self.scale
            
            if kp.visibility == 2:
                # 可见 = 圆形（实心）
                painter.setBrush(QBrush(fill_color))
                painter.setPen(QPen(border_color, pen_width))
                painter.drawEllipse(QPointF(kp.x, kp.y), radius, radius)
                
            elif kp.visibility == 1:
                # 遮挡 = 三角形（实心）
                from PySide6.QtGui import QPolygonF
                tri_size = radius * 1.3
                triangle = QPolygonF([
                    QPointF(kp.x, kp.y - tri_size),
                    QPointF(kp.x - tri_size, kp.y + tri_size * 0.8),
                    QPointF(kp.x + tri_size, kp.y + tri_size * 0.8)
                ])
                painter.setBrush(QBrush(fill_color))
                painter.setPen(QPen(border_color, pen_width))
                painter.drawPolygon(triangle)
                
            else:
                # 不可见 = 叉号
                cross_size = radius * 0.9
                cross_pen = QPen(fill_color, pen_width * 2)
                cross_pen.setCapStyle(Qt.RoundCap)
                painter.setPen(cross_pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawLine(
                    QPointF(kp.x - cross_size, kp.y - cross_size),
                    QPointF(kp.x + cross_size, kp.y + cross_size)
                )
                painter.drawLine(
                    QPointF(kp.x - cross_size, kp.y + cross_size),
                    QPointF(kp.x + cross_size, kp.y - cross_size)
                )
            
        painter.restore()
        
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if event.modifiers() & Qt.ControlModifier:
                if self.selected_keypoint:
                    image_pos = self.widget_to_image(event.pos())
                    keypoint_index = self.pose_data.keypoints.index(self.selected_keypoint)
                    old_state = self.selected_keypoint.copy()
                    
                    self.selected_keypoint.x = max(0, image_pos.x())
                    self.selected_keypoint.y = max(0, image_pos.y())
                    self.selected_keypoint.visibility = 2
                    
                    new_state = self.selected_keypoint.copy()
                    command = KeypointChangeCommand(self.pose_data, keypoint_index, old_state, new_state)
                    self.undo_stack.push(command)
                    self.update()
                    return

            self.selected_keypoint = self.get_keypoint_at(event.pos())
            if self.selected_keypoint:
                self.dragging = True
                self.drag_start_pos = QPointF(self.selected_keypoint.x, self.selected_keypoint.y)
                self.keypoint_selected.emit(self.selected_keypoint.name)
            self.update()
            
        elif event.button() == Qt.RightButton:
            self.panning = True
            self.last_pos = event.pos()
            
    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging and self.selected_keypoint:
            image_pos = self.widget_to_image(event.pos())
            self.selected_keypoint.x = max(0, image_pos.x())
            self.selected_keypoint.y = max(0, image_pos.y())
            if self.selected_keypoint.visibility == 0:
                self.selected_keypoint.visibility = 2
            self.update()
        elif self.panning:
            delta = event.pos() - self.last_pos
            self.offset += delta
            self.last_pos = event.pos()
            self.update()
            
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self.dragging and self.selected_keypoint and self.drag_start_pos:
            keypoint_index = self.pose_data.keypoints.index(self.selected_keypoint)
            old_state = Keypoint(
                self.selected_keypoint.name,
                self.drag_start_pos.x(),
                self.drag_start_pos.y(),
                self.selected_keypoint.visibility
            )
            new_state = self.selected_keypoint.copy()
            command = KeypointChangeCommand(self.pose_data, keypoint_index, old_state, new_state)
            self.undo_stack.push(command)
            self.dragging = False
            self.drag_start_pos = None
        elif event.button() == Qt.LeftButton:
            self.dragging = False
        elif event.button() == Qt.RightButton:
            self.panning = False
            
    def wheelEvent(self, event: QWheelEvent):
        if not self.image: return
        mouse_pos = event.position()
        image_pos_before = self.widget_to_image(mouse_pos)
        delta = event.angleDelta().y() / 120
        scale_factor = 1.1 if delta > 0 else 0.9
        new_scale = self.scale * scale_factor
        
        if 0.1 <= new_scale <= 20.0: # 允许更大的放大倍数
            self.scale = new_scale
            image_pos_after = self.widget_to_image(mouse_pos)
            offset_delta = QPointF(
                (image_pos_before.x() - image_pos_after.x()) * self.scale,
                (image_pos_before.y() - image_pos_after.y()) * self.scale
            )
            self.offset += offset_delta
            self.update()
            
    def keyPressEvent(self, event: QKeyEvent):
        if not self.selected_keypoint: return
        key = event.key()
        keypoint_index = self.pose_data.keypoints.index(self.selected_keypoint)
        old_state = self.selected_keypoint.copy()
        
        if key in [Qt.Key_A, Qt.Key_D, Qt.Key_S]:
            if key == Qt.Key_A: self.selected_keypoint.visibility = 1
            elif key == Qt.Key_D: self.selected_keypoint.visibility = 0
            elif key == Qt.Key_S: self.selected_keypoint.visibility = 2
            
            new_state = self.selected_keypoint.copy()
            command = KeypointChangeCommand(self.pose_data, keypoint_index, old_state, new_state)
            self.undo_stack.push(command)
            self.update()


class PoseEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_image_path = None
        self.current_annotation_path = None
        self.image_files = []
        self.current_index = 0
        
        # 新增评分和跳过按钮的引用
        self.score_buttons = {}  # 存储评分按钮的引用
        self.skip_buttons = []   # 存储跳过按钮的引用
        
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("姿态标注修正工具 v2.0")
        self.setGeometry(100, 100, 1300, 850)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        self.canvas = Canvas()
        self.canvas.keypoint_selected.connect(self.on_keypoint_selected)
        splitter.addWidget(self.canvas)
        
        control_panel = self.create_control_panel()
        splitter.addWidget(control_panel)
        splitter.setSizes([900, 400])
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.update_status()
        self.create_menu_bar()
        
    def create_control_panel(self) -> QWidget:
        panel = QFrame()
        panel.setMaximumWidth(350)
        layout = QVBoxLayout(panel)
        
        # --- 文件操作区 ---
        file_group = QGroupBox("文件操作")
        file_layout = QVBoxLayout(file_group)
        
        self.open_btn = QPushButton("打开图片文件夹")
        self.open_btn.clicked.connect(self.open_folder)
        file_layout.addWidget(self.open_btn)
        
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("上一张 (←)")
        self.prev_btn.clicked.connect(self.prev_image)
        self.next_btn = QPushButton("下一张 (→)")
        self.next_btn.clicked.connect(self.next_image)
        # self.next_processable_btn = QPushButton("下个需处理 (Ctrl+→)")
        # self.next_processable_btn.clicked.connect(self.next_processable_image   )
        # self.next_processable_btn.setStyleSheet("background-color: #e6f7ff; font-weight: bold;")
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.next_btn)
        # nav_layout.addWidget(self.next_processable_btn)
        file_layout.addLayout(nav_layout)
        
        self.save_btn = QPushButton("保存 (Ctrl+S)")
        self.save_btn.clicked.connect(self.save_current)
        file_layout.addWidget(self.save_btn)
        
        # # [新增功能 2] 废弃按钮
        # self.ignore_btn = QPushButton("标记为废弃/移动到Ignore (Del)")
        # self.ignore_btn.setStyleSheet("background-color: #ffcccc; color: darkred;")
        # self.ignore_btn.clicked.connect(self.move_to_ignore)
        # file_layout.addWidget(self.ignore_btn)
        
        layout.addWidget(file_group)
        
        # --- 评分系统 ---
        score_group = QGroupBox("姿态评分系统")
        score_layout = QVBoxLayout(score_group)
        
        # 评分区域
        detail_layout = QGridLayout()
        
        # 姿势新奇度
        detail_layout.addWidget(QLabel("姿势新奇度:"), 0, 0)
        self.novelty_buttons = {}
        self.novelty_btn_group = QButtonGroup(self)
        self.novelty_btn_group.setExclusive(True)
        self.novelty_btn_group.idClicked.connect(lambda id: self.on_new_score_button_clicked("novelty", id))
        
        for i in range(6):
            btn = QPushButton(str(i))
            btn.setCheckable(True)
            btn.setFixedSize(25, 25)
            btn.setStyleSheet("""
                QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; font-size: 10px; }
                QPushButton:checked { background-color: #28a745; color: white; border: 1px solid #1e7e34; }
            """)
            self.novelty_btn_group.addButton(btn, i)
            detail_layout.addWidget(btn, 0, i+1)
            self.novelty_buttons[i] = btn
        
        na_btn2 = QPushButton("N/A")
        na_btn2.setCheckable(True)
        na_btn2.setFixedSize(25, 25)
        na_btn2.setStyleSheet("""
            QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; color: gray; font-size: 10px; }
            QPushButton:checked { background-color: #999; color: white; }
        """)
        self.novelty_btn_group.addButton(na_btn2, -1)
        detail_layout.addWidget(na_btn2, 0, 7)
        na_btn2.setChecked(True)
        self.novelty_buttons[-1] = na_btn2
        
        # 环境互动性
        detail_layout.addWidget(QLabel("环境互动性:"), 1, 0)
        self.env_buttons = {}
        self.env_btn_group = QButtonGroup(self)
        self.env_btn_group.setExclusive(True)
        self.env_btn_group.idClicked.connect(lambda id: self.on_new_score_button_clicked("environment_interaction", id))
        
        for i in range(6):
            btn = QPushButton(str(i))
            btn.setCheckable(True)
            btn.setFixedSize(25, 25)
            btn.setStyleSheet("""
                QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; font-size: 10px; }
                QPushButton:checked { background-color: #17a2b8; color: white; border: 1px solid #117a8b; }
            """)
            self.env_btn_group.addButton(btn, i)
            detail_layout.addWidget(btn, 1, i+1)
            self.env_buttons[i] = btn
        
        na_btn3 = QPushButton("N/A")
        na_btn3.setCheckable(True)
        na_btn3.setFixedSize(25, 25)
        na_btn3.setStyleSheet("""
            QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; color: gray; font-size: 10px; }
            QPushButton:checked { background-color: #999; color: white; }
        """)
        self.env_btn_group.addButton(na_btn3, -1)
        detail_layout.addWidget(na_btn3, 1, 7)
        na_btn3.setChecked(True)
        self.env_buttons[-1] = na_btn3
        
        # 人物契合度
        detail_layout.addWidget(QLabel("人物契合度:"), 2, 0)
        self.person_buttons = {}
        self.person_btn_group = QButtonGroup(self)
        self.person_btn_group.setExclusive(True)
        self.person_btn_group.idClicked.connect(lambda id: self.on_new_score_button_clicked("person_fit", id))
        
        for i in range(6):
            btn = QPushButton(str(i))
            btn.setCheckable(True)
            btn.setFixedSize(25, 25)
            btn.setStyleSheet("""
                QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; font-size: 10px; }
                QPushButton:checked { background-color: #ffc107; color: black; border: 1px solid #d39e00; }
            """)
            self.person_btn_group.addButton(btn, i)
            detail_layout.addWidget(btn, 2, i+1)
            self.person_buttons[i] = btn
        
        na_btn4 = QPushButton("N/A")
        na_btn4.setCheckable(True)
        na_btn4.setFixedSize(25, 25)
        na_btn4.setStyleSheet("""
            QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; color: gray; font-size: 10px; }
            QPushButton:checked { background-color: #999; color: white; }
        """)
        self.person_btn_group.addButton(na_btn4, -1)
        detail_layout.addWidget(na_btn4, 2, 7)
        na_btn4.setChecked(True)
        self.person_buttons[-1] = na_btn4
        
        score_layout.addLayout(detail_layout)
        
        # 跳过按钮区域 - 点击后移动到 ignore 对应子文件夹（放在评分上方）
        skip_group = QGroupBox("移至Ignore（不可撤销）")
        skip_layout = QHBoxLayout(skip_group)
        skip_layout.setSpacing(6)
        
        ignore_btn_style = """
            QPushButton { 
                background-color: #fff3cd; border: 1px solid #ffc107; 
                padding: 6px 10px; color: #856404; font-size: 12px;
            }
            QPushButton:hover { background-color: #ffc107; color: white; }
        """
        
        self.ignore_aesthetic_btn = QPushButton("美感不足")
        self.ignore_aesthetic_btn.setToolTip("美感不足。如果图像不是具有美感的人物照片（例如日常照片），则可点击该按钮跳过。")
        self.ignore_aesthetic_btn.clicked.connect(lambda: self.move_to_ignore_category("美感不足"))
        self.ignore_aesthetic_btn.setStyleSheet(ignore_btn_style)
        skip_layout.addWidget(self.ignore_aesthetic_btn)
        
        self.ignore_blur_btn = QPushButton("图像模糊")
        self.ignore_blur_btn.setToolTip("图像模糊。如果图像分辨率很低，或图像质量不佳，则可点它跳过。")
        self.ignore_blur_btn.clicked.connect(lambda: self.move_to_ignore_category("图像模糊"))
        self.ignore_blur_btn.setStyleSheet(ignore_btn_style)
        skip_layout.addWidget(self.ignore_blur_btn)
        
        self.ignore_size_btn = QPushButton("比例失调")
        self.ignore_size_btn.setToolTip("比例失调。如果人物占画面的比例非常小或大，无法确定姿态，则点它跳过。")
        self.ignore_size_btn.clicked.connect(lambda: self.move_to_ignore_category("比例失调"))
        self.ignore_size_btn.setStyleSheet(ignore_btn_style)
        skip_layout.addWidget(self.ignore_size_btn)
        
        self.ignore_scene_btn = QPushButton("场景图失真")
        self.ignore_scene_btn.setToolTip("场景图失真。这里的图像是将人物图像中的人物区域给删除修复得到的无人场景图。如果该图像有异常纹理等不真实的情况，则点它跳过。")
        self.ignore_scene_btn.clicked.connect(lambda: self.move_to_ignore_category("场景图失真"))
        self.ignore_scene_btn.setStyleSheet(ignore_btn_style)
        skip_layout.addWidget(self.ignore_scene_btn)
        
        # 添加跳过组（在评分上方）和评分组到主布局
        layout.addWidget(skip_group)
        layout.addWidget(score_group)
        
        # 安装延迟tooltip过滤器（悬浮2秒后显示详细说明）
        self.tooltip_filter = DelayedTooltipFilter(self)
        for btn in [self.ignore_aesthetic_btn, self.ignore_blur_btn, 
                     self.ignore_size_btn, self.ignore_scene_btn]:
            btn.installEventFilter(self.tooltip_filter)
        
        # 保存评分按钮引用以便后续更新
        self.score_buttons = {
            "novelty": self.novelty_buttons,
            "environment_interaction": self.env_buttons,
            "person_fit": self.person_buttons
        }
        

        # --- 关键点列表 ---
        layout.addWidget(QLabel("关键点列表:"))
        self.keypoint_list = QListWidget()
        self.keypoint_list.itemClicked.connect(self.on_list_item_clicked)
        layout.addWidget(self.keypoint_list)
        self.update_keypoint_list()
        
        # --- 视图控制 ---
        view_group = QGroupBox("视图控制")
        view_layout = QVBoxLayout(view_group)
        
        self.fit_btn = QPushButton("适应窗口 / 重置视图")
        self.fit_btn.clicked.connect(self.fit_to_window)
        view_layout.addWidget(self.fit_btn)
        
        self.skeleton_btn = QPushButton("隐藏骨架 (H)")
        self.skeleton_btn.clicked.connect(self.toggle_skeleton)
        view_layout.addWidget(self.skeleton_btn)
        
        layout.addWidget(view_group)
        
        # --- 帮助 ---
        help_text = QLabel(
            "• 左键: 选中/拖拽 (Ctrl+点击=瞬移)\n"
            "• 右键: 平移画布 | 滚轮: 缩放\n"
            "• A: 遮挡(▲) | D: 不可见(✕) | S: 可见(●)\n"
            "• Tab/Shift+Tab: 切换点 | Delete: 移至Ignore\n"
            "• ←/→: 上一张/下一张 | Ctrl+→: 下个需处理\n"
            "• Ctrl+Z/Y: 撤销/重做 | Ctrl+S: 保存\n"
            "• Ignore分类: 美感不足/图像模糊/比例失调/场景图失真"
        )
        help_text.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(help_text)
        
        layout.addStretch()
        return panel
        
    def create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        
        open_action = QAction("打开文件夹", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_folder)
        file_menu.addAction(open_action)
        
        save_action = QAction("保存", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_current)
        file_menu.addAction(save_action)
        
        edit_menu = menubar.addMenu("编辑")
        undo_action = QAction("撤销", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self.undo)
        edit_menu.addAction(undo_action)
        
        redo_action = QAction("重做", self)
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(self.redo)
        edit_menu.addAction(redo_action)
        
    def update_keypoint_list(self):
        self.keypoint_list.clear()
        for kp in self.canvas.pose_data.keypoints:
            # 用形状符号表示可见性：● 圆形=可见，▲ 三角=遮挡，✕ 叉=不可见
            if kp.visibility == 2:
                prefix = "● "  # 可见
            elif kp.visibility == 1:
                prefix = "▲ "  # 遮挡
            else:
                prefix = "✕ "  # 不可见
            item = QListWidgetItem(prefix + kp.name)
            self.keypoint_list.addItem(item)
            
    def on_keypoint_selected(self, name: str):
        self.update_status()
        for i in range(self.keypoint_list.count()):
            item_text = self.keypoint_list.item(i).text()
            # 列表项有形状前缀（如 "● nose"），需要去掉前缀比较
            if item_text[2:] == name:
                self.keypoint_list.setCurrentRow(i)
                break
                
    def on_list_item_clicked(self, item: QListWidgetItem):
        kp_name = item.text()[2:]  # 去掉形状前缀（如 "● "）
        for kp in self.canvas.pose_data.keypoints:
            if kp.name == kp_name:
                self.canvas.selected_keypoint = kp
                self.canvas.update()
                self.update_status()
                break
    
    def on_new_score_button_clicked(self, score_type: str, value: int):
        """评分按钮点击回调"""
        old_value = getattr(self.canvas.pose_data, score_type, -1)
        if old_value != value:
            setattr(self.canvas.pose_data, score_type, value)

    def on_skip_button_clicked(self, reason: str):
        """已废弃 - 由 move_to_ignore_category 替代"""
        pass

    def move_to_ignore_category(self, category: str, custom_reason: str = ""):
        """将当前图片和JSON移动到 ignore/<category>/ 文件夹"""
        if not self.current_image_path:
            return

        image_path = Path(self.current_image_path)
        json_path = image_path.with_suffix('.json')
        
        # 创建 ignore/<category>/ 文件夹
        # 对"其他"类别使用固定文件夹名
        folder_name = category
        ignore_dir = image_path.parent / "ignore" / folder_name
        if not ignore_dir.exists():
            ignore_dir.mkdir(parents=True)
            
        try:
            # 先保存 skip_reason 到 JSON
            reason_text = custom_reason if custom_reason else category
            self.canvas.pose_data.skip_reason = reason_text
            
            # 保存 JSON（确保理由写入）
            data = self.canvas.pose_data.to_dict()
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # 移动图片
            shutil.move(str(image_path), str(ignore_dir / image_path.name))
            
            # 移动 JSON
            if json_path.exists():
                shutil.move(str(json_path), str(ignore_dir / json_path.name))
                
            print(f"Moved {image_path.name} to ignore/{folder_name}/")
            
            # 从列表中移除
            del self.image_files[self.current_index]
            
            # 如果列表空了
            if not self.image_files:
                self.canvas.image = None
                self.canvas.update()
                QMessageBox.information(self, "提示", "所有图片处理完毕")
                return

            # 修正索引
            if self.current_index >= len(self.image_files):
                self.current_index = len(self.image_files) - 1
                
            # 加载下一张
            self.load_current_image()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"移动文件失败: {e}")

    def move_to_ignore_other(self):
        """点击'其他原因'时弹出输入框，输入理由后移动"""
        if not self.current_image_path:
            return
        
        reason, ok = QInputDialog.getText(self, "其他原因", "请输入跳过理由:")
        if ok and reason.strip():
            self.move_to_ignore_category("其他", custom_reason=reason.strip())
        # 如果取消或空字符串则不执行

    def update_skip_buttons(self):
        """跳过按钮不再是toggle模式，此方法保留兼容"""
        pass
        
    def update_status(self):
        if self.current_image_path:
            filename = Path(self.current_image_path).name
            status = f"图片: {filename} ({self.current_index + 1}/{len(self.image_files)})"
        else:
            status = "未加载图片"
            
        # 显示跳过状态
        if self.canvas.pose_data.skip_reason:
            status += f" | [已跳过: {self.canvas.pose_data.skip_reason}]"
        
        if self.canvas.selected_keypoint:
            kp = self.canvas.selected_keypoint
            vis_map = {0: "不可见", 1: "遮挡", 2: "可见"}
            status += f" | 选中: {kp.name} ({vis_map[kp.visibility]})"
            
        self.status_bar.showMessage(status)
        
    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if folder:
            self.load_images_from_folder(folder)
            
    def load_images_from_folder(self, folder: str):
        folder_path = Path(folder)
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}
        
        self.image_files = []
        for ext in image_extensions:
            self.image_files.extend(folder_path.glob(f"*{ext}"))
            self.image_files.extend(folder_path.glob(f"*{ext.upper()}"))
            
        self.image_files.sort()
        if self.image_files:
            self.current_index = 0
            self.load_current_image()
        else:
            QMessageBox.information(self, "提示", "该文件夹下没有图片")
            
    def load_current_image(self):
        if not self.image_files: return
        self.current_image_path = str(self.image_files[self.current_index])
        
        image = QImage(self.current_image_path)
        if image.isNull():
            QMessageBox.warning(self, "错误", f"无法加载图片: {self.current_image_path}")
            return
            
        self.canvas.set_image(image)
        self.load_annotation()
        
        # 加载完数据后，重置撤销栈
        self.canvas.undo_stack.clear()
        self.update_status()
        self.update_keypoint_list()
        
    def load_annotation(self):
        if not self.current_image_path: return
        
        image_path = Path(self.current_image_path)
        json_path = image_path.with_suffix('.json')
        
        pose_data = PoseData()
        
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 处理最外层是列表的情况（COCO风格）
                    if isinstance(data, list):
                        if len(data) > 0:
                            pose_data = PoseData.from_dict(data[0])
                    else:
                        pose_data = PoseData.from_dict(data)
            except Exception as e:
                print(f"Error loading JSON: {e}")
        
        self.canvas.set_pose_data(pose_data)
        self.current_annotation_path = str(json_path)
        
        # 更新新版评分UI
        self.update_score_ui(pose_data)
        
        # 更新跳过按钮状态
        self.update_skip_buttons()

        if self.canvas.pose_data.keypoints:
            # 默认选中第一个点
            first_kp = self.canvas.pose_data.keypoints[0]
            self.canvas.selected_keypoint = first_kp
            self.on_keypoint_selected(first_kp.name)

        # [新增功能 1] 自动缩放逻辑
        if pose_data.has_valid_keypoints():
            # 如果有有效数据，聚焦于人体
            self.canvas.focus_on_pose()
        else:
            # 如果是新数据或全0数据，全屏显示
            self.canvas.fit_to_window()
    
    def update_score_ui(self, pose_data: PoseData):
        """更新评分UI状态"""
        # 更新姿势新奇度
        novelty = pose_data.novelty
        if novelty >= 0 and novelty in self.novelty_buttons:
            self.novelty_buttons[novelty].setChecked(True)
        else:
            self.novelty_buttons[-1].setChecked(True)  # N/A按钮
        
        # 更新环境互动性
        env_int = pose_data.environment_interaction
        if env_int >= 0 and env_int in self.env_buttons:
            self.env_buttons[env_int].setChecked(True)
        else:
            self.env_buttons[-1].setChecked(True)  # N/A按钮
        
        # 更新人物契合度
        person_fit = pose_data.person_fit
        if person_fit >= 0 and person_fit in self.person_buttons:
            self.person_buttons[person_fit].setChecked(True)
        else:
            self.person_buttons[-1].setChecked(True)  # N/A按钮
        
    def save_current(self):
        if not self.current_annotation_path: return
        try:
            data = [self.canvas.pose_data.to_dict()]  # 用列表包裹，保持COCO风格
            with open(self.current_annotation_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.status_bar.showMessage(f"已保存: {Path(self.current_annotation_path).name}", 2000)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存失败: {e}")

    def move_to_ignore(self):
        """[Delete键] 弹出选择对话框，选择类别后移动到 ignore 子文件夹"""
        if not self.current_image_path:
            return
        
        items = ["美感不足", "图像模糊", "比例失调", "场景图失真", "其他原因"]
        item, ok = QInputDialog.getItem(self, "选择ignore类别", "请选择跳过原因:", items, 0, False)
        if ok and item:
            if item == "其他原因":
                self.move_to_ignore_other()
            else:
                self.move_to_ignore_category(item)

    def has_complete_scores(self) -> bool:
        """检查是否所有评分都已填写（非N/A）"""
        pose = self.canvas.pose_data
        return (pose.novelty >= 0 and 
                pose.environment_interaction >= 0 and 
                pose.person_fit >= 0)
    
    def validate_before_navigate(self) -> bool:
        """导航前验证：评分不完整则阻止翻页"""
        pose = self.canvas.pose_data
        # 如果已有skip_reason（从旧数据加载的），允许翻页
        if pose.skip_reason:
            return True
        # 必须所有评分都已填写
        if not self.has_complete_scores():
            missing = []
            if pose.novelty < 0:
                missing.append("姿势新奇度")
            if pose.environment_interaction < 0:
                missing.append("环境互动性")
            if pose.person_fit < 0:
                missing.append("人物契合度")
            QMessageBox.warning(self, "评分不完整", 
                f"以下评分仍为N/A，请先打分或移至Ignore：\n\n• {'、'.join(missing)}")
            return False
        return True

    def prev_image(self):
        if self.image_files and self.current_index > 0:
            self.save_current()
            self.current_index -= 1
            self.load_current_image()
            
    def next_image(self):
        if self.image_files and self.current_index < len(self.image_files) - 1:
            if not self.validate_before_navigate():
                return
            self.save_current()
            self.current_index += 1
            self.load_current_image()
            
    def next_processable_image(self):
        """跳到下一个需要处理的图片（未跳过的图片）"""
        if not self.image_files:
            return
        
        if not self.validate_before_navigate():
            return
            
        original_index = self.current_index
        self.save_current()
        
        # 向前查找下一个未跳过的图片
        while self.current_index < len(self.image_files) - 1:
            self.current_index += 1
            self.load_current_image()
            if self.should_process_image():
                return
                
        # 如果没找到，回到原始位置
        self.current_index = original_index
        self.load_current_image()
        QMessageBox.information(self, "提示", "没有更多需要处理的图片")
            
    def should_process_image(self) -> bool:
        """判断是否应该处理当前图片（不跳过）"""
        return not self.canvas.pose_data.skip_reason
            
    def fit_to_window(self):
        self.canvas.fit_to_window()
        
    def toggle_skeleton(self):
        self.canvas.show_skeleton = not self.canvas.show_skeleton
        self.skeleton_btn.setText("显示骨架" if not self.canvas.show_skeleton else "隐藏骨架 (H)")
        self.canvas.update()
        
    def undo(self):
        if self.canvas.undo_stack.undo():
            self.canvas.update()
            self.update_keypoint_list()
            
    def redo(self):
        if self.canvas.undo_stack.redo():
            self.canvas.update()
            self.update_keypoint_list()
        
    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        
        if key == Qt.Key_Left:
            self.prev_image()
        elif key == Qt.Key_Right and not (event.modifiers() & Qt.ControlModifier):
            self.next_image()
        elif key == Qt.Key_Right and event.modifiers() & Qt.ControlModifier:
            self.next_processable_image()
        elif key == Qt.Key_Tab:
            self.switch_keypoint(1)
        elif key == Qt.Key_Backtab:
            self.switch_keypoint(-1)
        elif key == Qt.Key_S and event.modifiers() & Qt.ControlModifier:
            self.save_current()
        elif key == Qt.Key_Delete: # Delete 键触发移动到 ignore
            self.move_to_ignore()
        else:
            self.canvas.keyPressEvent(event)
            
    def switch_keypoint(self, direction: int):
        if not self.canvas.pose_data.keypoints: return
        current_idx = -1
        if self.canvas.selected_keypoint:
            try:
                current_idx = self.canvas.pose_data.keypoints.index(self.canvas.selected_keypoint)
            except ValueError:
                pass
        new_idx = (current_idx + direction) % len(self.canvas.pose_data.keypoints)
        self.canvas.selected_keypoint = self.canvas.pose_data.keypoints[new_idx]
        self.canvas.update()
        self.on_keypoint_selected(self.canvas.selected_keypoint.name)


def main():
    app = QApplication(sys.argv)
    editor = PoseEditor()
    editor.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()