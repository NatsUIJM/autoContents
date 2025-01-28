"""
文件名: llm_level_adjuster.py
功能: 使用DeepSeek模型调整目录层级结构，带重试机制
"""
import os
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import sys
import json
import re
import asyncio
import platform
from pathlib import Path
from openai import AsyncOpenAI
from datetime import datetime
from config.paths import PathConfig

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

def clean_text_for_matching(text):
    """仅保留中文字符"""
    return ''.join(char for char in text if '\u4e00' <= char <= '\u9fff')

def match_text_with_model_output(original_text, model_items):
    """尝试匹配文本并返回对应的level值"""
    # 第一次尝试：精确匹配
    for item in model_items:
        if item['text'] == original_text:
            return item.get('level')
    
    # 第二次尝试：仅匹配中文字符
    cleaned_original = clean_text_for_matching(original_text)
    for item in model_items:
        cleaned_model = clean_text_for_matching(item['text'])
        if cleaned_original == cleaned_model:
            return item.get('level')
    
    return None

def prepare_data_for_model(data):
    """移除number和level字段"""
    if isinstance(data, dict):
        return {
            key: prepare_data_for_model(value)
            for key, value in data.items()
            if key not in ['number', 'level']
        }
    elif isinstance(data, list):
        return [prepare_data_for_model(item) for item in data]
    return data

def remove_entries(data):
    if isinstance(data, list):
        return [remove_entries(item) for item in data if not (isinstance(item, dict) and re.match(r'^\d+\.\d+\.\d+', item.get('text', '')))]
    elif isinstance(data, dict):
        return {key: remove_entries(value) for key, value in data.items()}
    else:
        return data

def is_complete_json(text):
    """检查JSON是否完整"""
    return text.strip().endswith("}\n  ]\n}")

def save_response(content, input_filename, attempt, cache_dir):
    """保存响应到缓存目录，使用输入文件名作为前缀"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"response_{input_filename}_attempt_{attempt}_{timestamp}.json"
    filepath = cache_dir / filename
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
            # 创建模型提示
            if attempt == 1:
                system_prompt = """请协助我处理这份JSON文件。这是一份目录文件，包含了一本书的完整目录。
你的任务是为每个目录项添加合适的层级（level）。请先总览整个文档，判断出第一级标题的结构特点（它们一般是篇或者章），然后判断第二级和第三级标题的特征。
这个文件可能一共有两级标题也可能是三级标题，但不会更少或更多。请给出完整的JSON文件，为每个条目添加正确的level字段。
直接输出结果，不要附带任何说明或者解释。
输出格式要求：
```json
{
  "items": [
    {
      "text": "第一章",
      "level": 1
    },
    {
      "text": "第一节",
      "level": 2
    },
    {
      "text": "第一小节",
      "level": 3
    }
    ]
}

"""
                user_content = model_input_json
            else:
                system_prompt = """请继续处理之前的JSON文件，为每个目录项添加合适的层级（level）。
请基于这份不完整的结果继续处理。直接输出结果，不要附带任何说明或者解释。"""
                user_content = f"原始文件：\n{model_input_json}\n\n不完整的处理结果：\n{current_response}"

            print(f"\nAttempt {attempt}: Sending request to API...")
            
            # 获取流式响应
            stream = await client.chat.completions.create(
                model="qwen-long",
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

            # 检查响应是否完整
            if is_complete_json(accumulated_response):
                try:
                    model_output = json.loads(accumulated_response)
                    
                    # 更新原始数据的level值
                    for item in original_data['items']:
                        new_level = match_text_with_model_output(item['text'], model_output['items'])
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
    input_dir = Path(PathConfig.LEVEL_ADJUSTER_INPUT)
    output_dir = Path(PathConfig.LEVEL_ADJUSTER_OUTPUT)
    cache_dir = Path(PathConfig.LEVEL_ADJUSTER_CACHE)
    
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