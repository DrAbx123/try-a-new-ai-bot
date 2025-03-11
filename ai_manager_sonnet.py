import asyncio
import time
import torch
import os
from datetime import datetime
from PyQt6.QtCore import QObject, pyqtSignal as Signal, QThreadPool
from PyQt6.QtGui import QImage
import psutil

# 注释掉Stable Diffusion引用
# from stable_diffusion import StableDiffusion
from sonnet import Sonnet


def log(prefix, message):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [{prefix}] {message}")


class AIManagerSonnet(QObject):
    text_chunk_ready = Signal(str)  # 发送文本片段到UI
    image_ready = Signal(list)  # 发送生成的图像到UI
    thinking_changed = Signal(bool)  # 指示AI是否在思考
    prompt_extracted = Signal(str)  # 当提取到图像提示词时发射信号
    error_occurred = Signal(str)  # 错误信号

    def __init__(self, parent=None):
        super().__init__(parent)
        log("AIManagerSonnet", "初始化AIManagerSonnet")
        self.sonnet_service = Sonnet()

        # 注释掉Stable Diffusion初始化，改为创建空白图像
        # 读取API密钥用于Stable Diffusion
        try:
            key_path = os.path.join(os.path.dirname(__file__), "key.txt")
            with open(key_path, 'r') as f:
                api_key = f.read().strip()
            # self.sd_service = StableDiffusion(api_key)
            log("AIManagerSonnet", "已禁用StableDiffusion功能")
        except Exception as e:
            log("AIManagerSonnet", f"初始化StableDiffusion失败: {str(e)}")
            # self.sd_service = StableDiffusion(None)

        self.loop = None

        # 创建线程池
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(2)

        # 初始化任务集合和状态标志
        self.running_tasks = set()
        self._is_shutting_down = False
        self._cleanup_pending = False

        # 添加性能监控计数器
        self.conversation_count = 0
        self.last_memory_check = time.time()
        self.memory_check_interval = 1  # 每次对话检查一次内存

        # 初始化内存监控
        self.monitor_memory()

        # 创建简单的空白图像供测试使用
        self.blank_image = QImage(512, 512, QImage.Format.Format_RGB888)
        self.blank_image.fill(0xFFFFFF)  # 填充白色

    def monitor_memory(self):
        """监控内存使用情况"""
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            allocated = torch.cuda.memory_allocated() / 1024 ** 2
            reserved = torch.cuda.memory_reserved() / 1024 ** 2
            log("AIManagerSonnet", f"GPU内存使用 - 已分配: {allocated:.2f}MB, 已预留: {reserved:.2f}MB")

        process = psutil.Process()
        memory_info = process.memory_info()
        log("AIManagerSonnet",
            f"CPU内存使用 - RSS: {memory_info.rss / 1024 ** 2:.2f}MB, VMS: {memory_info.vms / 1024 ** 2:.2f}MB")

    def cleanup(self):
        """清理资源"""
        log("AIManagerSonnet", "开始清理资源")
        self._is_shutting_down = True

        # 取消所有运行中的任务
        for task in list(self.running_tasks):
            try:
                if hasattr(task, 'cancel'):
                    task.cancel()
            except Exception as e:
                log("AIManagerSonnet", f"取消任务时出错: {str(e)}")

        # 等待线程池完成
        self.thread_pool.waitForDone()

        # 清理其他资源
        self.running_tasks.clear()
        # 已移除StableDiffusion服务，不需要此清理
        # if hasattr(self, 'sd_service'):
        #     del self.sd_service
        if hasattr(self, 'sonnet_service'):
            del self.sonnet_service

        log("AIManagerSonnet", "资源清理完成")
        self._is_shutting_down = False

    def process_conversation(self, user_input: str):
        log("AIManagerSonnet", f"开始处理对话，用户输入: '{user_input}'")
        # 在单独线程中启动处理流程
        self.thread_pool.start(lambda: self._process_in_thread(user_input))
        log("AIManagerSonnet", "对话处理任务已加入线程池")

    def _process_in_thread(self, user_input: str):
        try:
            log("AIManagerSonnet", f"线程启动，准备处理: '{user_input}'")
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            # 设置默认的异常处理器
            def exception_handler(loop, context):
                exception = context.get('exception')
                msg = context.get('message')
                if exception:
                    log("AIManagerSonnet", f"异步任务异常: {str(exception)}")
                    self.error_occurred.emit(str(exception))
                elif msg:
                    log("AIManagerSonnet", f"异步任务消息: {msg}")

            self.loop.set_exception_handler(exception_handler)

            # 检查是否正在关闭
            if self._is_shutting_down:
                log("AIManagerSonnet", "管理器正在关闭，取消处理")
                return

            log("AIManagerSonnet", "开始运行主处理任务")
            main_task = self.loop.create_task(self._async_process(user_input))
            self.loop.run_until_complete(main_task)

        except Exception as e:
            log("AIManagerSonnet", f"线程处理错误: {str(e)}")
            self.error_occurred.emit(f"处理错误: {str(e)}")

    async def _async_process(self, user_input: str):
        log("AIManagerSonnet", f"开始异步处理用户输入: '{user_input}'")
        prompt_content = ""
        collecting_prompt = False
        collecting_think = False

        self.thinking_changed.emit(True)

        async for chunk in self.sonnet_service.generate_response(user_input):
            # 检查并处理</think>结束标签
            if collecting_think and "</think>" in chunk:
                parts = chunk.split("</think>")
                collecting_think = False
                # 如果标签后有内容，发送到UI
                if len(parts) > 1 and parts[1]:
                    self.text_chunk_ready.emit(parts[1])
                continue

            # 检查并处理<think>开始标签
            if not collecting_think and "<think>" in chunk:
                parts = chunk.split("<think>")
                # 发送标签之前的文本
                if parts[0]:
                    self.text_chunk_ready.emit(parts[0])
                collecting_think = True
                continue

            # 跳过思考内容
            if collecting_think:
                continue

            # 检查并处理}结束标签
            if collecting_prompt and "}" in chunk:
                parts = chunk.split("}")
                if parts[0]:
                    prompt_content += parts[0]

                log("AIManagerSonnet", f"完整提示词: '{prompt_content}'")
                self.prompt_extracted.emit(prompt_content)

                # 启动图像生成任务
                log("AIManagerSonnet", "创建图像生成协程任务")
                image_task = asyncio.create_task(self._generate_image(prompt_content))
                try:
                    # 等待图像生成任务完成
                    log("AIManagerSonnet", "等待图像生成任务完成")
                    await image_task
                    log("AIManagerSonnet", "图像生成任务完成")
                except Exception as e:
                    log("AIManagerSonnet", f"图像生成任务出错: {str(e)}")
                    self.error_occurred.emit(f"图像生成失败: {str(e)}")

                collecting_prompt = False

                # 发送标签后的文本
                if len(parts) > 1 and parts[1]:
                    log("AIManagerSonnet", f"发送{"}"}后的文本: '{parts[1]}'")
                    self.text_chunk_ready.emit(parts[1])

                continue

            # 检查并处理{开始标签
            if not collecting_prompt and "{" in chunk:
                parts = chunk.split("{")
                if parts[0]:
                    self.text_chunk_ready.emit(parts[0])

                collecting_prompt = True
                prompt_content = ""

                # 如果标签后有内容，添加到提示词
                if len(parts) > 1 and parts[1]:
                    prompt_content += parts[1]

                continue

            # 收集提示词内容
            if collecting_prompt:
                prompt_content += chunk
            # 正常文本内容
            else:
                self.text_chunk_ready.emit(chunk)

        log("AIManagerSonnet", "发出thinking_changed信号(False)")
        self.thinking_changed.emit(False)
        log("AIManagerSonnet", "异步处理完成")

    async def _generate_image(self, prompt: str):
        # 替换为返回空白图像而不是使用StableDiffusion
        log("AIManagerSonnet", f"图像生成已禁用，返回空白图像。原提示词: '{prompt}'")
        
        # 直接返回空白图像
        qt_images = [self.blank_image]
        
        # 发送信号到UI
        self.image_ready.emit(qt_images)
        
        return True

    # 以下是原来的代码，已注释掉
    '''
    async def _generate_image(self, prompt: str):
        # 该方法与原来的AIManager中的方法完全相同
        log("AIManagerSonnet", f"开始生成图像, 提示词: '{prompt}'")
        try:
            # 检查并清理内存
            self.conversation_count += 1
            if self.conversation_count % self.memory_check_interval == 0:
                self.monitor_memory()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

            future = self.loop.create_future()
            log("AIManagerSonnet", f"当前loop状态：{self.loop}, future: {future}")

            def generate_and_set_result():
                try:
                    result = self.sd_service.generate_image(prompt)
                    self.loop.call_soon_threadsafe(future.set_result, result)
                except Exception as e:
                    log("AIManagerSonnet", f"执行generate_image报错{e}")
                    self.loop.call_soon_threadsafe(future.set_exception, e)

            self.thread_pool.start(generate_and_set_result)
            pil_images = await future
            log("AIManagerSonnet", f"成功获取图像：{pil_images}")

            if not pil_images:
                log("AIManagerSonnet", "生成图像失败，返回为空")
                self.error_occurred.emit("图像生成失败")
                return False

            # 转换PIL图像为QImage
            qt_images = []
            for pil_image in pil_images:
                try:
                    if pil_image.mode != 'RGB':
                        pil_image = pil_image.convert('RGB')
                    width = pil_image.width
                    height = pil_image.height
                    bytes_data = pil_image.tobytes('raw', 'RGB')
                    qimage = QImage(bytes_data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
                    qt_images.append(qimage)
                except Exception as e:
                    log("AIManagerSonnet", f"图像转换错误: {str(e)}")
                    continue

            if qt_images:
                log("AIManagerSonnet", f"图像生成完成，转换后的图像数量: {len(qt_images)}")
                self.image_ready.emit(qt_images)
                return True
            else:
                log("AIManagerSonnet", "没有生成有效的图像")
                self.error_occurred.emit("图像转换失败")
                return False
        except Exception as e:
            log("AIManagerSonnet", f"图像生成过程中出错: {str(e)}")
            self.error_occurred.emit(f"图像生成错误: {str(e)}")
            return False
    '''
