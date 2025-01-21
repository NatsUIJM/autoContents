import os
import json
import asyncio
import time
from openai import AsyncOpenAI
import platform
from pathlib import Path
from typing import Dict

# 创建异步客户端实例
client = AsyncOpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
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

# 创建全局进度追踪器
progress_tracker = ProgressTracker()

class TokenCounter:
    def __init__(self):
        self.completion_tokens = 0
        self.prompt_tokens = 0
    
    def update(self, completion_tokens, prompt_tokens):
        self.completion_tokens += completion_tokens
        self.prompt_tokens += prompt_tokens

def get_system_prompt() -> str:
    """生成系统提示"""
    return """Task: 处理JSON格式的目录数据，修正文本错误并规范化格式。

Request:
1. 文本处理要求：
   - 修正text字段中的OCR识别错误（通常每条数据最多1-2个形近字错误）
   - 在章节序号和标题之间添加一个空格分隔
    
2. 页码处理规则：
对于number字段为null的情况，需处理以下三种场景：
   a. OCR未识别页码（常见于目录开头的个位数页码）：
      - 保持"number":null
      - 输出时标记"confirmed": false
   
   b. 标题换行导致分散（常见于较长标题）：
      - 将本行与相邻行合并为完整标题
      - 使用已有的页码
      - 输出时标记"confirmed": true
   
   c. 原书未标注页码（常见于一二级标题）：
      - 使用该部分第一个有页码的子标题页码
      - 输出时标记"confirmed": true

3. 标题合并规则：
   - 遇到含章节号且结尾不完整的条目时，与下一个无章节号的条目合并
   - 合并后使用下一条目的页码

4. 层级处理规则：
   - 如果"章"是最大标题层级
     * 章为level 1，节为level 2，忽略更小的层级
   - 如果"章"之上还有一个层级的标题
     * 章之上的层级为level1，章为level 2，节为level 3，忽略更小的层级

5. 输出格式要求：
   - 输出为一个JSON对象，包含一个"items"数组字段
   - 数组中的每个元素包含四个字段：
     * "text": 处理后的文本内容
     * "number": 页码数值或null
     * "confirmed": 页码是否确认(布尔值)
     * "level": 标题层级(1到2或3的整数)

请按照上述规则处理以下内容，输出符合要求的JSON格式数据。"""

system = """
You are a helpful assistant with these specific requirements:
1. Always be conservative about page number confidence. When in doubt, mark confirmed as false.
2. Any estimated or inferred page numbers must be marked as confirmed=false.
3. For chapter titles without explicit page numbers, default to confirmed=false unless there is clear evidence to mark it true.
4. Propagated page numbers (like using first sub-section's page number) should be marked as confirmed=false.
5. When processing TOC data, err on the side of caution - it's better to have more confirmed=false than missing uncertain cases.
"""

async def process_single_file(file_path: Path, output_dir: Path, token_counter: TokenCounter, retry_count: int = 1):
    """处理单个文件"""
    try:
        # 读取文件数据
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 创建模型提示
        prompt = f"{get_system_prompt()}\n\n{json.dumps(data, ensure_ascii=False, indent=2)}"
        
        # 更新输入字符计数
        progress_tracker.add_input_chars(len(prompt))
        
        # 最多重试指定次数
        for attempt in range(retry_count + 1):
            try:
                # 使用流式调用模型
                response = await client.chat.completions.create(
                    model="qwen-max",
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
                        
                        # 检查是否应该更新进度
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
                    # 生成错误信息JSON
                    error_data = {
                        "items": [{
                            "text": f"第一页 第一级标题 模型错误码{str(e)}",
                            "number": None,
                            "confirmed": False,
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
    input_dir = Path("4_initialContentInfo")
    output_dir = Path("4_1_LLMProcessed")
    
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
        tasks.append(process_single_file(file_path, output_dir, token_counters[file_path]))
    
    # 运行所有任务
    results = await asyncio.gather(*tasks)
    
    # 统计处理结果
    success_count = sum(1 for r in results if r)
    fail_count = len(results) - success_count
    print(f"\nProcessing complete. Success: {success_count}, Failed: {fail_count}")

if __name__ == '__main__':
    # 为Windows设置事件循环策略
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # 运行主协程
    asyncio.run(main())