"""主窗口与项目工作流。"""

import getpass
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QImage, QKeyEvent, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .constants import (
    APP_VERSION,
    DIR_INPAINT,
    DIR_JSON,
    DIR_ORIGIN,
    IGNORE_CATEGORIES,
    IMAGE_EXTENSIONS,
    INPAINT_EXTENSIONS,
    META_FILE,
)
from .models import PoseData
from .widgets.canvas import Canvas
from .widgets.tooltip import DelayedTooltipFilter


class PoseEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_image_path = None
        self.current_annotation_path = None
        self.image_files = []
        self.current_index = 0

        # 项目文件夹路径
        self.project_root = None  # 项目根目录
        self.origin_dir = None  # images/
        self.json_dir = None  # annotations/
        self.inpaint_dir = None  # inpainting/

        # 新增评分和跳过按钮的引用
        self.score_buttons = {}
        self.skip_buttons = []

        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(f"姿态标注修正工具 v{APP_VERSION}")
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
            f"  {DIR_INPAINT}/  — Inpainting 参考图\n"
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

        # --- 移至 Ignore ---
        skip_group = QGroupBox("移至 Ignore（不可撤销）")
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
        self.ignore_aesthetic_btn.setToolTip(
            "1 | 美感不足。如果图像不是具有美感的人物照片（例如日常照片），则可点击该按钮跳过。"
        )
        self.ignore_aesthetic_btn.clicked.connect(
            lambda: self.move_to_ignore_category("美感不足")
        )
        self.ignore_aesthetic_btn.setStyleSheet(ignore_btn_style)
        skip_layout_top.addWidget(self.ignore_aesthetic_btn)

        self.ignore_incomplete_btn = QPushButton("2.难以补全")
        self.ignore_incomplete_btn.setToolTip(
            "2 | 难以补全。如果图像中的人物下半身都在画面外，难以拖拽画面外的遮挡点到猜测位置，则点它跳过。"
        )
        self.ignore_incomplete_btn.clicked.connect(
            lambda: self.move_to_ignore_category("难以补全")
        )
        self.ignore_incomplete_btn.setStyleSheet(ignore_btn_style)
        skip_layout_top.addWidget(self.ignore_incomplete_btn)

        self.ignore_scene_btn = QPushButton("3.背景失真")
        self.ignore_scene_btn.setToolTip(
            "3 | 背景失真。这里的图像是将人物图像中的人物区域给删除修复得到的无人场景图。如果该图像有异常纹理等不真实的情况，则点它跳过。"
        )
        self.ignore_scene_btn.clicked.connect(
            lambda: self.move_to_ignore_category("背景失真")
        )
        self.ignore_scene_btn.setStyleSheet(ignore_btn_style)
        skip_layout_top.addWidget(self.ignore_scene_btn)

        self.ignore_size_btn = QPushButton("4.比例失调")
        self.ignore_size_btn.setToolTip(
            "4 | 比例失调。如果人物占画面的比例非常小或大，无法确定姿态，则点它跳过。"
        )
        self.ignore_size_btn.clicked.connect(
            lambda: self.move_to_ignore_category("比例失调")
        )
        self.ignore_size_btn.setStyleSheet(ignore_btn_style)
        skip_layout_bottom.addWidget(self.ignore_size_btn)

        self.ignore_blur_btn = QPushButton("5.图像模糊")
        self.ignore_blur_btn.setToolTip(
            "5 | 图像模糊。如果图像分辨率很低，或图像质量不佳，则可点它跳过。"
        )
        self.ignore_blur_btn.clicked.connect(
            lambda: self.move_to_ignore_category("图像模糊")
        )
        self.ignore_blur_btn.setStyleSheet(ignore_btn_style)
        skip_layout_bottom.addWidget(self.ignore_blur_btn)
        self.skip_buttons = [
            self.ignore_aesthetic_btn,
            self.ignore_incomplete_btn,
            self.ignore_scene_btn,
            self.ignore_size_btn,
            self.ignore_blur_btn,
        ]

        layout.addWidget(skip_group)

        # 安装延迟工具提示过滤器
        self.tooltip_filter = DelayedTooltipFilter(self)
        for btn in [
            self.ignore_aesthetic_btn,
            self.ignore_incomplete_btn,
            self.ignore_scene_btn,
            self.ignore_size_btn,
            self.ignore_blur_btn,
        ]:
            btn.installEventFilter(self.tooltip_filter)

        # --- 评分系统（支持 N/A 未评分状态，按钮更大） ---
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
            lambda btn: self._on_exclusive_score_click(
                self.novelty_btn_group, "novelty", btn
            )
        )

        for i in range(6):
            btn = QPushButton(str(i))
            btn.setCheckable(True)
            btn.setFixedSize(score_btn_size, score_btn_size)
            btn.setStyleSheet("""
                QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; font-size: 13px; font-weight: bold; }
                QPushButton:checked { background-color: #28a745; color: white; border: 2px solid #1e7e34; }
            """)
            self.novelty_btn_group.addButton(btn, i)
            detail_layout.addWidget(btn, 0, i + 1)
            self.novelty_buttons[i] = btn

        # 环境互动性
        detail_layout.addWidget(QLabel("环境互动性:"), 1, 0)
        self.env_buttons = {}
        self.env_btn_group = QButtonGroup(self)
        self.env_btn_group.setExclusive(False)
        self.env_btn_group.buttonClicked.connect(
            lambda btn: self._on_exclusive_score_click(
                self.env_btn_group, "environment_interaction", btn
            )
        )

        for i in range(6):
            btn = QPushButton(str(i))
            btn.setCheckable(True)
            btn.setFixedSize(score_btn_size, score_btn_size)
            btn.setStyleSheet("""
                QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; font-size: 13px; font-weight: bold; }
                QPushButton:checked { background-color: #17a2b8; color: white; border: 2px solid #117a8b; }
            """)
            self.env_btn_group.addButton(btn, i)
            detail_layout.addWidget(btn, 1, i + 1)
            self.env_buttons[i] = btn

        # 人物契合度
        detail_layout.addWidget(QLabel("人物契合度:"), 2, 0)
        self.person_buttons = {}
        self.person_btn_group = QButtonGroup(self)
        self.person_btn_group.setExclusive(False)
        self.person_btn_group.buttonClicked.connect(
            lambda btn: self._on_exclusive_score_click(
                self.person_btn_group, "person_fit", btn
            )
        )

        for i in range(6):
            btn = QPushButton(str(i))
            btn.setCheckable(True)
            btn.setFixedSize(score_btn_size, score_btn_size)
            btn.setStyleSheet("""
                QPushButton { background-color: #f0f0f0; border: 1px solid #ccc; font-size: 13px; font-weight: bold; }
                QPushButton:checked { background-color: #ffc107; color: black; border: 2px solid #d39e00; }
            """)
            self.person_btn_group.addButton(btn, i)
            detail_layout.addWidget(btn, 2, i + 1)
            self.person_buttons[i] = btn

        score_layout.addLayout(detail_layout)
        layout.addWidget(score_group)

        self.score_buttons = {
            "novelty": self.novelty_buttons,
            "environment_interaction": self.env_buttons,
            "person_fit": self.person_buttons,
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

    def _on_exclusive_score_click(
        self,
        btn_group: QButtonGroup,
        score_type: str,
        clicked_btn: QPushButton,
    ):
        """手动实现互斥选中（允许全不选表示未评分）。"""
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

    def _get_annotation_path(self, image_path: Path) -> Path:
        """解析标注路径，并兼容旧目录结构。"""
        if self.json_dir and self.origin_dir and self.json_dir != self.origin_dir:
            json_path = self.json_dir / f"{image_path.stem}.json"
            old_json_path = image_path.with_suffix(".json")
            # 新路径不存在时，回退读取旧结构中与图片同目录的标注文件。
            if not json_path.exists() and old_json_path.exists():
                return old_json_path
            return json_path
        return image_path.with_suffix(".json")

    def _collect_json_candidates(self, image_path: Path) -> list[Path]:
        """收集可能存在的标注文件路径，并按路径去重。"""
        candidates: list[Path] = []
        if self.current_annotation_path:
            candidates.append(Path(self.current_annotation_path))
        if self.json_dir and self.origin_dir and self.json_dir != self.origin_dir:
            candidates.append(self.json_dir / f"{image_path.stem}.json")
        candidates.append(image_path.with_suffix(".json"))

        deduped: list[Path] = []
        seen = set()
        for path in candidates:
            # 已存在文件用真实路径去重；不存在文件用字符串路径去重。
            key = str(path.resolve()) if path.exists() else str(path)
            if key not in seen:
                deduped.append(path)
                seen.add(key)
        return deduped

    def _reset_after_image_list_empty(self, show_finished_message: bool = False):
        """当图片列表为空时统一重置界面状态，避免分支重复。"""
        self.canvas.image = None
        self.canvas.pose_data = PoseData()
        self.canvas.selected_keypoint = None
        self.canvas.update()
        self.current_image_path = None
        self.current_annotation_path = None
        self._update_inpainting_preview()
        self.update_keypoint_list()
        self.update_skip_buttons()
        self.update_status()
        if show_finished_message:
            QMessageBox.information(self, "提示", "所有图片处理完毕")

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

        # 如果图片子目录不存在，检查根目录是否直接有图片（兼容旧结构）
        if not origin.exists():
            # 看看根目录自身有没有图片
            has_images_at_root = any(
                f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
                for f in root.iterdir()
            )
            if has_images_at_root:
                # 旧结构：用户选的根目录本身就是图片目录
                # 提示用户是否自动迁移
                reply = QMessageBox.question(
                    self,
                    "检测到旧文件结构",
                    f"选择的文件夹中直接包含图片。\n\n"
                    f"是否自动迁移为新的项目结构？\n"
                    f"  图片 → {DIR_ORIGIN}/\n"
                    f"  JSON → {DIR_JSON}/\n\n"
                    f"选「否」将直接以旧模式打开（图片和JSON在同一目录）。",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    self._migrate_to_project_structure(root)
                else:
                    # 旧模式兼容：不使用子目录
                    self.project_root = root
                    self.origin_dir = root
                    self.json_dir = root
                    self.inpaint_dir = (
                        root / DIR_INPAINT
                    )  # 即使旧模式也尝试读 inpainting
                    self._load_project()
                    return
            else:
                # 没有图片，创建子目录结构
                origin.mkdir(parents=True, exist_ok=True)
                QMessageBox.information(
                    self,
                    "已创建项目结构",
                    f"已创建 {DIR_ORIGIN}/ 子目录。\n请将原图放入 {origin} 后重新打开。",
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

        moved_count = 0
        for f in root.iterdir():
            if f.is_file():
                if f.suffix.lower() in IMAGE_EXTENSIONS:
                    shutil.move(str(f), str(origin / f.name))
                    moved_count += 1
                elif f.suffix.lower() == ".json" and f.name != META_FILE:
                    shutil.move(str(f), str(json_dir / f.name))

        self.project_root = root
        self.origin_dir = origin
        self.json_dir = json_dir
        self.inpaint_dir = inpaint

        QMessageBox.information(
            self, "迁移完成", f"已迁移 {moved_count} 个图片文件到 {DIR_ORIGIN}/"
        )
        self._load_project()

    def _load_project(self):
        """加载项目：扫描图片、更新 meta.json 并刷新界面。"""
        # 更新 meta.json
        self._update_meta()

        # 读取上次处理到的图片
        meta = self._read_meta()
        last_image = meta.get("last_image", "")

        # 扫描图片
        self.load_images_from_folder(str(self.origin_dir), autoload=False)

        # 更新项目路径显示
        if self.project_root:
            self.project_path_label.setText(f"📁 {self.project_root}")
            self.setWindowTitle(
                f"姿态标注修正工具 v{APP_VERSION} — {self.project_root.name}"
            )

        if not self.image_files:
            return

        self.current_index = 0
        # 恢复到上次处理的位置（避免重复加载）
        if last_image:
            for i, f in enumerate(self.image_files):
                if f.name == last_image:
                    self.current_index = i
                    break
        self.load_current_image()

    def _update_meta(self):
        """更新 meta.json（记录打开时间等协作信息）。"""
        if not self.project_root:
            return

        meta = self._read_meta()

        username = getpass.getuser()
        now = datetime.now().isoformat(timespec="seconds")

        meta["last_opened"] = now
        meta["last_opened_by"] = username

        # 维护打开历史
        history = meta.get("open_history", [])
        history.append({"time": now, "user": username})
        # 只保留最近50条
        meta["open_history"] = history[-50:]

        # 统计图片数量
        if self.origin_dir and self.origin_dir.exists():
            count = sum(
                1
                for f in self.origin_dir.iterdir()
                if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
            )
            meta["total_images"] = count

        self._write_meta(meta)

    def _read_meta(self) -> dict:
        """读取 meta.json。"""
        if not self.project_root:
            return {}
        meta_path = self.project_root / META_FILE
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _write_meta(self, meta: dict):
        """写入 meta.json。"""
        if not self.project_root:
            return
        meta_path = self.project_root / META_FILE
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: failed to write meta.json: {e}")

    def _save_last_image_to_meta(self):
        """将当前处理的图片文件名记录到 meta.json。"""
        if not self.project_root or not self.current_image_path:
            return
        meta = self._read_meta()
        meta["last_image"] = Path(self.current_image_path).name
        self._write_meta(meta)

    def _find_inpainting_image(self, image_name_stem: str) -> Optional[Path]:
        """在 inpainting 目录中查找同名参考图（允许不同后缀）。"""
        if not self.inpaint_dir or not self.inpaint_dir.exists():
            return None

        for candidate in self.inpaint_dir.iterdir():
            if (
                candidate.is_file()
                and candidate.stem == image_name_stem
                and candidate.suffix.lower() in INPAINT_EXTENSIONS
            ):
                return candidate
        return None

    def _update_inpainting_preview(self):
        """更新右下角的 inpainting 参考图预览。"""
        if not self.current_image_path:
            self.inpaint_label.setPixmap(QPixmap())
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
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self.inpaint_label.setPixmap(scaled)
                self.inpaint_filename_label.setText(f"📎 {inpaint_path.name}")
            else:
                self.inpaint_label.setPixmap(QPixmap())
                self.inpaint_label.setText("(加载失败)")
                self.inpaint_filename_label.setText(str(inpaint_path.name))
        else:
            self.inpaint_label.setText("无对应 inpainting 图")
            self.inpaint_label.setPixmap(QPixmap())  # 清除之前的图
            self.inpaint_filename_label.setText("")

    # ============================================================
    # Ignore 相关
    # ============================================================

    def _move_corrupt_to_ignore(self):
        """将当前损坏图片移入 Ignore/图片损坏，在JSON中标记损坏原因并加载下一张。"""
        if not self.current_image_path:
            return
        image_path = Path(self.current_image_path)

        # 确定 Ignore 目标路径
        base_dir = self.project_root if self.project_root else image_path.parent
        ignore_dir = base_dir / "ignore" / "图片损坏"
        ignore_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 在JSON中标记图片损坏原因
            json_path = self._get_annotation_path(image_path)
            self.canvas.pose_data.skip_reason = "图片损坏"
            
            # 保存标注（确保损坏原因落盘）- 保留在原位置
            data = [self.canvas.pose_data.to_dict()]
            json_path.parent.mkdir(parents=True, exist_ok=True)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # 只移动图片，不移动JSON标注文件
            shutil.move(str(image_path), str(ignore_dir / image_path.name))

            print(f"Moved corrupt image {image_path.name} to ignore/图片损坏/ (JSON kept at original location with damage reason)")

        except Exception as e:
            print(f"Warning: failed to move corrupt image: {e}")
            QMessageBox.critical(self, "错误", f"移动损坏图片失败: {e}")
            return

        # 从列表中移除
        del self.image_files[self.current_index]

        if not self.image_files:
            self._reset_after_image_list_empty()
            return

        if self.current_index >= len(self.image_files):
            self.current_index = len(self.image_files) - 1

        self.load_current_image()

    def move_to_ignore_category(self, category: str, custom_reason: str = ""):
        """将当前图片移动到 Ignore/<category> 文件夹，但保留JSON标注文件在原位置。"""
        if not self.current_image_path:
            return

        image_path = Path(self.current_image_path)

        # 标注路径：优先使用当前加载路径，避免写到错误位置
        json_path = self._get_annotation_path(image_path)

        # 创建 Ignore/<category> 文件夹（位于原图目录旁）
        folder_name = category
        base_dir = self.project_root if self.project_root else image_path.parent
        ignore_dir = base_dir / "ignore" / folder_name
        ignore_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 先把跳过原因写入标注数据
            reason_text = custom_reason if custom_reason else category
            self.canvas.pose_data.skip_reason = reason_text

            # 保存标注（确保理由落盘）- 保留在原位置
            data = [self.canvas.pose_data.to_dict()]
            # 确保标注目录存在
            json_path.parent.mkdir(parents=True, exist_ok=True)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # 只移动图片，不移动JSON标注文件
            shutil.move(str(image_path), str(ignore_dir / image_path.name))

            print(f"Moved {image_path.name} to ignore/{folder_name}/ (JSON kept at original location)")

            # 从列表中移除
            del self.image_files[self.current_index]

            if not self.image_files:
                self._reset_after_image_list_empty(show_finished_message=True)
                return

            if self.current_index >= len(self.image_files):
                self.current_index = len(self.image_files) - 1

            self.load_current_image()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"移动文件失败: {e}")

    def move_to_ignore(self):
        """按删除键后弹出类别选择对话框。"""
        if not self.current_image_path:
            return
        items = [*IGNORE_CATEGORIES, "其他原因"]
        item, ok = QInputDialog.getItem(
            self, "选择ignore类别", "请选择跳过原因:", items, 0, False
        )
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
        has_skip_reason = bool(self.canvas.pose_data.skip_reason)
        for btn in self.skip_buttons:
            btn.setEnabled(not has_skip_reason)

    # ============================================================
    # 评分验证 & 导航
    # ============================================================

    def has_complete_scores(self) -> bool:
        pose = self.canvas.pose_data
        return (
            pose.novelty >= 0
            and pose.environment_interaction >= 0
            and pose.person_fit >= 0
        )

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
            QMessageBox.warning(
                self,
                "评分不完整",
                f"以下评分仍为 N/A，请先打分或移至 Ignore：\n\n• {'、'.join(missing)}",
            )
            return False
        return True

    def update_status(self):
        if self.current_image_path:
            filename = Path(self.current_image_path).name
            status = (
                f"图片: {filename} ({self.current_index + 1}/{len(self.image_files)})"
            )
        else:
            status = "未加载图片"

        if self.canvas.pose_data.skip_reason:
            status += f" | [已跳过: {self.canvas.pose_data.skip_reason}]"

        if self.canvas.selected_keypoint:
            kp = self.canvas.selected_keypoint
            vis_map = {0: "遮挡", 1: "可见"}
            status += f" | 选中: {kp.name} ({vis_map[kp.visibility]})"

        self.status_bar.showMessage(status)

    def load_images_from_folder(self, folder: str, autoload: bool = True):
        folder_path = Path(folder)
        self.image_files = [
            path
            for path in folder_path.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]

        self.image_files.sort()
        if self.image_files:
            self.current_index = 0
            if autoload:
                self.load_current_image()
        else:
            QMessageBox.information(self, "提示", f"{folder_path} 下没有图片")

    def load_current_image(self):
        if not self.image_files:
            return
        self.current_image_path = str(self.image_files[self.current_index])

        image = QImage(self.current_image_path)
        if image.isNull():
            # 加载失败：自动移入 Ignore/图片损坏
            failed_name = Path(self.current_image_path).name
            self._move_corrupt_to_ignore()
            self.status_bar.showMessage(f"⚠ 图片损坏已移除: {failed_name}", 3000)
            # 内部会调整索引并递归加载下一张
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
        if not self.current_image_path:
            return

        image_path = Path(self.current_image_path)

        json_path = self._get_annotation_path(image_path)

        pose_data = PoseData()

        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
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

        # 更新评分界面
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

    def _set_score_group_value(
        self,
        btn_group: QButtonGroup,
        buttons: dict[int, QPushButton],
        value: int,
    ):
        for btn in btn_group.buttons():
            btn.setChecked(False)
        if value >= 0 and value in buttons:
            buttons[value].setChecked(True)

    def update_score_ui(self, pose_data: PoseData):
        self._set_score_group_value(
            self.novelty_btn_group,
            self.novelty_buttons,
            pose_data.novelty,
        )
        self._set_score_group_value(
            self.env_btn_group,
            self.env_buttons,
            pose_data.environment_interaction,
        )
        self._set_score_group_value(
            self.person_btn_group,
            self.person_buttons,
            pose_data.person_fit,
        )

    def save_current(self):
        if not self.current_annotation_path:
            return
        try:
            # 确保目录存在
            ann_path = Path(self.current_annotation_path)
            ann_path.parent.mkdir(parents=True, exist_ok=True)

            data = [self.canvas.pose_data.to_dict()]
            with open(self.current_annotation_path, "w", encoding="utf-8") as f:
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
        self.skeleton_btn.setText(
            "骨架 (H)" if self.canvas.show_skeleton else "骨架OFF"
        )
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
        """使用 QShortcut 注册全局快捷键，避免焦点切换导致快捷键失效。"""
        QShortcut(QKeySequence(Qt.Key_Left), self, self.prev_image)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.next_image)
        QShortcut(QKeySequence(Qt.Key_O), self, self.next_processable_image)
        QShortcut(QKeySequence(Qt.Key_Tab), self, lambda: self.switch_keypoint(1))
        QShortcut(
            QKeySequence(Qt.ShiftModifier | Qt.Key_Tab),
            self,
            lambda: self.switch_keypoint(-1),
        )
        QShortcut(QKeySequence(Qt.Key_H), self, self.toggle_skeleton)
        QShortcut(QKeySequence(Qt.Key_Delete), self, self.move_to_ignore)
        QShortcut(QKeySequence(Qt.Key_W), self, self.focus_on_pose)
        QShortcut(QKeySequence(Qt.Key_E), self, self.fit_to_window)
        # 数字快捷键 1..5 对应预设丢弃理由。
        for idx, category in enumerate(IGNORE_CATEGORIES, start=1):
            key = getattr(Qt, f"Key_{idx}")
            QShortcut(
                QKeySequence(key),
                self,
                lambda reason=category: self.move_to_ignore_category(reason),
            )
        # S/D/Space 用于切换可见性，需要转发给画布控件
        QShortcut(
            QKeySequence(Qt.Key_S),
            self,
            lambda: self._apply_visibility_shortcut(Qt.Key_S),
        )
        QShortcut(
            QKeySequence(Qt.Key_D),
            self,
            lambda: self._apply_visibility_shortcut(Qt.Key_D),
        )
        QShortcut(
            QKeySequence(Qt.Key_Space),
            self,
            lambda: self._apply_visibility_shortcut(Qt.Key_Space),
        )

    def _apply_visibility_shortcut(self, key: int):
        self.canvas.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
        self.update_keypoint_list()
        self.update_status()

    def switch_keypoint(self, direction: int):
        if not self.canvas.pose_data.keypoints:
            return
        current_idx = -1
        if self.canvas.selected_keypoint:
            try:
                current_idx = self.canvas.pose_data.keypoints.index(
                    self.canvas.selected_keypoint
                )
            except ValueError:
                pass
        new_idx = (current_idx + direction) % len(self.canvas.pose_data.keypoints)
        self.canvas.selected_keypoint = self.canvas.pose_data.keypoints[new_idx]
        self.canvas.update()
        self.on_keypoint_selected(self.canvas.selected_keypoint.name)
