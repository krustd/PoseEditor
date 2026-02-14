# PoseEditor - 姿态标注修正工具

[![Build Status](https://github.com/krustd/PoseEditor/workflows/Build%20and%20Release/badge.svg)](https://github.com/krustd/PoseEditor/actions)
[![Build Status (MCB)](https://github.com/MCB-SMART-BOY/PoseEditor/workflows/Build%20and%20Release/badge.svg)](https://github.com/MCB-SMART-BOY/PoseEditor/actions)
[![Release](https://img.shields.io/github/release/krustd/PoseEditor.svg)](https://github.com/krustd/PoseEditor/releases)
[![Release (MCB)](https://img.shields.io/github/release/MCB-SMART-BOY/PoseEditor.svg)](https://github.com/MCB-SMART-BOY/PoseEditor/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

一个基于 PySide6 的人体姿态标注修正工具，面向计算机视觉与机器学习数据清洗流程。支持 **COCO 风格 JSON** 标注读取与编辑，提供关键点拖拽、可见性切换、评分、Ignore 分类、inpainting 参考图联动等能力。

仓库说明：
- 上游原作者仓库：`https://github.com/krustd/PoseEditor`
- 当前维护分支：`https://github.com/MCB-SMART-BOY/PoseEditor`

## 🚀 快速开始

### 方式 1：直接使用可执行文件（推荐）
从 Releases 页面下载后直接运行：
- 原作者发布页：`https://github.com/krustd/PoseEditor/releases`
- 当前维护分支发布页：`https://github.com/MCB-SMART-BOY/PoseEditor/releases`
- Windows: `PoseEditor-windows.exe`
- macOS: `PoseEditor-macos.app.zip`
- Linux: `PoseEditor-linux.AppImage`

### 方式 2：从源码运行
```bash
git clone https://github.com/MCB-SMART-BOY/PoseEditor.git
cd PoseEditor
uv sync --group dev
uv run poseeditor
```

如需基于上游仓库开发：
```bash
git clone https://github.com/krustd/PoseEditor.git
cd PoseEditor
uv sync --group dev
uv run poseeditor
```

### 方式 3：安装为包
```bash
uv pip install poseeditor
```

## 🌟 核心功能

### 姿态编辑
- 17 个关键点编辑（COCO 顺序）
- 左键拖拽关键点，`Ctrl+左键` 瞬移关键点
- 骨架显示开关
- `S/D/Space` 切换关键点可见性状态
- 撤销/重做（`Ctrl+Z` / `Ctrl+Y`）

### 标注评分
- 姿势新奇度（0-5）
- 环境互动性（0-5）
- 人物契合度（0-5）
- 快速跳转下一个待处理图片（`O`）

### 项目管理
- 自动识别并创建项目目录结构
- 支持旧结构迁移到新结构
- 记录 `meta.json`（最近打开用户、时间、最后处理图片）
- Ignore 分类管理（含快捷键 `1~5`）

### Inpainting 联动
- 自动匹配 `inpainting/` 下同名参考图
- 在右侧预览区域展示参考图

## 📁 项目目录

### 数据目录（打开项目后自动使用）
```text
your_project/
├── images/          # 原始图片
├── annotations/     # 标注 JSON
├── inpainting/      # Inpainting 参考图
├── ignore/          # 已跳过图片（按原因分类）
│   ├── 美感不足/
│   ├── 难以补全/
│   ├── 背景失真/
│   ├── 比例失调/
│   └── 图像模糊/
└── meta.json        # 项目元数据
```

### 源码目录（严格 package 结构）
```text
PoseEditor/
├── pyproject.toml
├── uv.lock
├── src/
│   └── poseeditor/
│       ├── __main__.py       # 包入口
│       ├── app.py            # 应用启动
│       ├── main_window.py    # 主窗口与工作流
│       ├── models.py         # 数据模型
│       ├── undo.py           # 撤销/重做
│       ├── constants.py      # 常量定义
│       └── widgets/
│           ├── canvas.py     # 画布绘制与交互
│           └── tooltip.py    # 延迟提示
└── tests/
    └── test_models_and_undo.py
```

## ⌨️ 操作说明

### 鼠标
- 左键：选中/拖拽关键点
- `Ctrl+左键`：将当前选中关键点瞬移到点击位置
- 右键：平移画布
- 滚轮：缩放

### 快捷键
- `← / →`：上一张 / 下一张
- `Tab / Shift+Tab`：切换关键点
- `S / D / Space`：遮挡 / 可见 / 切换
- `W / E`：聚焦姿态 / 适应全图
- `H`：骨架显示开关
- `O`：跳到下一个待处理图片
- `Delete`：弹出 Ignore 类别选择
- `1~5`：按预设 Ignore 原因快速跳过
- `Ctrl+Z / Ctrl+Y`：撤销 / 重做

## 📊 标注数据格式

### COCO 风格 JSON
```json
[
  {
    "id": 0,
    "keypoints": [[x1, y1], [x2, y2], ...],
    "scores": [0.95, 0.87, ...],
    "visibility": [1, 0, 1, ...],
    "novelty": 3,
    "environment_interaction": 2,
    "person_fit": 4,
    "skip_reason": ""
  }
]
```

### 关键点顺序
1. nose
2. left_eye
3. right_eye
4. left_ear
5. right_ear
6. left_shoulder
7. right_shoulder
8. left_elbow
9. right_elbow
10. left_wrist
11. right_wrist
12. left_hip
13. right_hip
14. left_knee
15. right_knee
16. left_ankle
17. right_ankle

## 🛠️ 开发与发布

### 开发环境
```bash
uv sync --group dev
```

### 质量检查
```bash
uvx ruff check src tests
uv run pytest -q
uv run python -m compileall src/poseeditor tests
```

### 构建 Python 包
```bash
uv build
```

### 构建可执行文件
```bash
uv run pyinstaller src/poseeditor/__main__.py \
  --name=PoseEditor \
  --onefile \
  --windowed \
  --clean \
  --collect-all pyside6
```

### GitHub Actions 跨平台构建与发布
- 触发方式：
  - 推送标签：`v*`（例如 `v4.0.0`）
  - 手动触发：`workflow_dispatch` + `release_tag`
- 发布产物：
  - Windows：`PoseEditor-windows.exe`
  - macOS：`PoseEditor-macos.app.zip`
  - Linux：`PoseEditor-linux.AppImage`

### 锁文件一致性
```bash
uv lock --check
uv sync --locked --group dev
```

## 🤝 贡献

欢迎提交 Issue 与 Pull Request。

## 📄 许可证

本项目采用 MIT 许可证。

## 🔗 链接

- 上游项目主页：https://github.com/krustd/PoseEditor
- 上游问题反馈：https://github.com/krustd/PoseEditor/issues
- 当前维护分支主页：https://github.com/MCB-SMART-BOY/PoseEditor
- 当前维护分支问题反馈：https://github.com/MCB-SMART-BOY/PoseEditor/issues
