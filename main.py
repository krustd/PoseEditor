import sys
import json
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QStatusBar, QListWidget, QListWidgetItem, QPushButton,
    QFileDialog, QMessageBox, QSplitter, QFrame
)
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer, QObject
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
        """创建关键点的副本"""
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
    """姿态数据模型"""
    def __init__(self):
        self.keypoints = self._init_keypoints()
        
    def copy(self) -> 'PoseData':
        """创建姿态数据的副本"""
        new_pose = PoseData()
        new_pose.keypoints = [kp.copy() for kp in self.keypoints]
        return new_pose
        
    def _init_keypoints(self) -> List[Keypoint]:
        """初始化COCO格式的17个关键点"""
        keypoint_names = [
            "nose", "left_eye", "right_eye", "left_ear", "right_ear",
            "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
            "left_wrist", "right_wrist", "left_hip", "right_hip",
            "left_knee", "right_knee", "left_ankle", "right_ankle"
        ]
        return [Keypoint(name) for name in keypoint_names]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "keypoints": [kp.to_dict() for kp in self.keypoints]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PoseData':
        pose = cls()
        for i, kp_data in enumerate(data.get("keypoints", [])):
            if i < len(pose.keypoints):
                pose.keypoints[i] = Keypoint.from_dict(kp_data)
        return pose


class UndoCommand:
    """撤销命令基类"""
    def undo(self):
        pass
        
    def redo(self):
        pass


class KeypointChangeCommand(UndoCommand):
    """关键点变更命令 - 修改版"""
    def __init__(self, pose_data: PoseData, keypoint_index: int, old_state: Keypoint, new_state: Keypoint):
        self.pose_data = pose_data
        self.keypoint_index = keypoint_index
        # 保存状态的数据副本，而不是直接保存对象引用
        self.old_state = old_state
        self.new_state = new_state
        
    def _update_keypoint(self, state: Keypoint):
        """辅助方法：只更新属性，不替换对象"""
        # 获取当前列表里真正的那个对象
        current_kp = self.pose_data.keypoints[self.keypoint_index]
        # 更新它的属性
        current_kp.x = state.x
        current_kp.y = state.y
        current_kp.visibility = state.visibility
        # 注意：不要修改 name，也不要替换整个 current_kp 对象
        
    def undo(self):
        self._update_keypoint(self.old_state)
        
    def redo(self):
        self._update_keypoint(self.new_state)


class UndoStack(QObject):
    """撤销栈"""
    can_undo_changed = Signal(bool)
    can_redo_changed = Signal(bool)
    
    def __init__(self):
        super().__init__()
        self.undo_stack = []
        self.redo_stack = []
        
    def push(self, command: UndoCommand):
        """推送新命令"""
        self.undo_stack.append(command)
        self.redo_stack.clear()
        self.can_undo_changed.emit(True)
        self.can_redo_changed.emit(False)
        
    def undo(self) -> bool:
        """撤销"""
        if not self.undo_stack:
            return False
            
        command = self.undo_stack.pop()
        command.undo()
        self.redo_stack.append(command)
        
        self.can_undo_changed.emit(bool(self.undo_stack))
        self.can_redo_changed.emit(True)
        return True
        
    def redo(self) -> bool:
        """重做"""
        if not self.redo_stack:
            return False
            
        command = self.redo_stack.pop()
        command.redo()
        self.undo_stack.append(command)
        
        self.can_undo_changed.emit(True)
        self.can_redo_changed.emit(bool(self.redo_stack))
        return True
        
    def clear(self):
        """清空撤销栈"""
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.can_undo_changed.emit(False)
        self.can_redo_changed.emit(False)


class Canvas(QWidget):
    """画布组件，用于显示图片和关键点"""
    keypoint_selected = Signal(str)  # 关键点被选中信号
    
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
        
        # 骨架连接关系（COCO格式）
        self.skeleton = [
            (0, 1), (0, 2), (1, 3), (2, 4),  # 头部
            (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),  # 上肢
            (5, 11), (6, 12), (11, 12),  # 躯干
            (11, 13), (13, 15), (12, 14), (14, 15)  # 下肢
        ]
        
        self.setMinimumSize(800, 600)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        
    def set_image(self, image: QImage):
        """设置显示的图片"""
        self.image = image
        self.fit_to_window()
        self.update()
        
    def set_pose_data(self, pose_data: PoseData):
        """设置姿态数据"""
        self.pose_data = pose_data
        self.update()
        
    def fit_to_window(self):
        """适应窗口大小"""
        if not self.image:
            return
            
        widget_size = self.size()
        image_size = self.image.size()
        
        scale_x = widget_size.width() / image_size.width()
        scale_y = widget_size.height() / image_size.height()
        self.scale = min(scale_x, scale_y) * 0.9  # 留10%边距
        
        # 居中显示
        scaled_size = image_size * self.scale
        self.offset = QPointF(
            (widget_size.width() - scaled_size.width()) / 2,
            (widget_size.height() - scaled_size.height()) / 2
        )
        
    def image_to_widget(self, point: QPointF) -> QPointF:
        """图片坐标转窗口坐标"""
        return QPointF(point.x() * self.scale + self.offset.x(),
                      point.y() * self.scale + self.offset.y())
    
    def widget_to_image(self, point: QPointF) -> QPointF:
        """窗口坐标转图片坐标"""
        return QPointF((point.x() - self.offset.x()) / self.scale,
                      (point.y() - self.offset.y()) / self.scale)
    
    def get_keypoint_at(self, pos: QPointF) -> Optional[Keypoint]:
        """获取指定位置的关键点"""
        if not self.image:
            return None
            
        image_pos = self.widget_to_image(pos)
        
        for kp in self.pose_data.keypoints:
            # if kp.visibility == 0:  
            #     continue
                
            kp_pos = self.image_to_widget(QPointF(kp.x, kp.y))
            distance = (kp_pos - pos).manhattanLength()
            
            if distance < 10:  
                return kp
                
        return None
    
    def paintEvent(self, event):
        """绘制事件"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制背景
        painter.fillRect(self.rect(), QColor(50, 50, 50))
        
        if not self.image:
            return
            
        # 绘制图片
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        painter.drawImage(0, 0, self.image)
        painter.restore()
        
        # 绘制骨架和关键点
        if self.show_skeleton:
            self.draw_skeleton(painter)
        self.draw_keypoints(painter)
        
    def draw_skeleton(self, painter: QPainter):
        """绘制骨架连线"""
        if not self.image:
            return
            
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        
        pen = QPen(QColor(100, 200, 100, 150), 2)
        painter.setPen(pen)
        
        for start_idx, end_idx in self.skeleton:
            start_kp = self.pose_data.keypoints[start_idx]
            end_kp = self.pose_data.keypoints[end_idx]
            
            # 只有当两个点都可见时才绘制连线
            if start_kp.visibility > 0 and end_kp.visibility > 0:
                painter.drawLine(QPointF(start_kp.x, start_kp.y), 
                               QPointF(end_kp.x, end_kp.y))
        
        painter.restore()
        
    def draw_keypoints(self, painter: QPainter):
        """绘制关键点"""
        if not self.image:
            return
            
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        
        for i, kp in enumerate(self.pose_data.keypoints):
            # === 修改点 1: 删除了 "if kp.visibility == 0: continue" ===
            # 现在即使是不可见的点也会被绘制，方便你找到它们
            
            # === 修改点 2: 定义状态颜色 ===
            if kp.visibility == 2:  # 可见 -> 绿色
                color = QColor(0, 255, 0, int(255 * self.keypoint_opacity))
                border_color = Qt.black
            elif kp.visibility == 1:  # 遮挡 -> 橙色
                color = QColor(255, 165, 0, int(255 * self.keypoint_opacity))
                border_color = Qt.black
            else:  # [新增] 不可见/未标记 (0) -> 红色 (带透明度)
                # 使用红色表示"待处理"，方便在图片上通过颜色区分进度
                color = QColor(255, 0, 0, 150) 
                border_color = Qt.white  # 使用白色边框增强对比度
                
            # 如果是选中的点，覆盖为高亮黄色
            if self.selected_keypoint == kp:
                color = QColor(255, 255, 0)
                border_color = Qt.black
                
            painter.setBrush(QBrush(color))
            # 设置边框颜色（未标记的点用白边框更显眼）
            painter.setPen(QPen(border_color, 1))
            
            # 绘制圆点
            radius = 5 / self.scale  # 固定屏幕大小
            painter.drawEllipse(QPointF(kp.x, kp.y), radius, radius)
            
        painter.restore()
        
    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件 - 修改版"""
        if event.button() == Qt.LeftButton:
            # === 新增逻辑：按住 Ctrl 键 + 点击 = 瞬移当前选中的点 ===
            if event.modifiers() & Qt.ControlModifier:
                if self.selected_keypoint:
                    # 1. 计算鼠标点击在图片上的坐标
                    image_pos = self.widget_to_image(event.pos())
                    
                    # 2. 准备撤销数据（记录移动前的状态）
                    keypoint_index = self.pose_data.keypoints.index(self.selected_keypoint)
                    old_state = self.selected_keypoint.copy()
                    
                    # 3. 修改关键点坐标并设为可见
                    self.selected_keypoint.x = max(0, image_pos.x())
                    self.selected_keypoint.y = max(0, image_pos.y())
                    self.selected_keypoint.visibility = 2  # 强制设为可见
                    
                    # 4. 记录到撤销栈
                    new_state = self.selected_keypoint.copy()
                    command = KeypointChangeCommand(self.pose_data, keypoint_index, old_state, new_state)
                    self.undo_stack.push(command)
                    
                    self.update()
                    return  # 处理完毕，直接返回，不再执行下面的选中逻辑
            # ====================================================

            # 原有的选中逻辑（如果没有按 Ctrl）
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
        """鼠标移动事件"""
        if self.dragging and self.selected_keypoint:
            # 拖拽关键点
            image_pos = self.widget_to_image(event.pos())
            self.selected_keypoint.x = max(0, image_pos.x())
            self.selected_keypoint.y = max(0, image_pos.y())
            
            # 拖拽时默认设为可见
            if self.selected_keypoint.visibility == 0:
                self.selected_keypoint.visibility = 2
                
            self.update()
        elif self.panning:
            # 平移画布
            delta = event.pos() - self.last_pos
            self.offset += delta
            self.last_pos = event.pos()
            self.update()
            
    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放事件"""
        if event.button() == Qt.LeftButton and self.dragging and self.selected_keypoint and self.drag_start_pos:
            # 创建撤销命令
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
        """滚轮事件 - 缩放"""
        if not self.image:
            return
            
        # 获取鼠标位置对应的图片坐标
        mouse_pos = event.position()
        image_pos_before = self.widget_to_image(mouse_pos)
        
        # 计算新的缩放比例
        delta = event.angleDelta().y() / 120
        scale_factor = 1.1 if delta > 0 else 0.9
        new_scale = self.scale * scale_factor
        
        # 限制缩放范围
        if 0.1 <= new_scale <= 5.0:
            # 调整偏移以保持鼠标位置不变
            self.scale = new_scale
            image_pos_after = self.widget_to_image(mouse_pos)
            
            offset_delta = QPointF(
                (image_pos_before.x() - image_pos_after.x()) * self.scale,
                (image_pos_before.y() - image_pos_after.y()) * self.scale
            )
            self.offset += offset_delta
            
            self.update()
            
    def keyPressEvent(self, event: QKeyEvent):
        """键盘事件"""
        if not self.selected_keypoint:
            return
            
        key = event.key()
        keypoint_index = self.pose_data.keypoints.index(self.selected_keypoint)
        old_state = self.selected_keypoint.copy()
        
        if key == Qt.Key_A:
            # A键 - 标记为遮挡
            self.selected_keypoint.visibility = 1
            new_state = self.selected_keypoint.copy()
            command = KeypointChangeCommand(self.pose_data, keypoint_index, old_state, new_state)
            self.undo_stack.push(command)
            self.update()
        elif key == Qt.Key_D:
            # D键 - 标记为不可见
            self.selected_keypoint.visibility = 0
            new_state = self.selected_keypoint.copy()
            command = KeypointChangeCommand(self.pose_data, keypoint_index, old_state, new_state)
            self.undo_stack.push(command)
            self.update()
        elif key == Qt.Key_S:
            # S键 - 重置到可见状态
            self.selected_keypoint.visibility = 2
            new_state = self.selected_keypoint.copy()
            command = KeypointChangeCommand(self.pose_data, keypoint_index, old_state, new_state)
            self.undo_stack.push(command)
            self.update()


class PoseEditor(QMainWindow):
    """姿态标注编辑器主窗口"""
    
    def __init__(self):
        super().__init__()
        self.current_image_path = None
        self.current_annotation_path = None
        self.image_files = []
        self.current_index = 0
        self.undo_stack = []
        self.redo_stack = []
        
        self.init_ui()
        self.load_images()
        
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("姿态标注修正工具")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout(central_widget)
        
        # 创建分割器
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        # 左侧：画布
        self.canvas = Canvas()
        self.canvas.keypoint_selected.connect(self.on_keypoint_selected)
        splitter.addWidget(self.canvas)
        
        # 右侧：控制面板
        control_panel = self.create_control_panel()
        splitter.addWidget(control_panel)
        
        # 设置分割器比例
        splitter.setSizes([800, 400])
        
        # 创建状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.update_status()
        
        # 创建菜单栏
        self.create_menu_bar()
        
    def create_control_panel(self) -> QWidget:
        """创建控制面板"""
        panel = QFrame()
        panel.setMaximumWidth(300)
        layout = QVBoxLayout(panel)
        
        # 文件操作
        file_group = QFrame()
        file_layout = QVBoxLayout(file_group)
        
        self.open_btn = QPushButton("打开图片文件夹")
        self.open_btn.clicked.connect(self.open_folder)
        file_layout.addWidget(self.open_btn)
        
        self.prev_btn = QPushButton("上一张 (←)")
        self.prev_btn.clicked.connect(self.prev_image)
        file_layout.addWidget(self.prev_btn)
        
        self.next_btn = QPushButton("下一张 (→)")
        self.next_btn.clicked.connect(self.next_image)
        file_layout.addWidget(self.next_btn)
        
        self.save_btn = QPushButton("保存 (Ctrl+S)")
        self.save_btn.clicked.connect(self.save_current)
        file_layout.addWidget(self.save_btn)
        
        layout.addWidget(file_group)
        
        # 关键点列表
        layout.addWidget(QLabel("关键点列表:"))
        self.keypoint_list = QListWidget()
        self.keypoint_list.itemClicked.connect(self.on_list_item_clicked)
        layout.addWidget(self.keypoint_list)
        
        # 更新关键点列表
        self.update_keypoint_list()
        
        # 视图控制
        view_group = QFrame()
        view_layout = QVBoxLayout(view_group)
        
        layout.addWidget(QLabel("视图控制:"))
        
        self.fit_btn = QPushButton("适应窗口")
        self.fit_btn.clicked.connect(self.fit_to_window)
        view_layout.addWidget(self.fit_btn)
        
        self.skeleton_btn = QPushButton("隐藏骨架 (H)")
        self.skeleton_btn.clicked.connect(self.toggle_skeleton)
        view_layout.addWidget(self.skeleton_btn)
        
        layout.addWidget(view_group)
        
        # 操作提示
        layout.addWidget(QLabel("操作提示:"))
        help_text = QLabel(
            "• 左键拖拽: 移动关键点\n"
            "• A键: 标记为遮挡\n"
            "• Del键: 删除关键点\n"
            "• R键: 重置关键点\n"
            "• 滚轮: 缩放\n"
            "• 右键拖拽: 平移\n"
            "• Tab: 切换关键点"
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(help_text)
        
        layout.addStretch()
        
        return panel
        
    def create_menu_bar(self):
        """创建菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件")
        
        open_action = QAction("打开文件夹", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_folder)
        file_menu.addAction(open_action)
        
        save_action = QAction("保存", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_current)
        file_menu.addAction(save_action)
        
        # 编辑菜单
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
        """更新关键点列表"""
        self.keypoint_list.clear()
        for kp in self.canvas.pose_data.keypoints:
            item = QListWidgetItem(kp.name)
            
            # 根据可见性设置颜色
            if kp.visibility == 2:
                item.setForeground(Qt.green)
            elif kp.visibility == 1:
                item.setForeground(Qt.yellow)
            else:
                item.setForeground(Qt.gray)
                
            self.keypoint_list.addItem(item)
            
    def on_keypoint_selected(self, name: str):
        """关键点被选中时的回调"""
        self.update_status()
        
        # 更新列表选中状态
        for i in range(self.keypoint_list.count()):
            if self.keypoint_list.item(i).text() == name:
                self.keypoint_list.setCurrentRow(i)
                break
                
    def on_list_item_clicked(self, item: QListWidgetItem):
        """列表项被点击时的回调"""
        kp_name = item.text()
        for kp in self.canvas.pose_data.keypoints:
            if kp.name == kp_name:
                self.canvas.selected_keypoint = kp
                self.canvas.update()
                self.update_status()
                break
                
    def update_status(self):
        """更新状态栏"""
        if self.current_image_path:
            filename = Path(self.current_image_path).name
            status = f"当前图片: {filename} ({self.current_index + 1}/{len(self.image_files)})"
        else:
            status = "未加载图片"
            
        if self.canvas.selected_keypoint:
            kp = self.canvas.selected_keypoint
            visibility_name = {0: "不可见", 1: "遮挡", 2: "可见"}[kp.visibility]
            status += f" | 当前选中: {kp.name} ({visibility_name})"
            
        self.status_bar.showMessage(status)
        
    def open_folder(self):
        """打开图片文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if folder:
            self.load_images_from_folder(folder)
            
    def load_images_from_folder(self, folder: str):
        """从文件夹加载图片"""
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
            
    def load_images(self):
        """加载图片（示例）"""
        # 这里可以加载默认的示例图片
        pass
        
    def load_current_image(self):
        """加载当前图片"""
        if not self.image_files:
            return
            
        self.current_image_path = str(self.image_files[self.current_index])
        
        # 加载图片
        image = QImage(self.current_image_path)
        if image.isNull():
            QMessageBox.warning(self, "错误", f"无法加载图片: {self.current_image_path}")
            return
            
        self.canvas.set_image(image)
        
        # 加载对应的标注文件
        self.load_annotation()
        
        # 更新UI
        self.update_status()
        self.update_keypoint_list()
        
    def load_annotation(self):
        """加载标注文件"""
        if not self.current_image_path:
            return
            
        # 查找对应的JSON文件
        image_path = Path(self.current_image_path)
        json_path = image_path.with_suffix('.json')
        
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    pose_data = PoseData.from_dict(data)
                    self.canvas.set_pose_data(pose_data)
            except Exception as e:
                QMessageBox.warning(self, "错误", f"无法加载标注文件: {e}")
                self.canvas.set_pose_data(PoseData())  # 使用空的姿态数据
        else:
            # 如果没有标注文件，创建空的姿态数据
            self.canvas.set_pose_data(PoseData())
            
        self.current_annotation_path = str(json_path)
        if self.canvas.pose_data.keypoints:
            first_kp = self.canvas.pose_data.keypoints[0]
            self.canvas.selected_keypoint = first_kp
            self.on_keypoint_selected(first_kp.name) # 刷新列表高亮
            self.canvas.update()
        
    def save_current(self):
        """保存当前标注"""
        if not self.current_annotation_path:
            return
            
        try:
            data = self.canvas.pose_data.to_dict()
            with open(self.current_annotation_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
            self.status_bar.showMessage(f"已保存: {Path(self.current_annotation_path).name}", 2000)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存失败: {e}")
            
    def prev_image(self):
        """上一张图片"""
        if self.image_files and self.current_index > 0:
            self.save_current()  # 自动保存当前
            self.current_index -= 1
            self.load_current_image()
            
    def next_image(self):
        """下一张图片"""
        if self.image_files and self.current_index < len(self.image_files) - 1:
            self.save_current()  # 自动保存当前
            self.current_index += 1
            self.load_current_image()
            
    def fit_to_window(self):
        """适应窗口大小"""
        self.canvas.fit_to_window()
        self.canvas.update()
        
    def toggle_skeleton(self):
        """切换骨架显示"""
        self.canvas.show_skeleton = not self.canvas.show_skeleton
        self.skeleton_btn.setText("显示骨架" if not self.canvas.show_skeleton else "隐藏骨架 (H)")
        self.canvas.update()
        
    def undo(self):
        """撤销操作"""
        if self.canvas.undo_stack.undo():
            self.canvas.update()
            self.update_keypoint_list()
            self.update_status()
            
    def redo(self):
        """重做操作"""
        if self.canvas.undo_stack.redo():
            self.canvas.update()
            self.update_keypoint_list()
            self.update_status()
        
    def keyPressEvent(self, event: QKeyEvent):
        """键盘事件"""
        key = event.key()
        
        # 方向键切换图片
        if key == Qt.Key_Left:
            self.prev_image()
        elif key == Qt.Key_Right:
            self.next_image()
        # Tab键切换关键点
        elif key == Qt.Key_Tab:
            self.switch_keypoint(1)
        elif key == Qt.Key_Backtab:
            self.switch_keypoint(-1)
        # Ctrl+S 保存
        elif key == Qt.Key_S and event.modifiers() & Qt.ControlModifier:
            self.save_current()
        else:
            # 其他按键传递给画布处理
            self.canvas.keyPressEvent(event)
            
    def switch_keypoint(self, direction: int):
        """切换关键点选择"""
        if not self.canvas.pose_data.keypoints:
            return
            
        # 找到当前选中的关键点索引
        current_idx = -1
        if self.canvas.selected_keypoint:
            for i, kp in enumerate(self.canvas.pose_data.keypoints):
                if kp == self.canvas.selected_keypoint:
                    current_idx = i
                    break
                    
        # 计算新的索引
        new_idx = (current_idx + direction) % len(self.canvas.pose_data.keypoints)
        
        # 选择新的关键点
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
