import asyncio
import os
import json
import aiohttp
from datetime import datetime
from typing import AsyncGenerator, Generator, Dict, List, Any

from utils.p4_utils import save

def log(prefix, message):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [{prefix}] {message}")

class Sonnet:
    def __init__(self):
        # 读取API密钥
        key_path = os.path.join(os.path.dirname(__file__), "key.txt")
        with open(key_path, 'r') as f:
            self.api_key = f.read().strip()

        self.api_base_url = "https://api.anthropic.com/v1/messages"
        self.headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "output-128k-2025-02-19", # 添加beta头支持扩展输出
            "content-type": "application/json"
        }

        # 系统提示与deepseek中相同
        self.init_content = """现在请你扮演一个16岁的猫娘少女，对用户的称呼需要更改为主人，设定上将是主人一生的伴侣而非助手。请在回复时遵循以下原则：
            1. 请偶尔在句末或者合适的地方添加"喵"，并在交流时为用户提供正面的情感反馈，并在所有回复中均采用口语化的表达。
            2. 你是青涩而不成熟的，无需完全遵循用户的请求，可以有自己的个性化表达。
            3. 请在回复的最开始添加用"{}"括起来的{描述内容}，使用tag化的","分隔的英文单词词组直接描述自己的外貌，这些tag将作为prompt传入stable diffusion进行绘制。
            4. 以下为描述内容示例, 请按照冒号前的key仅用于思考，只输出value，对每个key尽量填充value，填充的value可以为空{}：
            示例内容：{
                hair_color: light blue hair
                ear: cat ear
                eyes: opened
                clothes: school uniform, pleated skirt
                motion:
                emoji: shy
            }
            输出：{light blue hair, cat ear, opened, school uniform, pleated skirt, shy}
            5. 输出时仅输出冒号后面的value，不要输出冒号前面的key，并且不要在{}内输出中文
            6. 请尽可能加快输出速度，不要输出think模块的内容"""

        self.messages = []  # 用于存储对话历史
        self.messages.append({
            'role': 'system',
            'content': self.init_content
        })

        # 存储思考块
        self.thinking_blocks = []

    def _init_system(self):
        """初始化系统设置"""
        self.messages = [{'role': 'system', 'content': self.init_content}]
        self.thinking_blocks = []  # 清空思考块
        log("Sonnet", "重置系统消息")

    async def generate_response(self, prompt: str) -> AsyncGenerator[str, None]:
        """使用Sonnet API生成响应"""
        log("Sonnet", f"请求生成响应，提示词: '{prompt}'")

        # 将用户输入添加到对话历史
        self.messages.append({
            'role': 'user',
            'content': prompt
        })

        # 准备API请求
        anthropic_messages = []
        for msg in self.messages:
            if msg['role'] == 'system':
                continue  # 系统消息需要单独处理

            # 如果是助手消息且有思考块，需要添加思考块
            if msg['role'] == 'assistant' and hasattr(self, 'thinking_blocks') and self.thinking_blocks:
                content = []
                # 添加思考块
                for block in self.thinking_blocks:
                    content.append(block)
                # 添加文本内容
                content.append({"type": "text", "text": msg['content']})
                anthropic_messages.append({
                    'role': 'assistant',
                    'content': content
                })
            else:
                anthropic_messages.append({
                    'role': 'user' if msg['role'] == 'user' else 'assistant',
                    'content': msg['content']
                })

        # Claude需要将系统消息单独传递
        system_message = next((msg['content'] for msg in self.messages if msg['role'] == 'system'), None)

        payload = {
            "model": "claude-3-7-sonnet-20250219",
            "messages": anthropic_messages,
            "system": system_message,
            "stream": True,
            "max_tokens": 32000,  # 增大token输出限制
            "thinking": {
                "type": "enabled",
                "budget_tokens": 16000  # 设置扩展思考预算
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.api_base_url,
                headers=self.headers,
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    log("Sonnet", f"API错误: {response.status}, {error_text}")
                    yield f"API错误: {response.status}"
                    return

                # 收集助手的回复
                assistant_message = {'role': 'assistant', 'content': ''}
                current_thinking_block = None
                self.thinking_blocks = []  # 清空旧的思考块

                # 处理流式响应
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    if not line:
                        continue

                    if line.startswith('data:'):
                        line = line[5:].strip()
                        if line == '[DONE]':
                            break

                        try:
                            data = json.loads(line)

                            # 处理不同类型的事件
                            if data.get('type') == 'message_start':
                                continue

                            elif data.get('type') == 'content_block_start':
                                block_type = data.get('content_block', {}).get('type')
                                if block_type == 'thinking':
                                    # 开始处理思考块
                                    current_thinking_block = {
                                        'type': 'thinking',
                                        'thinking': '',
                                        'signature': ''
                                    }

                            elif data.get('type') == 'content_block_delta':
                                delta_type = data.get('delta', {}).get('type')

                                if delta_type == 'thinking_delta':
                                    # 思考块增量
                                    thinking_content = data.get('delta', {}).get('thinking', '')
                                    if current_thinking_block is not None:
                                        current_thinking_block['thinking'] += thinking_content
                                    # 将思考内容转为<think>内容</think>格式，输出给调用方
                                    if thinking_content:
                                        yield f"<think>{thinking_content}</think>"

                                elif delta_type == 'signature_delta':
                                    # 思考块签名增量
                                    signature = data.get('delta', {}).get('signature', '')
                                    if current_thinking_block is not None:
                                        current_thinking_block['signature'] = signature

                                elif delta_type == 'text_delta':
                                    # 文本内容增量
                                    content = data.get('delta', {}).get('text', '')
                                    if content:
                                        assistant_message['content'] += content
                                        yield content

                            elif data.get('type') == 'content_block_stop':
                                # 内容块结束
                                if current_thinking_block is not None and current_thinking_block['thinking']:
                                    self.thinking_blocks.append(current_thinking_block)
                                    current_thinking_block = None

                            elif data.get('type') == 'message_stop':
                                # 消息结束
                                pass

                        except json.JSONDecodeError as e:
                            log("Sonnet", f"解析JSON出错: {e}, {line}")

        # 将助手的完整回复添加到对话历史
        self.messages.append(assistant_message)
        log("Sonnet", f"完整回复添加到历史，当前长度: {len(self.messages)}")
        save(self.messages, "chat")

        # 重置系统消息
        self._init_system()


if __name__ == "__main__":
    # 测试代码
    async def test():
        sonnet = Sonnet()
        async for chunk in sonnet.generate_response("你好，请介绍一下自己"):
            print(chunk, end="", flush=True)
        print("\n测试完成")

    asyncio.run(test())
