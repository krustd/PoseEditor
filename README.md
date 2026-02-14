# PoseEditor - 姿态标注修正工具

[![Build Status](https://github.com/krustd/PoseEditor/workflows/Build%20and%20Release/badge.svg)](https://github.com/krustd/PoseEditor/actions)
[![Release](https://img.shields.io/github/release/krustd/PoseEditor.svg)](https://github.com/krustd/PoseEditor/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## 🚀 即开即用 - 无需Python环境！

**直接下载可执行文件即可运行：** [📥 下载页面](https://github.com/krustd/PoseEditor/releases)

一个基于PySide6开发的人体姿态标注修正工具，专为计算机视觉和机器学习项目设计。支持COCO格式的姿态数据标注、修正和评分，提供直观的图形界面和高效的工作流程。

## 🌟 主要功能

### 📝 姿态标注与修正
- **17个关键点标注**：支持COCO风格的人体关键点标注
- **可视化编辑**：直观的拖拽操作调整关键点位置
- **骨架显示**：彩色骨架连接线，清晰展示人体结构
- **可见性标记**：支持标记关键点的可见/遮挡状态

### 🎯 智能评分系统
- **多维度评分**：
  - 姿势新奇度 (0-5分)
  - 环境互动性 (0-5分)
  - 人物契合度 (0-5分)
- **批量处理**：快速跳转到下一个未评分图片

### 🗂️ 项目管理
- **结构化项目**：自动创建标准项目目录结构
- **协作支持**：记录打开历史和处理进度
- **Ignore分类**：支持按原因分类跳过不合适的图片

### 🖼️ Inpainting支持
- **参考图预览**：自动加载并显示对应的inpainting参考图
- **工作区整合**：无缝集成inpainting工作流程

## 🚀 快速开始

### 环境要求
- Python 3.9
- PySide6 6.10.1+
- 支持操作系统：Windows、macOS、Linux

### 安装方法

#### 🚀 推荐方法：直接下载可执行文件
**无需安装Python环境，直接运行！**

从 [Releases页面](https://github.com/krustd/PoseEditor/releases) 下载适合您系统的可执行文件：
- Windows: `PoseEditor-windows.exe`
- macOS: `PoseEditor-macos.zip`
- Linux: `PoseEditor-linux.tar.gz`

下载后直接运行即可开始使用，这是最简单快捷的方式！

#### 方法2：从源码安装
如果您需要修改源码或开发，可以从源码安装：
```bash
# 克隆仓库
git clone https://github.com/krustd/PoseEditor.git
cd PoseEditor

# 安装依赖
pip install -r requirements.txt

# 运行程序
python main.py
```

#### 方法3：使用pip安装
```bash
pip install poseeditor
```

## 📖 使用指南

### 项目结构
打开或创建项目后，工具会自动创建以下目录结构：
```
your_project/
├── images/          # 原始图片
├── annotations/     # 标注JSON文件
├── inpainting/      # Inpainting参考图
├── ignore/          # 跳过的图片（按原因分类）
│   ├── 美感不足/
│   ├── 难以补全/
│   ├── 背景失真/
│   ├── 比例失调/
│   └── 图像模糊/
└── meta.json        # 项目元数据
```

### 基本操作

#### 鼠标操作
- **左键**：选择/拖拽关键点
- **Ctrl+左键**：瞬移关键点到指定位置
- **右键**：平移画布
- **滚轮**：缩放视图

#### 键盘快捷键
- **←/→**：上一张/下一张图片
- **Tab/Shift+Tab**：切换关键点选择
- **A/S**：标记关键点为遮挡/可见
- **W/E**：聚焦关键点/适应全图
- **H**：显示/隐藏骨架
- **O**：跳到下一个需要处理的图片
- **Delete**：选择跳过当前图片
- **1~5**：快速跳过（对应不同原因）
- **Ctrl+Z/Y**：撤销/重做操作

### 工作流程

1. **打开项目**：选择项目根目录或创建新项目
2. **加载图片**：自动扫描images目录中的图片
3. **调整姿态**：拖拽关键点到正确位置
4. **设置可见性**：使用A/S键标记遮挡点
5. **评分**：为姿态打分（新奇度、互动性、契合度）
6. **处理特殊情况**：使用Ignore功能跳过不合适的图片
7. **保存**：自动保存标注数据到annotations目录

## 📊 数据格式

### COCO风格JSON格式
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

## 🔧 高级功能

### Ignore分类系统
支持按以下原因分类跳过图片：
- **美感不足**：非艺术性人物照片
- **难以补全**：人物关键部分缺失
- **背景失真**：inpainting结果异常
- **比例失调**：人物比例不协调
- **图像模糊**：分辨率低或质量差

### 协作功能
- 记录每个用户的操作历史
- 保存上次处理位置
- 支持多人协作标注

### 批量处理
- 快速跳转到未完成图片
- 批量导出标注结果
- 支持项目迁移和结构转换

## 🤝 贡献指南

欢迎提交Issue和Pull Request！

### 开发环境设置
```bash
# 克隆仓库
git clone https://github.com/krustd/PoseEditor.git
cd PoseEditor

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装开发依赖
pip install -r requirements.txt
```

### 构建可执行文件
```bash
# 安装PyInstaller
pip install pyinstaller

# 构建可执行文件
pyinstaller main.py --name=PoseEditor --onefile --windowed --clean --collect-all pyside6
```

## 📝 更新日志

### v2.1.0
- 新增多维度评分系统
- 改进Ignore分类功能
- 优化用户界面和交互体验
- 增强inpainting工作流支持

### v2.0.0
- 重构为项目结构管理
- 添加协作功能支持
- 优化性能和稳定性

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🙏 致谢

- [PySide6](https://www.riverbankcomputing.com/software/pyqt/) - Qt for Python
- [COCO Dataset](https://cocodataset.org/) - 姿态标注格式参考

## 📞 联系方式

- 项目主页：https://github.com/krustd/PoseEditor
- 问题反馈：https://github.com/krustd/PoseEditor/issues
- 邮箱：[krust@foxmail.com]

---

如果这个项目对您有帮助，请给我们一个⭐️！