import os
import json
from pathlib import Path
import sys
import re
import dotenv

# 严格保持原始路径逻辑
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

# 加载 .env 文件 (路径逻辑保持不变)
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
    """读取 JSON 文件并返回数据，统一返回列表格式"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if isinstance(data, dict) and "items" in data:
            return data["items"]
        return data


def extract_book_title(filename: str) -> str:
    """从文件名中提取书名，取第一个下划线之前的内容"""
    match = re.match(r'^([^_]+)', filename)
    if match:
        return match.group(1)
    return "booktitle"


def find_min_page_file(json_files: list) -> str:
    """找到页码最小的_page_x_merged.json 文件"""
    min_page = float('inf')
    min_file = None
    
    for file_path in json_files:
        filename = file_path.name
        # 匹配_page_x_merged.json 模式
        match = re.search(r'_page_(\d+)_merged\.json', filename)
        if match:
            # 修复：直接使用 match.group(1)，去掉多余的 .group
            page_num = int(match.group(1))
            if page_num < min_page:
                min_page = page_num
                min_file = filename
    
    return min_file


def normalize_levels(data: list) -> list:
    """
    检查数据中 level 字段的最小值。
    如果最小值不是 1，则将所有 level 减去 (min_level - 1)，使最小值为 1。
    """
    if not data:
        return data

    # 收集所有存在的 level 值
    levels = []
    for item in data:
        if isinstance(item, dict) and "level" in item:
            val = item["level"]
            if isinstance(val, (int, float)):
                levels.append(int(val))

    if not levels:
        return data

    min_level = min(levels)

    if min_level != 1:
        offset = min_level - 1
        for item in data:
            if isinstance(item, dict) and "level" in item:
                if isinstance(item["level"], (int, float)):
                    item["level"] = int(item["level"]) - offset
    
    return data


def main():
    # 保持原始的环境变量读取逻辑
    input_dir = Path(os.environ.get('CONTENT_POSTPROCESSOR_INPUT', 'input'))
    output_dir = Path(os.environ.get('CONTENT_POSTPROCESSOR_OUTPUT', 'output'))
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # 获取所有 JSON 文件并自然排序
    json_files = sorted(input_dir.glob("*.json"), key=natural_sort_key)
    
    combined_data = []
    book_title = "booktitle"  # 默认书名

    # 找到页码最小的_page_x_merged.json 文件以确定书名
    min_page_file = find_min_page_file(json_files)
    if min_page_file:
        # 需要从完整路径对象中获取文件名进行提取
        target_path = next((f for f in json_files if f.name == min_page_file), None)
        if target_path:
            book_title = extract_book_title(target_path.name)
    else:
        # 如果没找到匹配的文件，从任意一个文件中提取
        for file_path in json_files:
            # 排除干扰文件
            if file_path.name not in ["file_info.json", "combined_output.json"]:
                book_title = extract_book_title(file_path.name)
                break

    # 读取所有 JSON 文件数据
    for file_path in json_files:
        # 【关键修复】显式排除 file_info.json 和可能遗留的 combined_output.json
        # 防止因输入目录被污染而导致数据重复合并
        if file_path.name not in ["file_info.json", "combined_output.json"]:
            data = read_json_file(file_path)
            if data:
                combined_data.extend(data)

    # 【新增功能】归一化标题层级
    combined_data = normalize_levels(combined_data)

    # 直接保存最终结果到输出目录
    final_output_file = output_dir / f"{book_title}_final.json"
    with open(final_output_file, 'w', encoding='utf-8') as f:
        json.dump(combined_data, f, ensure_ascii=False, indent=2)
    
    print(f"处理完成，结果已保存至：{final_output_file}")


if __name__ == "__main__":
    main()