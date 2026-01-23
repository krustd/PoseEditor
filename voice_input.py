import os
import sys
import wave
import time
import tempfile
import threading
import whisper
import pyaudio
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QTextEdit, QLabel, QMessageBox, QProgressBar
)
from PySide6.QtCore import Qt, Signal, QThread, QObject

class TranscribeWorker(QObject):
    """后台运行语音识别的 Worker，防止界面卡死"""
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, audio_path, model_size="small"):
        super().__init__()
        self.audio_path = audio_path
        self.model_size = model_size

    def run(self):
        global _LOADED_WHISPER_MODEL, _LOADED_MODEL_NAME
        try:
            # 只有当模型未加载，或者需要切换不同大小的模型时才重新加载
            if _LOADED_WHISPER_MODEL is None or _LOADED_MODEL_NAME != self.model_size:
                print(f"Loading Whisper model: {self.model_size}...") # 方便调试
                _LOADED_WHISPER_MODEL = whisper.load_model(self.model_size)
                _LOADED_MODEL_NAME = self.model_size
            
            # 使用全局缓存的模型
            result = _LOADED_WHISPER_MODEL.transcribe(self.audio_path, language="zh")
            text = result["text"].strip()
            self.finished.emit(text)
        except Exception as e:
            self.error.emit(str(e))

class VoiceInputWidget(QWidget):
    """
    组合组件：包含一个文本输入框和一个录音按钮
    """
    text_changed = Signal(str) # 当文本改变时发出信号

    def __init__(self, label_text="", placeholder="", parent=None,model_name="base"):
        super().__init__(parent)
        self.model_name = model_name
        self.is_recording = False
        self.frames = []
        self.p = None
        self.stream = None
        self.record_thread = None
        
        # 布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 标题行
        header_layout = QHBoxLayout()
        self.label = QLabel(label_text)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")
        
        header_layout.addWidget(self.label)
        header_layout.addStretch()
        header_layout.addWidget(self.status_label)
        layout.addLayout(header_layout)
        
        # 文本框
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(placeholder)
        self.text_edit.setMaximumHeight(60) # 限制高度
        self.text_edit.textChanged.connect(lambda: self.text_changed.emit(self.text_edit.toPlainText()))
        layout.addWidget(self.text_edit)
        
        # 按钮和进度条
        btn_layout = QHBoxLayout()
        self.record_btn = QPushButton("按住说话 (或点击开始/停止)")
        self.record_btn.setCheckable(True)
        self.record_btn.clicked.connect(self.toggle_recording)
        btn_layout.addWidget(self.record_btn)
        layout.addLayout(btn_layout)
        
        self.progress = QProgressBar()
        self.progress.setRange(0, 0) # Indeterminate mode
        self.progress.setFixedHeight(4)
        self.progress.hide()
        layout.addWidget(self.progress)

    def set_text(self, text):
        """外部设置文本"""
        self.text_edit.setPlainText(text)

    def get_text(self):
        """获取文本"""
        return self.text_edit.toPlainText()

    def toggle_recording(self):
        if self.record_btn.isChecked():
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        self.is_recording = True
        self.record_btn.setText("正在录音... (点击停止)")
        self.record_btn.setStyleSheet("background-color: #ffcccc; color: red;")
        self.status_label.setText("录音中...")
        self.frames = []
        
        # 开启录音线程
        self.record_thread = threading.Thread(target=self._record_audio)
        self.record_thread.start()

    def stop_recording(self):
        self.is_recording = False
        self.record_btn.setText("正在转写...")
        self.record_btn.setEnabled(False)
        self.progress.show()
        self.status_label.setText("正在加载模型并转写...")
        
        # 等待录音线程结束
        if self.record_thread:
            self.record_thread.join()
            
        # 保存临时文件
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        self.save_wave_file(self.temp_file.name)
        
        # 启动识别线程
        self.transcribe_thread = QThread()
        self.worker = TranscribeWorker(self.temp_file.name, model_size=self.model_name)
        self.worker.moveToThread(self.transcribe_thread)
        
        self.transcribe_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_transcribe_finished)
        self.worker.error.connect(self.on_transcribe_error)
        
        # 清理工作
        self.worker.finished.connect(self.transcribe_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.transcribe_thread.finished.connect(self.transcribe_thread.deleteLater)
        
        self.transcribe_thread.start()

    def _record_audio(self):
        CHUNK = 1024
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000 # Whisper 推荐 16k
        
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(format=FORMAT,
                                  channels=CHANNELS,
                                  rate=RATE,
                                  input=True,
                                  frames_per_buffer=CHUNK)
                                  
        while self.is_recording:
            data = self.stream.read(CHUNK)
            self.frames.append(data)
            
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()

    def save_wave_file(self, filename):
        wf = wave.open(filename, 'wb')
        wf.setnchannels(1)
        wf.setsampwidth(self.p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(16000)
        wf.writeframes(b''.join(self.frames))
        wf.close()

    def on_transcribe_finished(self, text):
        self.progress.hide()
        self.record_btn.setEnabled(True)
        self.record_btn.setChecked(False)
        self.record_btn.setText("按住说话 (或点击开始/停止)")
        self.record_btn.setStyleSheet("")
        
        # 追加还是覆盖？这里选择追加，方便多次说话拼接
        current_text = self.text_edit.toPlainText()
        if current_text:
            new_text = current_text + " " + text
        else:
            new_text = text
            
        self.text_edit.setPlainText(new_text)
        self.status_label.setText("转写完成")
        
        # 删除临时文件
        try:
            os.remove(self.temp_file.name)
        except:
            pass

    def on_transcribe_error(self, err_msg):
        self.progress.hide()
        self.record_btn.setEnabled(True)
        self.record_btn.setChecked(False)
        self.record_btn.setStyleSheet("")
        self.status_label.setText("错误")
        QMessageBox.warning(self, "识别错误", f"Whisper 运行失败: {err_msg}")