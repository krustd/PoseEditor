import sys
import json
import shutil
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QStatusBar, QListWidget, QListWidgetItem, QPushButton,
    QFileDialog, QMessageBox, QSplitter, QFrame, QSpinBox, QGroupBox,
    QButtonGroup, QGridLayout  # 新增引用
)
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QObject
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QBrush, QColor, 
    QMouseEvent, QKeyEvent, QWheelEvent, QAction
)


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
    """姿态数据模型 - 新增评分字段"""
    def __init__(self):
        self.keypoints = self._init_keypoints()
        self.score = -1  # 新增：默认评分为 -1 (代表未评分)
        
    def copy(self) -> 'PoseData':
        new_pose = PoseData()
        new_pose.keypoints = [kp.copy() for kp in self.keypoints]
        new_pose.score = self.score
        return new_pose
        
    def _init_keypoints(self) -> List[Keypoint]:
        keypoint_names = [
            "nose", "left_eye", "right_eye", "left_ear", "right_ear",
            "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
            "left_wrist", "right_wrist", "left_hip", "right_hip",
            "left_knee", "right_knee", "left_ankle", "right_ankle"
        ]
        return [Keypoint(name) for name in keypoint_names]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,  # 保存评分
            "keypoints": [kp.to_dict() for kp in self.keypoints]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PoseData':
        pose = cls()
        pose.score = data.get("score", -1)  # 读取评分
        for i, kp_data in enumerate(data.get("keypoints", [])):
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
            (11, 13), (13, 15), (12, 14), (14, 15)
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
        
        for i, kp in enumerate(self.pose_data.keypoints):
            if kp.visibility == 2:
                color = QColor(0, 255, 0, int(255 * self.keypoint_opacity))
                border_color = Qt.black
            elif kp.visibility == 1:
                color = QColor(255, 165, 0, int(255 * self.keypoint_opacity))
                border_color = Qt.black
            else:
                color = QColor(255, 0, 0, 150) 
                border_color = Qt.white
                
            if self.selected_keypoint == kp:
                color = QColor(255, 255, 0)
                border_color = Qt.black
                
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(border_color, 1))
            radius = 5 / self.scale 
            painter.drawEllipse(QPointF(kp.x, kp.y), radius, radius)
            
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
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.next_btn)
        file_layout.addLayout(nav_layout)
        
        self.save_btn = QPushButton("保存 (Ctrl+S)")
        self.save_btn.clicked.connect(self.save_current)
        file_layout.addWidget(self.save_btn)
        
        # [新增功能 2] 废弃按钮
        self.ignore_btn = QPushButton("标记为废弃/移动到Ignore (Del)")
        self.ignore_btn.setStyleSheet("background-color: #ffcccc; color: darkred;")
        self.ignore_btn.clicked.connect(self.move_to_ignore)
        file_layout.addWidget(self.ignore_btn)
        
        layout.addWidget(file_group)
        
        # --- [修改] 评分区: 替换 SpinBox 为 0-10 按钮组 ---
        score_group = QGroupBox("姿态美学评分")
        score_container_layout = QVBoxLayout(score_group)
        
        # 使用 Grid 布局放置按钮
        score_grid = QGridLayout()
        score_grid.setSpacing(5)
        
        self.score_group_btn = QButtonGroup(self)
        self.score_group_btn.setExclusive(True)
        self.score_group_btn.idClicked.connect(self.on_score_button_clicked)
        
        # 创建 0-10 的按钮
        for i in range(11):
            btn = QPushButton(str(i))
            btn.setCheckable(True)
            btn.setFixedSize(30, 30) # 设置固定大小，类似方块
            
            # 设置样式：选中时变蓝，未选中时普通
            btn.setStyleSheet("""
                QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; }
                QPushButton:checked { background-color: #0078d7; color: white; border: 1px solid #005a9e; }
            """)
            
            self.score_group_btn.addButton(btn, i) # id = 分数
            
            # 计算行和列 (两行显示: 0-5, 6-10)
            row = 0 if i <= 5 else 1
            col = i if i <= 5 else i - 6
            score_grid.addWidget(btn, row, col)
            
        # 添加一个 "N/A" 按钮用来表示 -1
        na_btn = QPushButton("N/A")
        na_btn.setCheckable(True)
        na_btn.setFixedSize(30, 30)
        na_btn.setToolTip("未评分")
        na_btn.setStyleSheet("""
            QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; color: gray; }
            QPushButton:checked { background-color: #999; color: white; }
        """)
        self.score_group_btn.addButton(na_btn, 11) 
        score_grid.addWidget(na_btn, 1, 5)
        
        # 默认选中 N/A 按钮 (表示未评分)
        na_btn.setChecked(True)
            
        score_container_layout.addLayout(score_grid)
        layout.addWidget(score_group)
        
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
            "• A: 遮挡 | D: 不可见 | S: 可见\n"
            "• Tab/Shift+Tab: 切换点 | Delete: 移至Ignore\n"
            "• Ctrl+Z/Y: 撤销/重做 | Ctrl+S: 保存"
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
            item = QListWidgetItem(kp.name)
            if kp.visibility == 2: item.setForeground(Qt.green)
            elif kp.visibility == 1: item.setForeground(Qt.darkYellow)
            else: item.setForeground(Qt.gray)
            self.keypoint_list.addItem(item)
            
    def on_keypoint_selected(self, name: str):
        self.update_status()
        for i in range(self.keypoint_list.count()):
            if self.keypoint_list.item(i).text() == name:
                self.keypoint_list.setCurrentRow(i)
                break
                
    def on_list_item_clicked(self, item: QListWidgetItem):
        kp_name = item.text()
        for kp in self.canvas.pose_data.keypoints:
            if kp.name == kp_name:
                self.canvas.selected_keypoint = kp
                self.canvas.update()
                self.update_status()
                break
    
    def on_score_button_clicked(self, score_id):
        """[修改] 评分按钮点击回调"""
        if score_id == 11:
            self.canvas.pose_data.score = -1
        else:
            self.canvas.pose_data.score = score_id

        
    def update_status(self):
        if self.current_image_path:
            filename = Path(self.current_image_path).name
            status = f"图片: {filename} ({self.current_index + 1}/{len(self.image_files)})"
        else:
            status = "未加载图片"
            
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
                    pose_data = PoseData.from_dict(data)
            except Exception as e:
                print(f"Error loading JSON: {e}")
        
        self.canvas.set_pose_data(pose_data)
        self.current_annotation_path = str(json_path)
        
        current_score = pose_data.score
        if current_score is not None:
            try:
                current_score = int(current_score)
            except ValueError:
                current_score = -1
        else:
            current_score = -1
        target_btn_id = 11 if current_score == -1 else current_score
        btn = self.score_group_btn.button(target_btn_id)
        
        if btn:
            btn.setChecked(True)
        else:
            fallback_btn = self.score_group_btn.button(11)
            if fallback_btn: fallback_btn.setChecked(True)
        
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
        
    def save_current(self):
        if not self.current_annotation_path: return
        try:
            data = self.canvas.pose_data.to_dict()
            with open(self.current_annotation_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.status_bar.showMessage(f"已保存: {Path(self.current_annotation_path).name}", 2000)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存失败: {e}")

    def move_to_ignore(self):
        """[新增功能 2] 将当前图片和JSON移动到 ignore 文件夹"""
        if not self.current_image_path:
            return
            
        # 确认对话框（可选，为了效率可以注释掉）
        # reply = QMessageBox.question(self, '确认', '确定要将此图片标记为废弃吗？', 
        #                              QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        # if reply == QMessageBox.No:
        #     return

        image_path = Path(self.current_image_path)
        json_path = image_path.with_suffix('.json')
        
        ignore_dir = image_path.parent / "ignore"
        if not ignore_dir.exists():
            ignore_dir.mkdir()
            
        try:
            # 移动图片
            shutil.move(str(image_path), str(ignore_dir / image_path.name))
            
            # 如果有 JSON 也移动
            if json_path.exists():
                shutil.move(str(json_path), str(ignore_dir / json_path.name))
                
            print(f"Moved {image_path.name} to ignore/")
            
            # 从列表中移除
            del self.image_files[self.current_index]
            
            # 如果列表空了
            if not self.image_files:
                self.canvas.image = None
                self.canvas.update()
                QMessageBox.information(self, "提示", "所有图片处理完毕")
                return

            # 修正索引（保持当前索引，因为后面元素前移了）
            if self.current_index >= len(self.image_files):
                self.current_index = len(self.image_files) - 1
                
            # 加载下一张
            self.load_current_image()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"移动文件失败: {e}")

    def prev_image(self):
        if self.image_files and self.current_index > 0:
            self.save_current()
            self.current_index -= 1
            self.load_current_image()
            
    def next_image(self):
        if self.image_files and self.current_index < len(self.image_files) - 1:
            self.save_current()
            self.current_index += 1
            self.load_current_image()
            
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
        elif key == Qt.Key_Right:
            self.next_image()
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