import os
import json
from pathlib import Path
import sys
import re
from openai import OpenAI

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import dotenv

dotenv.load_dotenv()


def natural_sort_key(path: Path) -> tuple:
    """自然排序键函数"""
    parts = re.split(r'(\d+)', path.name)
    result = []
    for part in parts:
        try:
            result.append(int(part))
        except ValueError:
            result.append(part)
    return tuple(result)


def read_json_file(file_path: Path) -> list:
    """读取JSON文件并返回数据，统一返回列表格式"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if isinstance(data, dict) and "items" in data:
            return data["items"]
        return data


def extract_book_title(filename: str) -> str:
    """从文件名中提取书名，取第一个下划线之前的内容"""
    # 从 "dianlixitonggongchengjich_page_5_merged.json" 提取 "dianlixitonggongchengjich"
    match = re.match(r'^([^_]+)', filename)
    if match:
        return match.group(1)
    return "booktitle"


def find_min_page_file(json_files: list) -> str:
    """找到页码最小的_page_x_merged.json文件"""
    min_page = float('inf')
    min_file = None
    
    for file_path in json_files:
        filename = file_path.name
        # 匹配_page_x_merged.json模式
        match = re.search(r'_page_(\d+)_merged\.json', filename)
        if match:
            page_num = int(match.group(1))
            if page_num < min_page:
                min_page = page_num
                min_file = filename
    
    return min_file


def send_to_llm(data: list) -> str:
    """将数据发送到LLM并获取响应"""
    client = OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    few_shot_example = """
以下是示例输入和输出：

输入：
[
  {
    "text": "3.1 电力网络",
    "number": 25,
    "level": 3
  },
  {
    "text": "等效电路",
    "number": 25,
    "level": 3
  },
  {
    "text": "思 考 题",
    "number": 324,
    "level": 3
  }
]

期望输出：
{
  "delete_items": [
    {
      "text": "3.1 电力网络",
      "number": 25,
      "level": 3
    },
    {
      "text": "等效电路",
      "number": 25,
      "level": 3
    },
    {
      "text": "思 考 题",
      "number": 324,
      "level": 3
    }
  ],
  "add_items": [
    {
      "text": "3.1 电力网络等效电路",
      "number": 25,
      "level": 3
    },
    {
      "text": "思考题",
      "number": 324,
      "level": 3
    }
  ]
}
"""

    prompt = f"""
请分析以下目录结构的JSON数据，完成以下任务：

1. 合并意外被切分的条目（例如："3.1 电力网络" 和 "等效电路" 应该合并为 "3.1 电力网络等效电路"）
2. 修复空格误用问题（例如："思 考 题" 应该修正为 "思考题"）

请按照以下格式返回结果：
{{
  "delete_items": [
    // 需要删除的条目，直接复制原始条目
  ],
  "add_items": [
    // 需要添加的新条目，包含修正后的内容
  ]
}}

{few_shot_example}

原始数据：
{json.dumps(data, ensure_ascii=False, indent=2)}

请只返回上述格式的JSON，不要包含其他任何内容。
"""

    completion = client.chat.completions.create(
        model="qwen3-235b-a22b-instruct-2507",
        messages=[
            {"role": "system", "content": "你是一个专门处理目录结构的助手。"},
            {"role": "user", "content": prompt},
        ],
        extra_body={"enable_thinking": False},
    )
    
    return completion.choices[0].message.content


def apply_modifications(data: list, modifications: dict) -> list:
    """应用LLM返回的修改到数据上"""
    # 创建数据副本以避免修改原始数据
    result_data = [item.copy() for item in data]
    
    # 删除指定的条目
    delete_items = modifications.get("delete_items", [])
    for item in delete_items:
        # 查找并删除匹配的条目
        for i in range(len(result_data) - 1, -1, -1):
            if (result_data[i]["text"] == item["text"] and 
                result_data[i]["number"] == item["number"] and 
                result_data[i]["level"] == item["level"]):
                result_data.pop(i)
                break
    
    # 添加新的条目
    add_items = modifications.get("add_items", [])
    result_data.extend(add_items)
    
    return result_data


def main():
    input_dir = Path(os.environ.get('CONTENT_PREPROCESSOR_INPUT', 'input'))
    output_dir = Path(os.environ.get('CONTENT_PREPROCESSOR_OUTPUT', 'output'))
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    json_files = sorted(input_dir.glob("*.json"), key=natural_sort_key)
    combined_data = []
    book_title = "booktitle"  # 默认书名

    # 找到页码最小的_page_x_merged.json文件
    min_page_file = find_min_page_file(json_files)
    if min_page_file:
        book_title = extract_book_title(min_page_file)
    else:
        # 如果没找到匹配的文件，从任意一个文件中提取
        for file_path in json_files:
            if file_path.name != "file_info.json":
                book_title = extract_book_title(file_path.name)
                break

    # 读取所有JSON文件数据
    for file_path in json_files:
        if file_path.name != "file_info.json":
            data = read_json_file(file_path)
            if data:
                combined_data.extend(data)

    # 保存合并后的数据
    combined_output_file = input_dir / "combined_output.json"
    with open(combined_output_file, 'w', encoding='utf-8') as f:
        json.dump(combined_data, f, ensure_ascii=False, indent=2)

    # 发送到LLM处理
    llm_response = send_to_llm(combined_data)
    
    # 保存原始响应到与combined_output.json相同的位置
    initial_reply_file = input_dir / "initial_reply.txt"
    with open(initial_reply_file, 'w', encoding='utf-8') as f:
        f.write(llm_response)
    
    # 解析并应用修改
    try:
        modifications = json.loads(llm_response)
        processed_data = apply_modifications(combined_data, modifications)
        
        # 保存处理后的数据到CONTENT_PREPROCESSOR_OUTPUT目录，使用书名作为文件名
        final_output_file = output_dir / f"{book_title}_final.json"
        with open(final_output_file, 'w', encoding='utf-8') as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=2)
            
    except json.JSONDecodeError as e:
        print(f"LLM返回的响应不是有效的JSON: {e}")
        print("原始响应内容:")
        print(llm_response)
        raise


if __name__ == "__main__":
    main()
