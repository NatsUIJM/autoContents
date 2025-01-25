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
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Remove x.x.x entries
        data = remove_entries(data)
        original_data = json.dumps(data, ensure_ascii=False, indent=2)
        
        attempt = 1
        current_response = ""
        
        while True:
            # Create model prompt
            if attempt == 1:
                system_prompt = """请协助我处理这份JSON文件。这是一份目录文件，包含了一本书的完整目录。
你的任务是调整目录层级`level`。当前的文档中，大部分的目录层级是正确的。但是由于目录是分段处理的，所以少部分的目录的层级可能过高，也就是`level`字段过大。
请先总览整个文档，判断出第一级标题的结构特点（它们一般是篇或者章），然后判断第二级和第三级标题的特征。这个文件可能一共有两级标题也可能是三级标题，但不会更少或更多。
请给出完整的修改后的JSON文件。直接输出结果，不要附带任何说明或者解释。"""
                user_content = original_data
            else:
                system_prompt = """请协助我处理这份JSON文件。这是一份目录文件，包含了一本书的完整目录。
你的任务是调整目录层级`level`。当前的文档中，大部分的目录层级是正确的。但是由于目录是分段处理的，所以少部分的目录的层级可能过高，也就是`level`字段过大。
请先总览整个文档，判断出第一级标题的结构特点（它们一般是篇或者章），然后判断第二级和第三级标题的特征。这个文件可能一共有两级标题也可能是三级标题，但不会更少或更多。
请给出完整的修改后的JSON文件。直接输出结果，不要附带任何说明或者解释。

JSON文件以及部分处理后的结果已经给出，请基于这份不完整的结果，继续处理。

例如：不完整的结果：
```json
{
  "items": [
    {
      "text": "第1篇 力学",
      "number": null,
      "confirmed": false,
      "level": 1
    },
    [因为太长所以中间部分省略]
    {
      "text": "第15章 电磁感应",
      "number": 410,
      "confirmed": true,
      "level": 2
    },
    {
      "text": "15.1 法拉第电磁感应定律",
      "number": 410,
      "confirmed": true,
      "level": 3
    },
    {
      "text": "15.2 动
```

你应该输出的：
```json
{
  "items": [
    { 
      "text": "15.2 动生电动势",
      "number": 412,
      "confirmed": true,
      "level": 3
    },
    {
      "text": "15.3 感生电动势和感生电场",
      "number": 415,
      "confirmed": true,
      "level": 3
    },
    [直到目录完整输出为止]
  ]
}
```

注意输出格式应为完整的JSON结构，不要遗漏任何括号或者逗号。

再次提醒，请不要复述这段不完整的结果，而是在不完整的结果的末尾继续输出，给出之前未给出的部分的内容。这份不完整的结果是因为输出长度到达最大长度所以被截断而导致的，如果你复述了它，也会被截断而无法生成完整结果，请务必注意。
"""
                user_content = f"原始文件：\n{original_data}\n\n不完整的处理结果：\n{current_response}"

            print(f"\nAttempt {attempt}: Sending request to API...")
            
            # Stream the response
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

            # Save the current response with input filename
            cache_file = save_response(
                accumulated_response,
                file_path.stem,
                attempt,
                cache_dir
            )
            print(f"\nResponse saved to: {cache_file}")

            # Update current_response
            current_response = accumulated_response

            # Check if response is complete
            if is_complete_json(accumulated_response):
                try:
                    processed_data = json.loads(accumulated_response)
                    output_file = output_dir / file_path.name
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(processed_data, f, ensure_ascii=False, indent=2)
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