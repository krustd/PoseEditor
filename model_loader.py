import os
import sys
import requests
import subprocess
import whisper
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QMessageBox, QPushButton
)
from PySide6.QtCore import Qt, QThread, Signal

# --- 工具函数 ---
def get_whisper_download_root():
    """获取 Whisper 官方默认的下载路径"""
    default_cache = os.path.join(os.path.expanduser("~"), ".cache")
    xdg_cache = os.getenv("XDG_CACHE_HOME", default_cache)
    return os.path.join(xdg_cache, "whisper")

# --- 常量定义 ---
MODEL_URLS = whisper._MODELS 
DOWNLOAD_ROOT = get_whisper_download_root()

class DownloadThread(QThread):
    """
    下载线程：
    只负责下载到 .tmp，完成后重命名。
    """
    progress = Signal(int)
    finished = Signal()
    error = Signal(str)

    def __init__(self, url, save_path):
        super().__init__()
        self.url = url
        self.save_path = save_path

    def run(self):
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
            
            # 使用临时文件路径
            temp_path = self.save_path + ".tmp"
            
            # 开始下载
            response = requests.get(self.url, stream=True, timeout=15)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            self.progress.emit(percent)
            
            # 关键点：下载成功后，才覆盖/重命名为正式文件
            # 如果之前有损坏的旧文件，直接替换
            if os.path.exists(self.save_path):
                os.remove(self.save_path)
            
            os.rename(temp_path, self.save_path)
            self.finished.emit()
            
        except Exception as e:
            self.error.emit(str(e))

class ModelLoaderDialog(QDialog):
    def __init__(self, model_name="base", parent=None):
        super().__init__(parent)
        self.setWindowTitle("下载资源")
        self.setFixedSize(400, 150)
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        
        layout = QVBoxLayout(self)
        
        self.label = QLabel(f"正在下载 {model_name} 模型...")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # 下载过程中不允许取消，或者需要你自己处理清理逻辑
        # 这里简单起见，禁用取消，强制等待完成
        self.cancel_btn = QPushButton("请等待下载完成...")
        self.cancel_btn.setEnabled(False) 
        layout.addWidget(self.cancel_btn, alignment=Qt.AlignRight)
        
        # 获取配置
        self.url = MODEL_URLS.get(model_name)
        if not self.url:
            QMessageBox.critical(self, "错误", f"未找到模型 {model_name} 的下载链接")
            self.reject()
            return

        filename = os.path.basename(self.url)
        self.target_path = os.path.join(DOWNLOAD_ROOT, filename)
        
        self.download_thread = None

    def start_download(self):
        self.download_thread = DownloadThread(self.url, self.target_path)
        self.download_thread.progress.connect(self.progress_bar.setValue)
        self.download_thread.finished.connect(self.accept)
        self.download_thread.error.connect(self.on_download_error)
        self.download_thread.start()

    def on_download_error(self, msg):
        QMessageBox.critical(self, "下载失败", f"无法下载模型：\n{msg}")
        self.reject()

def check_ffmpeg_available():
    """
    检查系统是否安装了FFmpeg
    返回: bool - True表示FFmpeg可用，False表示不可用
    """
    try:
        # 尝试运行ffmpeg -version命令
        subprocess.run(["ffmpeg", "-version"],
                      stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE,
                      check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def ensure_model_ready(model_name="base"):
    """
    外部调用接口
    """
    # 0. 检查FFmpeg是否可用
    if not check_ffmpeg_available():
        QMessageBox.warning(
            None,
            "FFmpeg 未安装",
            "语音识别功能需要安装FFmpeg才能正常工作。\n\n"
            "请安装FFmpeg并确保它已添加到系统PATH环境变量中：\n"
            "• Windows: 下载FFmpeg并添加到PATH\n"
            "• macOS: brew install ffmpeg\n"
            "• Linux: sudo apt-get install ffmpeg\n\n"
            "安装后请重启程序。"
        )
        return False
    
    # 1. 快速检查：如果文件存在且大小正常(>0)，直接通过，不弹窗
    url = MODEL_URLS.get(model_name)
    if url:
        filename = os.path.basename(url)
        path = os.path.join(DOWNLOAD_ROOT, filename)
        # 只要文件存在，就信任它是通过 .tmp -> .pt 机制生成的完整文件
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return True

    # 2. 如果文件不存在，弹窗下载
    dialog = ModelLoaderDialog(model_name)
    
    # 窗口显示后立即开始下载
    from PySide6.QtCore import QTimer
    QTimer.singleShot(100, dialog.start_download)
    
    return dialog.exec() == QDialog.Accepted