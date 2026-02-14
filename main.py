import sys
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QStatusBar, QListWidget, QListWidgetItem, QPushButton,
    QFileDialog, QMessageBox, QSplitter, QFrame, QSpinBox, QGroupBox,
    QButtonGroup, QGridLayout, QInputDialog, QToolTip, QScrollArea,
    QSizePolicy
)
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QObject, QTimer, QEvent
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QBrush, QColor, 
    QMouseEvent, QKeyEvent, QWheelEvent, QAction, QShortcut, QKeySequence
)


# ============================================================
# 项目文件夹结构常量
# ============================================================
DIR_ORIGIN   = "images"           # 原图
DIR_JSON     = "annotations"      # 标注JSON
DIR_INPAINT  = "inpainting"       # inpainting参考图
META_FILE    = "meta.json"        # 项目元数据


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
        self.visibility = visibility  # 0: 遮挡, 1: 可见
        
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
                    kp.visibility = 1  # 置信度高则默认可见
                    
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
        if not self.image: return
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        for start_idx, end_idx in self.skeleton:
            start_kp = self.pose_data.keypoints[start_idx]
            end_kp = self.pose_data.keypoints[end_idx]
            if (start_kp.x > 1 or start_kp.y > 1) and (end_kp.x > 1 or end_kp.y > 1):
                color = self.SKELETON_COLORS.get((start_idx, end_idx), QColor(100, 200, 100, 150))
                painter.setPen(QPen(color, 2))
                painter.drawLine(QPointF(start_kp.x, start_kp.y), 
                               QPointF(end_kp.x, end_kp.y))
        painter.restore()
        
    KEYPOINT_COLORS = {
        0:  QColor(100, 220, 100),
        1:  QColor(255, 120, 120),
        3:  QColor(255, 80, 80),
        5:  QColor(255, 100, 50),
        7:  QColor(255, 140, 60),
        9:  QColor(255, 180, 80),
        11: QColor(220, 80, 60),
        13: QColor(230, 120, 80),
        15: QColor(240, 160, 100),
        2:  QColor(100, 180, 255),
        4:  QColor(60, 140, 255),
        6:  QColor(80, 120, 255),
        8:  QColor(100, 160, 240),
        10: QColor(130, 200, 255),
        12: QColor(80, 80, 220),
        14: QColor(100, 120, 230),
        16: QColor(140, 160, 240),
    }

    def draw_keypoints(self, painter: QPainter):
        if not self.image: return
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        
        selected_color = QColor(255, 255, 0)
        selected_border = QColor(0, 0, 0)
        normal_border = QColor(0, 0, 0)
        
        for i, kp in enumerate(self.pose_data.keypoints):
            is_selected = (self.selected_keypoint == kp)
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
                    self.selected_keypoint.visibility = 1
                    
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
        
        if 0.1 <= new_scale <= 20.0:
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
        
        if key in [Qt.Key_S, Qt.Key_D, Qt.Key_Space]:
            if key == Qt.Key_S: self.selected_keypoint.visibility = 0
            elif key == Qt.Key_D: self.selected_keypoint.visibility = 1
            elif key == Qt.Key_Space: self.selected_keypoint.visibility = 1 - self.selected_keypoint.visibility
            
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
        
        # 项目文件夹路径
        self.project_root = None       # 项目根目录
        self.origin_dir = None         # images/
        self.json_dir = None           # annotations/
        self.inpaint_dir = None        # inpainting/
        
        # 新增评分和跳过按钮的引用
        self.score_buttons = {}
        self.skip_buttons = []
        
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("姿态标注修正工具 v2.1")
        self.setGeometry(100, 100, 1400, 900)
        
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
        splitter.setSizes([950, 400])
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.update_status()
        self.create_menu_bar()
        self._setup_shortcuts()
        
    def create_control_panel(self) -> QWidget:
        panel = QFrame()
        panel.setMaximumWidth(380)
        layout = QVBoxLayout(panel)
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # --- 项目操作（紧凑两行） ---
        proj_row1 = QHBoxLayout()
        proj_row1.setSpacing(3)
        
        self.open_btn = QPushButton("📁 打开项目")
        self.open_btn.setToolTip(
            "选择项目根目录，工具会自动识别或创建子目录：\n"
            f"  {DIR_ORIGIN}/  — 原图\n"
            f"  {DIR_JSON}/  — 标注JSON\n"
            f"  {DIR_INPAINT}/  — Inpainting参考图\n"
            f"  {META_FILE}  — 协作元数据"
        )
        self.open_btn.clicked.connect(self.open_folder)
        proj_row1.addWidget(self.open_btn)
        
        self.save_btn = QPushButton("💾 保存")
        self.save_btn.setToolTip("Ctrl+S")
        self.save_btn.clicked.connect(self.save_current)
        proj_row1.addWidget(self.save_btn)
        
        layout.addLayout(proj_row1)
        
        self.project_path_label = QLabel("未打开项目")
        self.project_path_label.setStyleSheet("color: #888; font-size: 10px;")
        self.project_path_label.setWordWrap(True)
        layout.addWidget(self.project_path_label)
        
        # 导航 + 视图控制 合并一行
        nav_row = QHBoxLayout()
        nav_row.setSpacing(3)
        
        self.prev_btn = QPushButton("← 上一张")
        self.prev_btn.clicked.connect(self.prev_image)
        nav_row.addWidget(self.prev_btn)
        
        self.next_btn = QPushButton("下一张 →")
        self.next_btn.clicked.connect(self.next_image)
        nav_row.addWidget(self.next_btn)
        
        self.next_process_btn = QPushButton("待处理 (O)")
        self.next_process_btn.setToolTip("跳到下一个未完成评分的图片")
        self.next_process_btn.clicked.connect(self.next_processable_image)
        nav_row.addWidget(self.next_process_btn)
        
        layout.addLayout(nav_row)
        
        # 视图控制单独一行（带文字，更清晰）
        view_row = QHBoxLayout()
        view_row.setSpacing(3)
        self.focus_pose_btn = QPushButton("聚焦 (W)")
        self.focus_pose_btn.setToolTip("根据关键点位置缩放视图")
        self.focus_pose_btn.clicked.connect(self.focus_on_pose)
        self.fit_btn = QPushButton("全图 (E)")
        self.fit_btn.setToolTip("缩放以显示完整图片")
        self.fit_btn.clicked.connect(self.fit_to_window)
        self.skeleton_btn = QPushButton("骨架 (H)")
        self.skeleton_btn.setToolTip("隐藏/显示骨架")
        self.skeleton_btn.clicked.connect(self.toggle_skeleton)
        view_row.addWidget(self.focus_pose_btn)
        view_row.addWidget(self.fit_btn)
        view_row.addWidget(self.skeleton_btn)
        layout.addLayout(view_row)
        
        # --- 关键点列表（全宽，限高） ---
        layout.addWidget(QLabel("关键点列表:"))
        self.keypoint_list = QListWidget()
        self.keypoint_list.setMaximumHeight(160)
        self.keypoint_list.setStyleSheet("font-size: 11px;")
        self.keypoint_list.itemClicked.connect(self.on_list_item_clicked)
        layout.addWidget(self.keypoint_list)
        self.update_keypoint_list()
        
        # --- 移至Ignore ---
        skip_group = QGroupBox("移至Ignore（不可撤销）")
        skip_layout_top = QHBoxLayout()
        skip_layout_top.setSpacing(4)
        skip_layout_bottom = QHBoxLayout()
        skip_layout_bottom.setSpacing(4)
        skip_group_layout = QVBoxLayout(skip_group)
        skip_group_layout.setSpacing(4)
        skip_group_layout.addLayout(skip_layout_top)
        skip_group_layout.addLayout(skip_layout_bottom)
        
        ignore_btn_style = """
            QPushButton { 
                background-color: #fff3cd; border: 1px solid #ffc107; 
                padding: 4px 6px; color: #856404; font-size: 11px;
            }
            QPushButton:hover { background-color: #ffc107; color: white; }
        """
        
        self.ignore_aesthetic_btn = QPushButton("1.美感不足")
        self.ignore_aesthetic_btn.setToolTip("1 | 美感不足。如果图像不是具有美感的人物照片（例如日常照片），则可点击该按钮跳过。")
        self.ignore_aesthetic_btn.clicked.connect(lambda: self.move_to_ignore_category("美感不足"))
        self.ignore_aesthetic_btn.setStyleSheet(ignore_btn_style)
        skip_layout_top.addWidget(self.ignore_aesthetic_btn)
        
        self.ignore_incomplete_btn = QPushButton("2.难以补全")
        self.ignore_incomplete_btn.setToolTip("2 | 难以补全。如果图像中的人物下半身都在画面外，难以拖拽画面外的遮挡点到猜测位置，则点它跳过。")
        self.ignore_incomplete_btn.clicked.connect(lambda: self.move_to_ignore_category("难以补全"))
        self.ignore_incomplete_btn.setStyleSheet(ignore_btn_style)
        skip_layout_top.addWidget(self.ignore_incomplete_btn)
        
        self.ignore_scene_btn = QPushButton("3.背景失真")
        self.ignore_scene_btn.setToolTip("3 | 背景失真。这里的图像是将人物图像中的人物区域给删除修复得到的无人场景图。如果该图像有异常纹理等不真实的情况，则点它跳过。")
        self.ignore_scene_btn.clicked.connect(lambda: self.move_to_ignore_category("背景失真"))
        self.ignore_scene_btn.setStyleSheet(ignore_btn_style)
        skip_layout_top.addWidget(self.ignore_scene_btn)
        
        self.ignore_size_btn = QPushButton("4.比例失调")
        self.ignore_size_btn.setToolTip("4 | 比例失调。如果人物占画面的比例非常小或大，无法确定姿态，则点它跳过。")
        self.ignore_size_btn.clicked.connect(lambda: self.move_to_ignore_category("比例失调"))
        self.ignore_size_btn.setStyleSheet(ignore_btn_style)
        skip_layout_bottom.addWidget(self.ignore_size_btn)
        
        self.ignore_blur_btn = QPushButton("5.图像模糊")
        self.ignore_blur_btn.setToolTip("5 | 图像模糊。如果图像分辨率很低，或图像质量不佳，则可点它跳过。")
        self.ignore_blur_btn.clicked.connect(lambda: self.move_to_ignore_category("图像模糊"))
        self.ignore_blur_btn.setStyleSheet(ignore_btn_style)
        skip_layout_bottom.addWidget(self.ignore_blur_btn)
        
        layout.addWidget(skip_group)
        
        # 安装延迟tooltip过滤器
        self.tooltip_filter = DelayedTooltipFilter(self)
        for btn in [self.ignore_aesthetic_btn, self.ignore_incomplete_btn,
                     self.ignore_scene_btn, self.ignore_size_btn, self.ignore_blur_btn]:
            btn.installEventFilter(self.tooltip_filter)
        
        # --- 评分系统（无N/A，按钮更大） ---
        score_group = QGroupBox("姿态评分")
        score_layout = QVBoxLayout(score_group)
        score_layout.setSpacing(4)
        
        score_btn_size = 36  # 放大的按钮尺寸
        
        detail_layout = QGridLayout()
        detail_layout.setSpacing(3)
        
        # 姿势新奇度
        detail_layout.addWidget(QLabel("姿势新奇度:"), 0, 0)
        self.novelty_buttons = {}
        self.novelty_btn_group = QButtonGroup(self)
        self.novelty_btn_group.setExclusive(False)
        self.novelty_btn_group.buttonClicked.connect(
            lambda btn: self._on_exclusive_score_click(self.novelty_btn_group, self.novelty_buttons, "novelty", btn))
        
        for i in range(6):
            btn = QPushButton(str(i))
            btn.setCheckable(True)
            btn.setFixedSize(score_btn_size, score_btn_size)
            btn.setStyleSheet("""
                QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; font-size: 13px; font-weight: bold; }
                QPushButton:checked { background-color: #28a745; color: white; border: 2px solid #1e7e34; }
            """)
            self.novelty_btn_group.addButton(btn, i)
            detail_layout.addWidget(btn, 0, i+1)
            self.novelty_buttons[i] = btn
        
        # 环境互动性
        detail_layout.addWidget(QLabel("环境互动性:"), 1, 0)
        self.env_buttons = {}
        self.env_btn_group = QButtonGroup(self)
        self.env_btn_group.setExclusive(False)
        self.env_btn_group.buttonClicked.connect(
            lambda btn: self._on_exclusive_score_click(self.env_btn_group, self.env_buttons, "environment_interaction", btn))
        
        for i in range(6):
            btn = QPushButton(str(i))
            btn.setCheckable(True)
            btn.setFixedSize(score_btn_size, score_btn_size)
            btn.setStyleSheet("""
                QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; font-size: 13px; font-weight: bold; }
                QPushButton:checked { background-color: #17a2b8; color: white; border: 2px solid #117a8b; }
            """)
            self.env_btn_group.addButton(btn, i)
            detail_layout.addWidget(btn, 1, i+1)
            self.env_buttons[i] = btn
        
        # 人物契合度
        detail_layout.addWidget(QLabel("人物契合度:"), 2, 0)
        self.person_buttons = {}
        self.person_btn_group = QButtonGroup(self)
        self.person_btn_group.setExclusive(False)
        self.person_btn_group.buttonClicked.connect(
            lambda btn: self._on_exclusive_score_click(self.person_btn_group, self.person_buttons, "person_fit", btn))
        
        for i in range(6):
            btn = QPushButton(str(i))
            btn.setCheckable(True)
            btn.setFixedSize(score_btn_size, score_btn_size)
            btn.setStyleSheet("""
                QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; font-size: 13px; font-weight: bold; }
                QPushButton:checked { background-color: #ffc107; color: black; border: 2px solid #d39e00; }
            """)
            self.person_btn_group.addButton(btn, i)
            detail_layout.addWidget(btn, 2, i+1)
            self.person_buttons[i] = btn
        
        score_layout.addLayout(detail_layout)
        layout.addWidget(score_group)
        
        self.score_buttons = {
            "novelty": self.novelty_buttons,
            "environment_interaction": self.env_buttons,
            "person_fit": self.person_buttons
        }

        # --- Inpainting 预览区 ---
        inpaint_group = QGroupBox("Inpainting 参考")
        inpaint_layout = QVBoxLayout(inpaint_group)
        inpaint_layout.setContentsMargins(4, 4, 4, 4)
        inpaint_layout.setSpacing(2)
        
        self.inpaint_label = QLabel("打开项目后自动加载")
        self.inpaint_label.setAlignment(Qt.AlignCenter)
        self.inpaint_label.setMinimumHeight(120)
        self.inpaint_label.setMaximumHeight(200)
        self.inpaint_label.setStyleSheet(
            "background-color: #3a3a3a; color: #888; border: 1px solid #555; font-size: 11px;"
        )
        self.inpaint_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        inpaint_layout.addWidget(self.inpaint_label)
        
        self.inpaint_filename_label = QLabel("")
        self.inpaint_filename_label.setStyleSheet("color: #aaa; font-size: 10px;")
        self.inpaint_filename_label.setAlignment(Qt.AlignCenter)
        inpaint_layout.addWidget(self.inpaint_filename_label)
        
        layout.addWidget(inpaint_group)
        
        # --- 帮助说明（放在最底部，紧凑） ---
        help_text = QLabel(
            "左键:选中/拖拽 Ctrl+点击:瞬移 | 右键:平移 滚轮:缩放\n"
            "S:遮挡✕ D:可见● 空格:切换 | Tab/Shift+Tab:切换点\n"
            "←→:翻页 O:下个需处理 | W:聚焦关键点 E:适应全图\n"
            "H:骨架 1~5:丢弃 Del:选择丢弃 | Ctrl+Z/Y:撤销/重做"
        )
        help_text.setStyleSheet("color: #777; font-size: 10px;")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        
        return panel
        
    def create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        
        open_action = QAction("打开项目文件夹", self)
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
            if kp.visibility == 1:
                prefix = "● "
            else:
                prefix = "✕ "
            item = QListWidgetItem(prefix + kp.name)
            self.keypoint_list.addItem(item)
            
    def on_keypoint_selected(self, name: str):
        self.update_status()
        for i in range(self.keypoint_list.count()):
            item_text = self.keypoint_list.item(i).text()
            if item_text[2:] == name:
                self.keypoint_list.setCurrentRow(i)
                break
                
    def on_list_item_clicked(self, item: QListWidgetItem):
        kp_name = item.text()[2:]
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

    def _on_exclusive_score_click(self, btn_group: QButtonGroup, buttons: dict, score_type: str, clicked_btn: QPushButton):
        """手动实现互斥选中（不用N/A，允许全不选表示未评分）"""
        clicked_id = btn_group.id(clicked_btn)
        # 取消同组其他按钮
        for btn in btn_group.buttons():
            if btn is not clicked_btn:
                btn.setChecked(False)
        # 如果点击已选中的按钮则取消（变回未评分）
        if clicked_btn.isChecked():
            setattr(self.canvas.pose_data, score_type, clicked_id)
        else:
            setattr(self.canvas.pose_data, score_type, -1)

    def on_skip_button_clicked(self, reason: str):
        """已废弃 - 由 move_to_ignore_category 替代"""
        pass

    # ============================================================
    # 项目文件夹管理
    # ============================================================
    
    def open_folder(self):
        """打开项目根目录，自动识别或创建子目录结构"""
        folder = QFileDialog.getExistingDirectory(self, "选择项目根目录")
        if not folder:
            return
        
        root = Path(folder)
        origin = root / DIR_ORIGIN
        json_dir = root / DIR_JSON
        inpaint = root / DIR_INPAINT
        
        # 如果 images/ 子目录不存在，检查根目录是否直接有图片（兼容旧结构）
        if not origin.exists():
            # 看看根目录自身有没有图片
            has_images_at_root = any(
                root.glob(f"*{ext}") 
                for ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff',
                            '.JPG', '.JPEG', '.PNG', '.BMP', '.TIFF']
            )
            if has_images_at_root:
                # 旧结构：用户选的根目录本身就是图片目录
                # 提示用户是否自动迁移
                reply = QMessageBox.question(
                    self, "检测到旧文件结构",
                    f"选择的文件夹中直接包含图片。\n\n"
                    f"是否自动迁移为新的项目结构？\n"
                    f"  图片 → {DIR_ORIGIN}/\n"
                    f"  JSON → {DIR_JSON}/\n\n"
                    f"选「否」将直接以旧模式打开（图片和JSON在同一目录）。",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self._migrate_to_project_structure(root)
                else:
                    # 旧模式兼容：不使用子目录
                    self.project_root = root
                    self.origin_dir = root
                    self.json_dir = root
                    self.inpaint_dir = root / DIR_INPAINT  # 即使旧模式也尝试读 inpainting
                    self._load_project()
                    return
            else:
                # 没有图片，创建子目录结构
                origin.mkdir(parents=True, exist_ok=True)
                QMessageBox.information(
                    self, "已创建项目结构",
                    f"已创建 {DIR_ORIGIN}/ 子目录。\n请将原图放入 {origin} 后重新打开。"
                )
                return
        
        # 确保所有目录存在
        json_dir.mkdir(parents=True, exist_ok=True)
        inpaint.mkdir(parents=True, exist_ok=True)
        
        self.project_root = root
        self.origin_dir = origin
        self.json_dir = json_dir
        self.inpaint_dir = inpaint
        
        self._load_project()
    
    def _migrate_to_project_structure(self, root: Path):
        """将旧的平铺结构迁移为项目子目录结构"""
        origin = root / DIR_ORIGIN
        json_dir = root / DIR_JSON
        inpaint = root / DIR_INPAINT
        
        origin.mkdir(parents=True, exist_ok=True)
        json_dir.mkdir(parents=True, exist_ok=True)
        inpaint.mkdir(parents=True, exist_ok=True)
        
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}
        
        moved_count = 0
        for f in root.iterdir():
            if f.is_file():
                if f.suffix.lower() in image_extensions:
                    shutil.move(str(f), str(origin / f.name))
                    moved_count += 1
                elif f.suffix.lower() == '.json' and f.name != META_FILE:
                    shutil.move(str(f), str(json_dir / f.name))
        
        self.project_root = root
        self.origin_dir = origin
        self.json_dir = json_dir
        self.inpaint_dir = inpaint
        
        QMessageBox.information(self, "迁移完成", f"已迁移 {moved_count} 个图片文件到 {DIR_ORIGIN}/")
        self._load_project()
    
    def _load_project(self):
        """加载项目：扫描图片、更新meta、刷新UI"""
        # 更新 meta.json
        self._update_meta()
        
        # 读取上次处理到的图片
        meta = self._read_meta()
        last_image = meta.get("last_image", "")
        
        # 扫描图片
        self.load_images_from_folder(str(self.origin_dir))
        
        # 恢复到上次处理的位置
        if last_image and self.image_files:
            for i, f in enumerate(self.image_files):
                if f.name == last_image:
                    self.current_index = i
                    self.load_current_image()
                    break
        
        # 更新项目路径显示
        if self.project_root:
            self.project_path_label.setText(f"📁 {self.project_root}")
            self.setWindowTitle(f"姿态标注修正工具 v2.1 — {self.project_root.name}")
    
    def _update_meta(self):
        """更新 meta.json（记录打开时间等协作信息）"""
        if not self.project_root:
            return
        
        meta_path = self.project_root / META_FILE
        meta = self._read_meta()
        
        # 更新字段
        import getpass
        username = getpass.getuser()
        now = datetime.now().isoformat(timespec='seconds')
        
        meta["last_opened"] = now
        meta["last_opened_by"] = username
        
        # 维护打开历史
        history = meta.get("open_history", [])
        history.append({"time": now, "user": username})
        # 只保留最近50条
        meta["open_history"] = history[-50:]
        
        # 统计图片数量
        if self.origin_dir and self.origin_dir.exists():
            image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}
            count = sum(1 for f in self.origin_dir.iterdir() 
                       if f.is_file() and f.suffix.lower() in image_extensions)
            meta["total_images"] = count
        
        self._write_meta(meta)
    
    def _read_meta(self) -> dict:
        """读取 meta.json"""
        if not self.project_root:
            return {}
        meta_path = self.project_root / META_FILE
        if meta_path.exists():
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}
    
    def _write_meta(self, meta: dict):
        """写入 meta.json"""
        if not self.project_root:
            return
        meta_path = self.project_root / META_FILE
        try:
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: failed to write meta.json: {e}")
    
    def _save_last_image_to_meta(self):
        """将当前处理的图片文件名记录到 meta.json"""
        if not self.project_root or not self.current_image_path:
            return
        meta = self._read_meta()
        meta["last_image"] = Path(self.current_image_path).name
        self._write_meta(meta)

    def _find_inpainting_image(self, image_name_stem: str) -> Optional[Path]:
        """在 inpainting/ 目录中查找同名（不同后缀也可以）的参考图"""
        if not self.inpaint_dir or not self.inpaint_dir.exists():
            return None
        
        image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp',
                           '.JPG', '.JPEG', '.PNG', '.BMP', '.TIFF', '.WEBP']
        
        for ext in image_extensions:
            candidate = self.inpaint_dir / (image_name_stem + ext)
            if candidate.exists():
                return candidate
        return None
    
    def _update_inpainting_preview(self):
        """更新右下角的 inpainting 参考图预览"""
        if not self.current_image_path:
            self.inpaint_label.setText("无图片")
            self.inpaint_filename_label.setText("")
            return
        
        stem = Path(self.current_image_path).stem
        inpaint_path = self._find_inpainting_image(stem)
        
        if inpaint_path:
            pixmap = QPixmap(str(inpaint_path))
            if not pixmap.isNull():
                # 缩放以适应预览区域
                scaled = pixmap.scaled(
                    self.inpaint_label.width() - 4, 
                    self.inpaint_label.maximumHeight() - 4,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.inpaint_label.setPixmap(scaled)
                self.inpaint_filename_label.setText(f"📎 {inpaint_path.name}")
            else:
                self.inpaint_label.setText("(加载失败)")
                self.inpaint_filename_label.setText(str(inpaint_path.name))
        else:
            self.inpaint_label.setText("无对应 inpainting 图")
            self.inpaint_label.setPixmap(QPixmap())  # 清除之前的图
            self.inpaint_filename_label.setText("")

    # ============================================================
    # ignore 相关
    # ============================================================

    def _move_corrupt_to_ignore(self):
        """将当前无法加载的图片（及其JSON）移入 ignore/图片损坏/，然后加载下一张"""
        image_path = Path(self.current_image_path)

        # 确定 ignore 目标目录
        base_dir = self.project_root if self.project_root else image_path.parent
        ignore_dir = base_dir / "ignore" / "图片损坏"
        ignore_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 移动图片
            shutil.move(str(image_path), str(ignore_dir / image_path.name))

            # 移动对应 JSON（如果有）
            if self.json_dir and self.json_dir != self.origin_dir:
                json_path = self.json_dir / (image_path.stem + '.json')
            else:
                json_path = image_path.with_suffix('.json')
            if json_path.exists():
                shutil.move(str(json_path), str(ignore_dir / json_path.name))

        except Exception as e:
            print(f"Warning: failed to move corrupt image: {e}")

        # 从列表中移除
        del self.image_files[self.current_index]

        if not self.image_files:
            self.canvas.image = None
            self.canvas.pose_data = PoseData()
            self.canvas.update()
            self.current_image_path = None
            self.current_annotation_path = None
            self.update_status()
            return

        if self.current_index >= len(self.image_files):
            self.current_index = len(self.image_files) - 1

        self.load_current_image()

    def move_to_ignore_category(self, category: str, custom_reason: str = ""):
        """将当前图片和JSON移动到 ignore/<category>/ 文件夹"""
        if not self.current_image_path:
            return

        image_path = Path(self.current_image_path)
        
        # JSON 路径：优先用项目结构
        if self.json_dir and self.json_dir != self.origin_dir:
            json_path = self.json_dir / (image_path.stem + '.json')
        else:
            json_path = image_path.with_suffix('.json')
        
        # 创建 ignore/<category>/ 文件夹（在 origin 目录旁边）
        folder_name = category
        base_dir = self.project_root if self.project_root else image_path.parent
        ignore_dir = base_dir / "ignore" / folder_name
        if not ignore_dir.exists():
            ignore_dir.mkdir(parents=True)
            
        try:
            # 先保存 skip_reason 到 JSON
            reason_text = custom_reason if custom_reason else category
            self.canvas.pose_data.skip_reason = reason_text
            
            # 保存 JSON（确保理由写入）
            data = self.canvas.pose_data.to_dict()
            # 确保JSON目录存在
            json_path.parent.mkdir(parents=True, exist_ok=True)
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
            
            if not self.image_files:
                self.canvas.image = None
                self.canvas.update()
                QMessageBox.information(self, "提示", "所有图片处理完毕")
                return

            if self.current_index >= len(self.image_files):
                self.current_index = len(self.image_files) - 1
                
            self.load_current_image()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"移动文件失败: {e}")

    def move_to_ignore(self):
        """[Delete键] 弹出选择对话框"""
        if not self.current_image_path:
            return
        items = ["美感不足", "难以补全", "背景失真", "比例失调", "图像模糊", "其他原因"]
        item, ok = QInputDialog.getItem(self, "选择ignore类别", "请选择跳过原因:", items, 0, False)
        if ok and item:
            if item == "其他原因":
                self.move_to_ignore_other()
            else:
                self.move_to_ignore_category(item)

    def move_to_ignore_other(self):
        """点击'其他原因'时弹出输入框"""
        if not self.current_image_path:
            return
        reason, ok = QInputDialog.getText(self, "其他原因", "请输入跳过理由:")
        if ok and reason.strip():
            self.move_to_ignore_category("其他", custom_reason=reason.strip())

    def update_skip_buttons(self):
        pass

    # ============================================================
    # 评分验证 & 导航
    # ============================================================
        
    def has_complete_scores(self) -> bool:
        pose = self.canvas.pose_data
        return (pose.novelty >= 0 and 
                pose.environment_interaction >= 0 and 
                pose.person_fit >= 0)
    
    def validate_before_navigate(self) -> bool:
        pose = self.canvas.pose_data
        if pose.skip_reason:
            return True
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

    def update_status(self):
        if self.current_image_path:
            filename = Path(self.current_image_path).name
            status = f"图片: {filename} ({self.current_index + 1}/{len(self.image_files)})"
        else:
            status = "未加载图片"
            
        if self.canvas.pose_data.skip_reason:
            status += f" | [已跳过: {self.canvas.pose_data.skip_reason}]"
        
        if self.canvas.selected_keypoint:
            kp = self.canvas.selected_keypoint
            vis_map = {0: "遮挡", 1: "可见"}
            status += f" | 选中: {kp.name} ({vis_map[kp.visibility]})"
            
        self.status_bar.showMessage(status)
            
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
            QMessageBox.information(self, "提示", f"{folder_path} 下没有图片")
            
    def load_current_image(self):
        if not self.image_files: return
        self.current_image_path = str(self.image_files[self.current_index])
        
        image = QImage(self.current_image_path)
        if image.isNull():
            # 加载失败：自动移入 ignore/图片损坏/
            failed_name = Path(self.current_image_path).name
            self._move_corrupt_to_ignore()
            self.status_bar.showMessage(f"⚠ 图片损坏已移除: {failed_name}", 3000)
            # _move_corrupt_to_ignore 内部会调整索引并递归加载下一张
            return
            
        self.canvas.set_image(image)
        self.load_annotation()
        
        # 加载完数据后，重置撤销栈
        self.canvas.undo_stack.clear()
        self.update_status()
        self.update_keypoint_list()
        
        # 更新 inpainting 预览
        self._update_inpainting_preview()
        
    def load_annotation(self):
        if not self.current_image_path: return
        
        image_path = Path(self.current_image_path)
        
        # JSON路径：优先从 annotations/ 目录加载
        if self.json_dir and self.json_dir != self.origin_dir:
            json_path = self.json_dir / (image_path.stem + '.json')
            # 也检查旧的同目录位置（兼容）
            old_json_path = image_path.with_suffix('.json')
            if not json_path.exists() and old_json_path.exists():
                json_path = old_json_path
        else:
            json_path = image_path.with_suffix('.json')
        
        pose_data = PoseData()
        
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        if len(data) > 0:
                            pose_data = PoseData.from_dict(data[0])
                    else:
                        pose_data = PoseData.from_dict(data)
            except Exception as e:
                print(f"Error loading JSON: {e}")
        
        self.canvas.set_pose_data(pose_data)
        self.current_annotation_path = str(json_path)
        
        # 更新评分UI
        self.update_score_ui(pose_data)
        self.update_skip_buttons()

        if self.canvas.pose_data.keypoints:
            first_kp = self.canvas.pose_data.keypoints[0]
            self.canvas.selected_keypoint = first_kp
            self.on_keypoint_selected(first_kp.name)

        if pose_data.has_valid_keypoints():
            self.canvas.focus_on_pose()
        else:
            self.canvas.fit_to_window()
    
    def update_score_ui(self, pose_data: PoseData):
        # 先全部取消选中，再设置正确的值
        for btn in self.novelty_btn_group.buttons():
            btn.setChecked(False)
        novelty = pose_data.novelty
        if novelty >= 0 and novelty in self.novelty_buttons:
            self.novelty_buttons[novelty].setChecked(True)
        
        for btn in self.env_btn_group.buttons():
            btn.setChecked(False)
        env_int = pose_data.environment_interaction
        if env_int >= 0 and env_int in self.env_buttons:
            self.env_buttons[env_int].setChecked(True)
        
        for btn in self.person_btn_group.buttons():
            btn.setChecked(False)
        person_fit = pose_data.person_fit
        if person_fit >= 0 and person_fit in self.person_buttons:
            self.person_buttons[person_fit].setChecked(True)
        
    def save_current(self):
        if not self.current_annotation_path: return
        try:
            # 确保目录存在
            ann_path = Path(self.current_annotation_path)
            ann_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = [self.canvas.pose_data.to_dict()]
            with open(self.current_annotation_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # 记录当前处理位置
            self._save_last_image_to_meta()
            
            self.status_bar.showMessage(f"已保存: {ann_path.name}", 2000)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存失败: {e}")

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
        while self.current_index < len(self.image_files) - 1:
            self.current_index += 1
            self.load_current_image()
            if self.should_process_image():
                return
        self.current_index = original_index
        self.load_current_image()
        QMessageBox.information(self, "提示", "没有更多需要处理的图片")
            
    def should_process_image(self) -> bool:
        """判断当前图片是否还需要处理（评分不完整）"""
        pose = self.canvas.pose_data
        if pose.skip_reason:
            return False  # 已标记跳过
        return not self.has_complete_scores()
            
    def fit_to_window(self):
        self.canvas.fit_to_window()

    def focus_on_pose(self):
        self.canvas.focus_on_pose()
        
    def toggle_skeleton(self):
        self.canvas.show_skeleton = not self.canvas.show_skeleton
        self.skeleton_btn.setText("骨架 (H)" if self.canvas.show_skeleton else "骨架OFF")
        self.canvas.update()
        
    def undo(self):
        if self.canvas.undo_stack.undo():
            self.canvas.update()
            self.update_keypoint_list()
            
    def redo(self):
        if self.canvas.undo_stack.redo():
            self.canvas.update()
            self.update_keypoint_list()
        
    def _setup_shortcuts(self):
        """使用 QShortcut 注册全局快捷键，避免焦点问题"""
        QShortcut(QKeySequence(Qt.Key_Left), self, self.prev_image)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.next_image)
        QShortcut(QKeySequence(Qt.Key_O), self, self.next_processable_image)
        QShortcut(QKeySequence(Qt.Key_Tab), self, lambda: self.switch_keypoint(1))
        QShortcut(QKeySequence(Qt.ShiftModifier | Qt.Key_Tab), self, lambda: self.switch_keypoint(-1))
        QShortcut(QKeySequence(Qt.Key_H), self, self.toggle_skeleton)
        QShortcut(QKeySequence(Qt.Key_Delete), self, self.move_to_ignore)
        QShortcut(QKeySequence(Qt.Key_W), self, self.focus_on_pose)
        QShortcut(QKeySequence(Qt.Key_E), self, self.fit_to_window)
        # 1/2/3/4/5 对应五个丢弃理由
        QShortcut(QKeySequence(Qt.Key_1), self, lambda: self.move_to_ignore_category("美感不足"))
        QShortcut(QKeySequence(Qt.Key_2), self, lambda: self.move_to_ignore_category("难以补全"))
        QShortcut(QKeySequence(Qt.Key_3), self, lambda: self.move_to_ignore_category("背景失真"))
        QShortcut(QKeySequence(Qt.Key_4), self, lambda: self.move_to_ignore_category("比例失调"))
        QShortcut(QKeySequence(Qt.Key_5), self, lambda: self.move_to_ignore_category("图像模糊"))
        # S/D/空格 用于切换可见性，需要转发给 canvas
        QShortcut(QKeySequence(Qt.Key_S), self, lambda: self.canvas.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_S, Qt.NoModifier)))
        QShortcut(QKeySequence(Qt.Key_D), self, lambda: self.canvas.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_D, Qt.NoModifier)))
        QShortcut(QKeySequence(Qt.Key_Space), self, lambda: self.canvas.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier)))
            
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