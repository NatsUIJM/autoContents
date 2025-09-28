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

from dotenv import load_dotenv
load_dotenv()

ENABLE_DEEPSEEK = False  # 设置为False以禁用DeepSeek服务

def preprocess_model_output(raw_output: str) -> str:
    """
    Preprocess model output to remove commentary structures and clean up the JSON.
    Returns cleaned JSON string.
    """
    # 处理代码块包裹的JSON
    if "```json" in raw_output and "```" in raw_output:
        # 提取代码块中的JSON内容
        start_marker = "```json"
        end_marker = "```"
        start_index = raw_output.find(start_marker)
        if start_index != -1:
            content_start = start_index + len(start_marker)
            end_index = raw_output.find(end_marker, content_start)
            if end_index != -1:
                raw_output = raw_output[content_start:end_index].strip()
            else:
                # 如果找不到结束标记，尝试从开始标记后截取所有内容
                raw_output = raw_output[content_start:].strip()
    
    lines = raw_output.strip().split('\n')
    cleaned_lines = []
    
    # 找到最后一个实际的数组项（非空且非结束括号的行）
    last_item_index = -1
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if line and not line.startswith(']'):
            last_item_index = i
            break
    
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        
        # 如果行中包含花括号，只保留花括号之前的内容
        if '{' in line:
            line = line.split('{')[0]
        
        # 处理任意数量空格+制表符的情况
        if '\t' in line:
            line = line.split('\t')[0]
        
        # 移除行尾空白和逗号
        line = line.rstrip()
        line = line.rstrip(',')
        
        # 只给非最后项且非开括号行添加逗号
        if i < last_item_index and line.strip() and not line.strip() == '[' and not line.strip().startswith(']'):
            line = line + ','
        
        if line:  # 确保清理后的行不为空
            cleaned_lines.append(line)
    
    # 重建JSON结构，确保格式正确
    joined = '\n'.join(cleaned_lines)
    
    # 如果没有开括号，添加它
    if not joined.strip().startswith('['):
        joined = '[\n' + joined
    
    # 如果没有闭括号，添加它
    if not joined.strip().endswith(']'):
        joined = joined + '\n]'
    
    # 处理null页码问题
    try:
        data = json.loads(joined)
        if isinstance(data, list):
            for i in range(len(data)):
                if data[i][1] is None:  # 检测到null页码
                    # 如果是最后一条，使用前一条的页码
                    if i == len(data) - 1:
                        # 向前查找非null的页码
                        prev_index = i - 1
                        while prev_index >= 0 and data[prev_index][1] is None:
                            prev_index -= 1
                        
                        if prev_index >= 0:  # 找到了非null的页码
                            data[i][1] = data[prev_index][1]
                        else:  # 所有前面的页码都是null，使用1作为默认值
                            data[i][1] = 1
                    else:
                        # 向后查找非null的页码
                        next_index = i + 1
                        while next_index < len(data) and data[next_index][1] is None:
                            next_index += 1
                        
                        if next_index < len(data):  # 找到了非null的页码
                            data[i][1] = data[next_index][1]
                        else:  # 所有后面的页码都是null，向前查找
                            prev_index = i - 1
                            while prev_index >= 0 and data[prev_index][1] is None:
                                prev_index -= 1
                            
                            if prev_index >= 0:  # 找到了非null的页码
                                data[i][1] = data[prev_index][1]
                            else:  # 都是null，使用1作为默认值
                                data[i][1] = 1
            
            # 将处理后的数据转回JSON字符串
            joined = json.dumps(data, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        # 如果JSON解析失败，保留原始清理后的文本
        pass
        
    return joined

class ServiceConfig(NamedTuple):
    name: str
    api_key_env: str
    base_url: str
    model_name: str

def strip_items_wrapper(data: dict | list) -> list:
    """Remove the 'items' wrapper from input JSON"""
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    return data

def is_valid_format(data) -> bool:
    """
    Validate if the data matches the required format:
    [["title", page_number], ...]
    where page_number must be an integer
    """
    try:
        if not isinstance(data, list):
            return False
        
        for item in data:
            if not isinstance(item, list) or len(item) != 2:
                return False
            if not isinstance(item[0], str):
                return False
            if not isinstance(item[1], int):
                return False
        
        return True
    except Exception:
        return False
    
def convert_to_full_format(data: list) -> dict:
    """Convert input format to full format"""
    return {
        "items": [
            {
                "text": item[0],           # 第一个元素是文本
                "number": item[1],         # 第二个元素是页码
                "confirmed": True,         # 固定为 True
                "level": 1                 # 固定为 1
            }
            for item in data
        ]
    }

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
        return self.total_output_chars / (self.total_input_chars / 3 ) * 100

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
   1. 修复OCR错误。通常情况下，每个条目最多有1-2个字符错误
   2. 在编号和标题正文之间添加空格
   3. 删除多余的空格和异常符号
   4. 某些文本是异常识别，比如文本最后跟随着完全无法理解的文字，请删除这部分内容
   5. 有的教材名称会被识别进去，比如“高等数学（第一册）”，请删除这部分内容
   6. 如果是中英文混合标题，英文应使用半角括号括起来，如“第一章 电路基础（Circuit Basics）”
   7. 如果是纯英文标题，请不要把它翻译成中文；如果是繁体中文标题，也请保持其原始内容，而不是翻译为简体中文。
2. 页码处理：
   1. 某些标题原文有换行，导致被识别为两条，请将它们合并起来
   2. 某些标题没有匹配到页码，请合理估算（注意，只有你确信是页码丢失而不是标题换行时才要估算）
   3. 某些页码被少识别了一位，请在后面补零
3. 其他注意事项：
   1. 除了编号和标题正文之外，不要在中文和英文或数字之间加空格
   2. 选择阿拉伯数字还是中文数字，请遵循输入原始信息，不要随意更改
   3. 附录一般是一级或者二级标题，不隶属于正文部分
   4. 请不要包含任何解释性文字，直接输出要求的JSON文件
4. 请使用JSON格式输出，标准正确示例如下：

```json
[
  ["第1章 半导体器件基础", 3],
  ["1.1 基本要求", 3],
  ["1.2 精要指点", 3],
  ["1.2.1 半导体的基本知识", 3],
  ["1.2.2 半导体二极管", 5]
]
```

5. 易错案例：
   1. `第1章 自动控制概述`正确；`第 1章 自动控制概述`错误；`第1 章 自动控制概述`错误
   2. `第2章 超前滞后校正与PID校正`正确；`第2章 超前滞后校正与 PID校正`错误；`第2章 超前滞后校正与PID 校正`错误
   3. JSON错误格式案例：
```json
[
  ["第1章 半导体器件基础", "3"],  // 错误：应为数字（int），不要加引号（str）
  ["1.1 基本要求", 3],
  ["1.2 精要指点", 3]
]
```
```json
[
  ["1.1.3 PN结及其单向导电性", 4],
  ["1.1.4 PN结的击穿特性", 5], 	{"注释": "合理估算页码"},  // 错误：不要包含解释性文字
  ["1.1.5 PN结的电容效应", 8]
]
```
```json
[
  ["1.1.3 PN结及其单向导电性", 4],
  ["1.1.4 PN结的击穿特性", 5], 	{"number": 8, "text": "1.1.5 PN结的电容效应"},  // 错误：格式不符合要求
  ["1.2 半导体二极管", 9]
]
```
```json
[
  ["1.1.3 PN结及其单向导电性", 4],
  ["1.1.4 PN结的击穿特性", 5], 	"number"  							   ]  // 错误：格式错乱
```
```json
[
  ["模拟电子技术基础", null],  // 错误：不能包含教材名称；缺失的页码要合理估算
  ["5.4.6 集成运放的封装", 128],
  ["5.5 特殊集成运算放大器", 129]
]
```
```json
[
    ["第九章 抗肿瘤药 Anti-tumor Drugs", 1],  // 错误：中英文混合标题，英文应使用半角括号括起来，而不是全角括号或者不括起来
    ["第十章 生物信息学与生物信息处理", 2]  // 错误：中英文混合标题的英文部分丢失
]
常见错误示例：

1. 输入：`今日物理趣闻A基本粒子`
   错误输出：`今日物理趣闻 基本粒子` // 缺少输入中所包含的编号
   正确输出：`今日物理趣闻A 基本粒子`
2. 输入：`A. 1粒子的发现与特征`
   错误输出：`粒子的发现与特征` // 缺少输入中所包含的编号
   正确输出：`A.1 粒子的发现与特征`
3. 输入：`第一章 电路模型和电路定律`
   错误输出：`第1章 电路模型和电路定律` // 选择阿拉伯数字还是中文数字，请遵循输入原始信息，不要随意更改
   正确输出：`第一章 电路模型和电路定律`
4. 输入：`1-1 电路和电路模型`
   错误输出：`第一节 电路和电路模型`，`第一章 电路和电路模型` // 选择阿拉伯数字还是中文数字，请遵循输入原始信息，不要随意更改
   错误输出：`1.1 电路和电路模型` // 编号分隔符与输入不符
   正确输出：`1-1 电路和电路模型`
5. 输入：`*3-4 戴维南定理和诺顿定理`
   错误输出：`3-4 戴维南定理和诺顿定理` // 丢失*号
   正确输出：`*3-4 戴维南定理和诺顿定理`
6. 输入：`PARTA一THERMODYNAMICANDKINETICTHEORY`
   正确输出：`PART A - THERMODYNAMIC AND KINETIC THEORY`
   错误输出：`PART A 热力学与动力学理论（Thermodynamic and Kinetic Theory）` // 错误翻译，英文标题不应翻译成中文
   错误输出：`PART A 热力学与动力学理论` // 错误翻译，英文标题不应翻译成中文
   错误输出：`PART A Thermodynamic and Kinetic Theory` // 错误：原始内容是大写，不应该转换成小写
"""

system = """
You are a helpful assistant for a data processing task. You need to process JSON-formatted directory data, correct text errors, and standardize the format.
"""

async def process_single_file(file_path: Path, output_dir: Path, service_manager: ServiceManager, token_counter: TokenCounter, retry_count: int = 10):
    """处理单个文件"""
    try:
        # Create raw_responses subdirectory
        raw_responses_dir = output_dir / "raw_responses"
        os.makedirs(raw_responses_dir, exist_ok=True)

        if not ENABLE_DEEPSEEK and service_manager.config.name.lower() == 'deepseek':
            error_data = {
                "items": [{
                    "text": "模型错误",
                    "number": 1,
                    "confirmed": True,
                    "level": 1
                }]
            }
            output_file = output_dir / f"{file_path.stem}_{service_manager.config.name.lower()}_processed.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(error_data, f, ensure_ascii=False, indent=2)
            
            raw_response_file = raw_responses_dir / f"{file_path.stem}_{service_manager.config.name.lower()}_raw.json"
            with open(raw_response_file, 'w', encoding='utf-8') as f:
                json.dump(error_data, f, ensure_ascii=False, indent=2)
                
            print(f"Skipped {file_path.name} as DeepSeek is disabled")
            return False

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        stripped_data = strip_items_wrapper(data)
        prompt = f"{get_system_prompt()}\n\n{json.dumps(stripped_data, ensure_ascii=False, indent=2)}"
        progress_tracker.add_input_chars(len(prompt))
        
        for attempt in range(retry_count):
            try:
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

                # Store raw response
                raw_response_file = raw_responses_dir / f"{file_path.stem}_{service_manager.config.name.lower()}_raw_{attempt+1}.json"
                with open(raw_response_file, 'w', encoding='utf-8') as f:
                    f.write(full_response)
                
                try:
                    # Preprocess the model output before parsing
                    cleaned_response = preprocess_model_output(full_response)
                    
                    # Store cleaned response if it's different from raw response
                    if cleaned_response != full_response:
                        cleaned_response_file = raw_responses_dir / f"{file_path.stem}_{service_manager.config.name.lower()}_cleaned_{attempt+1}.json"
                        with open(cleaned_response_file, 'w', encoding='utf-8') as f:
                            f.write(cleaned_response)
                    
                    compressed_data = json.loads(cleaned_response)
                    
                    if not is_valid_format(compressed_data):
                        print(f"Invalid format in attempt {attempt + 1} for {file_path.name}. Retrying...")
                        continue
                    
                    processed_data = convert_to_full_format(compressed_data)
                    
                    output_file = output_dir / f"{file_path.stem}_{service_manager.config.name.lower()}_processed.json"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(processed_data, f, ensure_ascii=False, indent=2)
                    
                    print(f"Processed {file_path.name} using {service_manager.config.name} on attempt {attempt + 1}")
                    return True
                
                except json.JSONDecodeError:
                    print(f"Invalid JSON in attempt {attempt + 1} for {file_path.name}. Retrying...")
                    continue
                    
            except Exception as e:
                if attempt < retry_count - 1:
                    print(f"Retry {attempt + 1} for {file_path.name} using {service_manager.config.name} due to: {str(e)}")
                    continue
                else:
                    error_data = {
                        "items": [{
                            "text": f"模型错误，错误码{str(e)}",
                            "number": 1,
                            "confirmed": True,
                            "level": 1
                        }]
                    }
                    
                    output_file = output_dir / f"{file_path.stem}_{service_manager.config.name.lower()}_processed.json"
                    raw_response_file = raw_responses_dir / f"{file_path.stem}_{service_manager.config.name.lower()}_raw_final.json"
                    
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(error_data, f, ensure_ascii=False, indent=2)
                    with open(raw_response_file, 'w', encoding='utf-8') as f:
                        json.dump(error_data, f, ensure_ascii=False, indent=2)
                        
                    print(f"Failed to process {file_path.name} using {service_manager.config.name} after {retry_count} retries")
                    return False
        
        # If we've exhausted all retries
        error_data = {
            "items": [{
                "text": "模型输出格式验证失败",
                "number": 1,
                "confirmed": True,
                "level": 1
            }]
        }
        
        output_file = output_dir / f"{file_path.stem}_{service_manager.config.name.lower()}_processed.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(error_data, f, ensure_ascii=False, indent=2)
            
        print(f"Failed to get valid format for {file_path.name} after {retry_count} attempts")
        return False
                
    except Exception as e:
        print(f"Error processing {file_path.name} using {service_manager.config.name}: {str(e)}")
        return False
    
async def main():
    # 根据DeepSeek的启用状态决定要使用的服务
    service_managers = {
        'dashscope': ServiceManager('dashscope')
    }
    
    if ENABLE_DEEPSEEK:
        service_managers['deepseek'] = ServiceManager('deepseek')
    
    input_dir = Path(os.getenv('LLM_HANDLER_INPUT'))
    output_dir = Path(os.getenv('LLM_HANDLER_OUTPUT'))
    
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
        # 排除名为file_info的文件
        if file_path.name == "file_info.json":
            continue
        # 为每个服务创建一个计数器
        for service_name in service_managers:
            token_counters[f"{file_path}_{service_name}"] = TokenCounter()
            tasks.append(process_single_file(
                file_path, 
                output_dir, 
                service_managers[service_name],
                token_counters[f"{file_path}_{service_name}"]
            ))
    
    # 运行所有任务
    results = await asyncio.gather(*tasks)
    
    # 汇总处理结果
    success_count = sum(1 for r in results if r)
    fail_count = len(results) - success_count
    print(f"\nProcessing complete. Success: {success_count}, Failed: {fail_count}")
    
    # 根据成功失败数量返回退出码
    return 0 if success_count >= fail_count else 1

if __name__ == '__main__':
    # 为Windows设置事件循环策略
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # 运行主协程并获取退出码
    exit_code = asyncio.run(main())
    sys.exit(exit_code)