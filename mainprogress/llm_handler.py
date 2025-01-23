"""
文件名: llm_handler.py (原名: 5_2_model_process.py)
功能: 使用LLM服务处理原始内容数据，进行文本纠错和标准化
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import os
import json
import asyncio
import time
from openai import AsyncOpenAI
import platform
from pathlib import Path
from typing import Dict, NamedTuple
from config.paths import PathConfig

class ServiceConfig(NamedTuple):
    name: str
    api_key_env: str
    base_url: str
    model_name: str

SERVICES = {
    'dashscope': ServiceConfig(
        name='DashScope',
        api_key_env='DASHSCOPE_API_KEY',
        base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
        model_name='qwen-max'
    ),
    'deepseek': ServiceConfig(
        name='DeepSeek',
        api_key_env='DEEPSEEK_API_KEY',
        base_url='https://api.deepseek.com/v1',
        model_name='deepseek-chat'
    ),
    # Add more services as needed
}

class ServiceManager:
    def __init__(self, service_name: str):
        if service_name not in SERVICES:
            raise ValueError(f"Unsupported service: {service_name}")
        
        self.config = SERVICES[service_name]
        self.client = AsyncOpenAI(
            api_key=os.getenv(self.config.api_key_env),
            base_url=self.config.base_url
        )

class ProgressTracker:
    def __init__(self):
        self.total_input_chars = 0
        self.total_output_chars = 0
        self.last_progress_time = 0
        self.start_time = time.time()
        self.processed_chars = 0
    
    def add_input_chars(self, count: int):
        self.total_input_chars += count
    
    def add_output_chars(self, count: int):
        self.total_output_chars += count
        self.processed_chars += count
    
    def get_progress(self) -> float:
        if self.total_output_chars == 0:
            return 0.0
        return self.total_output_chars / (self.total_input_chars / 0.65) * 100

    def get_time_estimate(self) -> str:
        if self.processed_chars == 0:
            return "calculating..."
        
        elapsed_time = time.time() - self.start_time
        chars_per_second = self.processed_chars / elapsed_time
        remaining_chars = (self.total_input_chars / 0.65) - self.total_output_chars
        
        if chars_per_second > 0:
            remaining_seconds = remaining_chars / chars_per_second
            remaining_minutes = int(remaining_seconds / 60)
            remaining_seconds = int(remaining_seconds % 60)
            return f"{remaining_minutes}m {remaining_seconds}s"
        return "calculating..."

    def should_update(self) -> bool:
        current_time = time.time()
        if current_time - self.last_progress_time >= 1:
            self.last_progress_time = current_time
            return True
        return False

# Create global progress tracker
progress_tracker = ProgressTracker()

class TokenCounter:
    def __init__(self):
        self.completion_tokens = 0
        self.prompt_tokens = 0
    
    def update(self, completion_tokens, prompt_tokens):
        self.completion_tokens += completion_tokens
        self.prompt_tokens += prompt_tokens

def get_system_prompt() -> str:
    """Generate system prompt"""
    return """请协助我规范化JSON格式的目录数据。要求如下：

1.  文本处理：
   1. 修复OCR错误。通常情况下，每个条目最多有1-2个字符错误。
   2. 在编号和标题正文之间添加空格
   3. 删除多余的空格和异常符号
   4. 如果标题是中英双语的，忽略英语部分
2. 页码处理：
   1. 某些标题原文有换行，导致被识别为两条，请将它们合并起来
   2. 某些标题没有匹配到页码，请返回`number=null`
3. 标题层级：在输入的文件中，最高级别的标题（一般为篇或者章）为`level=1`，标题层级越低则`level`值越大
4. 其他注意事项：
   1. 除了编号和标题正文之外，不要在中文和英文或数字之间加空格
   2. 选择阿拉伯数字还是中文数字，请遵循输入原始信息，不要随意更改
5. 处理案例：
   1. `第1章 自动控制概述`正确；`第 1章 自动控制概述`错误；`第1 章 自动控制概述`错误
   2. `第2章 超前滞后校正与PID校正`正确；`第2章 超前滞后校正与 PID校正`错误；`第2章 超前滞后校正与PID 校正`错误
   
请使用JSON格式输出，示例如下：

``` json
{
  "items": [
    {
      "text": "第1章 自动控制概述",
      "number": null,
      "confirmed": false,
      "level": 1
    },
    {
      "text": "第一节 自动控制和自动控制技术",
      "number": 1,
      "confirmed": true,
      "level": 2
    },
    {
      "text": "第二节 自动控制系统的组成及分类",
      "number": 6,
      "confirmed": true,
      "level": 2
    }
  ]
}
```

"""

system = """
You are a helpful assistant for a data processing task. You need to process JSON-formatted directory data, correct text errors, and standardize the format.
"""

async def process_single_file(file_path: Path, output_dir: Path, service_manager: ServiceManager, token_counter: TokenCounter, retry_count: int = 1):
    """处理单个文件"""
    try:
        # 读取文件数据
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 创建模型提示词
        prompt = f"{get_system_prompt()}\n\n{json.dumps(data, ensure_ascii=False, indent=2)}"
        
        # 更新输入字符计数
        progress_tracker.add_input_chars(len(prompt))
        
        # 指定重试次数
        for attempt in range(retry_count + 1):
            try:
                # 使用流式调用模型
                response = await service_manager.client.chat.completions.create(
                    model=service_manager.config.model_name,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    stream=True
                )
                
                full_response = ""
                async for chunk in response:
                    if chunk.choices[0].delta.content is not None:
                        content = chunk.choices[0].delta.content
                        full_response += content
                        progress_tracker.add_output_chars(len(content))
                        
                        if progress_tracker.should_update():
                            print(f"Progress: {progress_tracker.get_progress():.2f}% | Estimated time remaining: {progress_tracker.get_time_estimate()}")
                            
                    if hasattr(chunk, 'usage') and chunk.usage:
                        token_counter.update(
                            chunk.usage.completion_tokens,
                            chunk.usage.prompt_tokens
                        )
                
                # 验证JSON格式
                processed_data = json.loads(full_response)
                
                # 保存处理后的数据
                output_file = output_dir / f"{file_path.stem}_processed.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(processed_data, f, ensure_ascii=False, indent=2)
                
                print(f"Processed {file_path.name}")
                return True
                
            except Exception as e:
                if attempt < retry_count:
                    print(f"Retry {attempt + 1} for {file_path.name} due to: {str(e)}")
                    continue
                else:
                    error_data = {
                        "items": [{
                            "text": f"错误码{str(e)}",
                            "number": 1,
                            "confirmed": True,
                            "level": 1
                        }]
                    }
                    output_file = output_dir / f"{file_path.stem}_processed.json"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(error_data, f, ensure_ascii=False, indent=2)
                    print(f"Failed to process {file_path.name} after {retry_count} retries")
                    return False
                
    except Exception as e:
        print(f"Error processing {file_path.name}: {str(e)}")
        return False

async def main():
    # 获取服务选择
    service_name = os.getenv('LLM_SERVICE', 'dashscope').lower()
    service_manager = ServiceManager(service_name)
    
    input_dir = Path(PathConfig.LLM_HANDLER_INPUT)
    output_dir = Path(PathConfig.LLM_HANDLER_OUTPUT)
    
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 读取文件信息
    with open(input_dir / "file_info.json", 'r', encoding='utf-8') as f:
        file_info = json.load(f)
    
    # 创建任务列表
    tasks = []
    token_counters = {}
    
    for file_path_str in file_info.keys():
        file_path = Path(file_path_str)
        token_counters[file_path] = TokenCounter()
        tasks.append(process_single_file(file_path, output_dir, service_manager, token_counters[file_path]))
    
    # 运行所有任务
    results = await asyncio.gather(*tasks)
    
    # 汇总处理结果
    success_count = sum(1 for r in results if r)
    fail_count = len(results) - success_count
    print(f"\nProcessing complete. Success: {success_count}, Failed: {fail_count}")

if __name__ == '__main__':
    # 为Windows设置事件循环策略
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # 运行主协程
    asyncio.run(main())