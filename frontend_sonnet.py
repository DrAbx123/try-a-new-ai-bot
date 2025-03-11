import sys
import os
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QTextEdit, QLineEdit, QPushButton, QLabel, QSplitter)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from ai_manager_sonnet import AIManagerSonnet

# 调试日志函数
def log(prefix, message):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [{prefix}] {message}")

# 主窗口
class SonnetChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        log("SonnetChatWindow", "初始化主窗口")
        self.setWindowTitle("Claude Sonnet Chat & Image Generator")
        self.setMinimumSize(800, 600)

        log("SonnetChatWindow", "创建AIManager实例")
        self.ai_manager = AIManagerSonnet(self)  # 设置父对象为主窗口
        log("SonnetChatWindow", "连接AIManager信号")
        self.ai_manager.text_chunk_ready.connect(self.update_chat_text)
        self.ai_manager.image_ready.connect(self.update_image)
        self.ai_manager.thinking_changed.connect(self.set_thinking_status)
        self.ai_manager.prompt_extracted.connect(self.update_prompt_label)
        self.ai_manager.error_occurred.connect(self.handle_error)

        log("SonnetChatWindow", "设置UI组件")
        self.setup_ui()
        log("SonnetChatWindow", "主窗口初始化完成")

    def closeEvent(self, event):
        """窗口关闭时的处理"""
        log("SonnetChatWindow", "窗口正在关闭")
        try:
            if hasattr(self, 'ai_manager'):
                self.ai_manager.cleanup()
        except Exception as e:
            log("SonnetChatWindow", f"清理时出错: {str(e)}")
        super().closeEvent(event)

    def handle_error(self, error_message):
        """处理错误消息"""
        log("SonnetChatWindow", f"收到错误: {error_message}")
        self.status_label.setText(f"错误: {error_message}")

    def setup_ui(self):
        log("SonnetChatWindow", "开始设置UI")
        # 创建主窗口布局
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)

        # 创建左侧聊天部分
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)

        # 聊天显示区域
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        chat_layout.addWidget(self.chat_display)

        # 输入区域
        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入您的消息...")
        self.input_field.returnPressed.connect(self.send_message)
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self.send_message)

        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_button)
        chat_layout.addLayout(input_layout)

        # 创建右侧图像显示部分
        image_widget = QWidget()
        image_layout = QVBoxLayout(image_widget)

        image_label_header = QLabel("生成的图像")
        image_layout.addWidget(image_label_header)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(400, 400)
        self.image_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ddd;")
        image_layout.addWidget(self.image_label)

        self.image_prompt_label = QLabel("等待图像生成...")
        self.image_prompt_label.setWordWrap(True)
        image_layout.addWidget(self.image_prompt_label)

        # 状态指示器
        self.status_label = QLabel("准备就绪")
        chat_layout.addWidget(self.status_label)

        # 使用分割器整合左右两侧
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(chat_widget)
        splitter.addWidget(image_widget)
        splitter.setSizes([400, 400])

        main_layout.addWidget(splitter)
        self.setCentralWidget(main_widget)

        # 初始欢迎消息
        log("SonnetChatWindow", "添加欢迎消息")
        self.chat_display.append("欢迎使用Claude Sonnet聊天与图像生成器！\n请发送消息开始对话。")
        log("SonnetChatWindow", "UI设置完成")


    def send_message(self):
        user_input = self.input_field.text().strip()
        log("SonnetChatWindow", f"发送消息函数调用，用户输入: '{user_input}'")

        if not user_input:
            log("SonnetChatWindow", "用户输入为空，忽略请求")
            return

        self.input_field.clear()
        log("SonnetChatWindow", "更新聊天显示 - 添加用户消息")
        self.chat_display.append(f"\n你: {user_input}\n")
        self.chat_display.append("Claude: ")

        # 禁用输入区域直到回复完成
        log("SonnetChatWindow", "禁用输入区域")
        self.input_field.setEnabled(False)
        self.send_button.setEnabled(False)

        log("SonnetChatWindow", "调用AIManager处理对话")
        self.ai_manager.process_conversation(user_input)

    def update_chat_text(self, text: str):
        self.chat_display.insertPlainText(text)
        # 自动滚动到底部
        self.chat_display.verticalScrollBar().setValue(
            self.chat_display.verticalScrollBar().maximum()
        )

    def update_image(self, image: list):
        image = image[0]
        log("SonnetChatWindow", f"更新图像，尺寸: {image.width()}x{image.height()}")
        pixmap = QPixmap.fromImage(image)

        # 确保图像标签已经有几何信息
        if self.image_label.width() > 0 and self.image_label.height() > 0:
            scaled_pixmap = pixmap.scaled(
                self.image_label.width(),
                self.image_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        else:
            # 如果标签尚未调整大小，使用原始大小
            scaled_pixmap = pixmap

        self.image_label.setPixmap(scaled_pixmap)
        self.status_label.setText("图像生成完成")
        log("SonnetChatWindow", "图像更新完成")

    def update_prompt_label(self, prompt: str):
        log("SonnetChatWindow", f"更新图像提示词标签: '{prompt}'")
        self.image_prompt_label.setText(f"提示词: {prompt}")

    def set_thinking_status(self, is_thinking: bool):
        log("SonnetChatWindow", f"设置思考状态: {is_thinking}")
        if is_thinking:
            self.status_label.setText("Claude Sonnet正在思考...")
        else:
            self.status_label.setText("回复完成")
            self.input_field.setEnabled(True)
            self.send_button.setEnabled(True)
        log("SonnetChatWindow", "思考状态更新完成")


# 应用程序入口
def main():
    log("Main", "应用程序启动")
    app = QApplication(sys.argv)
    log("Main", "创建主窗口")
    window = SonnetChatWindow()
    log("Main", "显示主窗口")
    window.show()
    log("Main", "进入应用程序主循环")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
