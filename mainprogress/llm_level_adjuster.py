"""
文件名: llm_level_adjuster.py
功能: 使用DeepSeek模型调整目录层级结构，带重试机制
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import json
import re
import asyncio
import platform
from pathlib import Path
from openai import AsyncOpenAI
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

def clean_text_for_matching(text):
    """仅保留中文字符"""
    return ''.join(char for char in text if '\u4e00' <= char <= '\u9fff')

def match_text_with_model_output(original_text, model_items):
    """尝试匹配文本并返回对应的level值"""
    for text, level in model_items:
        if text == original_text:
            return level
    
    # 第二次尝试：仅匹配中文字符
    cleaned_original = clean_text_for_matching(original_text)
    for text, level in model_items:
        cleaned_model = clean_text_for_matching(text)
        if cleaned_original == cleaned_model:
            return level
    
    return None

def prepare_data_for_model(data):
    """移除number和confirmed字段"""
    if isinstance(data, dict):
        return {
            key: prepare_data_for_model(value)
            for key, value in data.items()
            if key not in ['number', 'confirmed']
        }
    elif isinstance(data, list):
        return [prepare_data_for_model(item) for item in data]
    return data

def convert_compressed_to_full(compressed_data):
    """将压缩格式转换为完整JSON格式"""
    items = []
    for text, level in compressed_data:
        items.append({
            "text": text,
            "level": level
        })
    return {"items": items}

def is_complete_json(text):
    """检查压缩格式JSON是否完整"""
    # 检查是否以方括号结尾，并且包含至少一个有效的条目
    text = text.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return False
    
    try:
        # 尝试解析JSON
        json.loads(text)
        return True
    except json.JSONDecodeError:
        return False

def save_response(content, input_filename, attempt, cache_dir, is_compressed=True):
    """保存响应到缓存目录"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"response_{input_filename}_attempt_{attempt}_{timestamp}.json"
    filepath = cache_dir / filename
    
    if is_compressed:
        # 如果是压缩格式，先转换为完整格式
        try:
            compressed_data = json.loads(content)
            full_data = convert_compressed_to_full(compressed_data)
            content = json.dumps(full_data, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            print("警告：压缩格式转换失败，保存原始内容")
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return filepath

async def process_file(client, file_path: Path, output_dir: Path, cache_dir: Path):
    try:
        print(f"Processing file: {file_path}")
        
        # 读取原始数据
        with open(file_path, 'r', encoding='utf-8') as f:
            original_data = json.load(f)
        
        # 准备发送给模型的数据
        model_input_data = prepare_data_for_model(original_data)
        model_input_json = json.dumps(model_input_data, ensure_ascii=False, indent=2)
        
        attempt = 1
        current_response = ""
        
        while True:
            if attempt == 1:
                system_prompt = """请协助我处理这份JSON文件。这是一份目录文件，包含了一本书的完整目录。
你的任务是为每个目录项添加合适的层级（level）。请先总览整个文档，判断出第一级标题的结构特点（它们一般是篇或者章），然后判断第二级和第三级标题的特征。
这个文件可能一共有两级标题也可能是三级标题，但不会更少或更多。请按照下面的输出格式，为每个条目添加正确的level字段。

请使用以下格式输出结果（示例）：
```json
[["第一章 绪论", 1],
["第一节 概述", 2],
["第二节 基本原理", 2]]
```

请注意，这是一个压缩格式的输出，每个条目是一个包含两个元素的列表，第一个元素是目录项的文本，第二个元素是level值。请直接输出结果，不要附带任何说明或者解释。
"""
                user_content = model_input_json
            else:
                system_prompt = """请继续处理之前的JSON文件，为每个目录项添加合适的层级（level）。
请基于这份不完整的结果继续处理。使用相同的压缩格式输出。"""
                user_content = f"原始文件：\n{model_input_json}\n\n不完整的处理结果：\n{current_response}"

            print(f"\nAttempt {attempt}: Sending request to API...")
            
            stream = await client.chat.completions.create(
                model="qwen-max",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                response_format={"type": "json_object"},
                stream=True
            )

            print(f"\nReceiving and processing response (Attempt {attempt}):")
            accumulated_response = ""
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    accumulated_response += content
                    print(content, end='', flush=True)

            # 保存当前响应
            cache_file = save_response(
                accumulated_response,
                file_path.stem,
                attempt,
                cache_dir
            )
            print(f"\nResponse saved to: {cache_file}")

            current_response = accumulated_response

            if is_complete_json(accumulated_response):
                try:
                    model_output = json.loads(accumulated_response)
                    
                    # 更新原始数据的level值
                    for item in original_data['items']:
                        new_level = match_text_with_model_output(item['text'], model_output)
                        if new_level is not None:
                            item['level'] = new_level
                    
                    # 保存最终结果
                    output_file = output_dir / file_path.name
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(original_data, f, ensure_ascii=False, indent=2)
                    print(f"\nProcessing complete. Final output saved to: {output_file}")
                    break
                except json.JSONDecodeError as e:
                    print(f"\nWarning: JSON parsing failed on attempt {attempt}")
                    print(f"Error: {str(e)}")
            
            attempt += 1
            print("\nResponse incomplete, continuing with next attempt...")
            
    except Exception as e:
        print(f"\nError processing {file_path.name}:")
        print(f"Type: {type(e).__name__}")
        print(f"Message: {str(e)}")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()

async def main():
    # Setup directories
    input_dir = Path(os.getenv("LEVEL_ADJUSTER_INPUT"))
    output_dir = Path(os.getenv("LEVEL_ADJUSTER_OUTPUT"))
    cache_dir = Path(os.getenv("LEVEL_ADJUSTER_CACHE"))
    
    for dir_path in [output_dir, cache_dir]:
        os.makedirs(dir_path, exist_ok=True)
    
    # Initialize client
    client = AsyncOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    
    # Process all JSON files
    tasks = []
    for file_path in input_dir.glob("*.json"):
        tasks.append(process_file(client, file_path, output_dir, cache_dir))
    
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())