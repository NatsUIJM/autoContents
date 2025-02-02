"""
文件名: content_preprocessor.py (原名: 5_1_json_preprocess.py)
功能: 预处理原始JSON内容文件，生成辅助文件和组合文件
"""

import os
import json
from pathlib import Path
from typing import Dict, List
from dataclasses import dataclass
import logging
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
from config.paths import PathConfig


@dataclass
class FileInfo:
    path: Path
    items_count: int

def natural_sort_key(path: Path) -> tuple:
    """自然排序键函数"""
    import re
    # 分割文件名中的数字和非数字部分
    parts = re.split('(\d+)', path.name)
    # 将数字部分转换为整数，非数字部分保持字符串
    result = []
    for part in parts:
        try:
            result.append(int(part))
        except ValueError:
            result.append(part)
    return tuple(result)

def setup_logging():
    # Create logs directory if it doesn't exist
    logs_dir = Path('logs')
    logs_dir.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(logs_dir / 'json_preprocess.log', encoding='utf-8')
        ]
    )

def clean_number_field(value: str) -> int:
    """清理number字段，仅保留数字并转换为整数"""
    if not isinstance(value, str):
        return value
    # 仅保留数字字符
    digits = ''.join(c for c in value if c.isdigit())
    return int(digits) if digits else 0

def clean_text_field(text: str) -> str:
    """清理text字段，处理特殊字符和截断规则"""
    if not isinstance(text, str):
        return text
    
    # 查找 "…" 并截断
    ellipsis_pos = text.find('…')
    if ellipsis_pos != -1:
        text = text[:ellipsis_pos]
    
    # 查找连续的 "·" 或 "." 并截断
    for i in range(len(text) - 1):
        if (text[i] == '·' and text[i+1] == '·') or (text[i] == '.' and text[i+1] == '.'):
            text = text[:i]
            break
    
    return text


def read_json_file(file_path: Path) -> List[dict]:
    """读取JSON文件并返回数据，统一返回列表格式"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 如果是新格式，提取items内容
            if isinstance(data, dict) and "items" in data:
                return data["items"]
            # 如果是旧格式的列表，直接返回
            return data
    except Exception as e:
        logging.error(f"Error reading {file_path}: {str(e)}")
        return []

def remove_items_prefix(file_path: Path):
    """删除JSON文件中的"items": 前缀和最外层的大括号"""
    try:
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 删除"items": 前缀
        content = content.replace('"items": ', '')
        
        # 删除第一行的左大括号和最后一行的右大括号
        lines = content.splitlines()
        if lines:
            # 删除第一行的左大括号
            if lines[0].strip() == '{':
                lines = lines[1:]
            elif lines[0].strip().startswith('{'):
                lines[0] = lines[0].replace('{', '', 1).lstrip()
            
            # 删除最后一行的右大括号
            if lines and lines[-1].strip() == '}':
                lines = lines[:-1]
            elif lines and lines[-1].strip().endswith('}'):
                lines[-1] = lines[-1].rstrip().rstrip('}').rstrip()
            
            # 重新组合内容
            content = '\n'.join(line for line in lines if line.strip())
        
        # 写回文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        logging.info(f"Removed 'items' prefix and braces from: {file_path}")
    except Exception as e:
        logging.error(f"Error processing {file_path}: {str(e)}")

def post_process_all_files(directory: Path):
    """对目录下所有JSON文件进行后处理"""
    for file_path in directory.glob("*.json"):
        if file_path.name != "file_info.json":  # 跳过文件信息JSON
            remove_items_prefix(file_path)

def clean_text_content(data: List[dict]) -> List[dict]:
    """清理JSON数据中text和number字段的内容"""
    for item in data:
        # 清理text字段
        if 'text' in item and isinstance(item['text'], str):
            item['text'] = (clean_text_field(item['text'])
                          .replace(' ', '')
                          .replace('§', '')
                          .replace('¥', '*')
                          .replace('$', '')
                          .replace('+', ''))
        
        # 清理number字段
        if 'number' in item:
            item['number'] = clean_number_field(item['number'])
    
    return data

def transform_data_structure(data: List[dict]) -> dict:
    """将数据结构转换为带items键的字典格式"""
    return {"items": data}

def write_json_file(file_path: Path, data: List[dict]):
    """写入JSON文件并进行后处理"""
    try:
        # 清理数据
        cleaned_data = clean_text_content(data)
        
        # 检查文件是否存在并读取当前内容以检查格式
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                try:
                    current_data = json.load(f)
                    # 如果已经是新格式，只更新items内容
                    if isinstance(current_data, dict) and "items" in current_data:
                        current_data["items"] = cleaned_data
                        transformed_data = current_data
                    else:
                        transformed_data = {"items": cleaned_data}
                except:
                    transformed_data = {"items": cleaned_data}
        else:
            transformed_data = {"items": cleaned_data}
            
        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(transformed_data, ensure_ascii=False, indent=2, fp=f)
    except Exception as e:
        logging.error(f"Error writing {file_path}: {str(e)}")

def get_slice_count(items_count: int) -> int:
    """根据条目数量确定切片数量"""
    if items_count >= 20:
        return items_count // 2
    elif items_count >= 10:
        return 10
    return items_count

def generate_auxiliary_file(
    file_path: Path,
    data: List[dict],
    items_count: int,
    is_first: bool
) -> Path:
    """生成单文件辅助文件"""
    if items_count < 10:
        return None
    
    slice_count = get_slice_count(items_count)
    items = data[:slice_count] if is_first else data[-slice_count:]
    
    aux_path = file_path.parent / f"{file_path.stem}_辅助.json"
    write_json_file(aux_path, items)
    return aux_path

def generate_combined_file(
    file1_path: Path,
    file2_path: Path,
    file1_data: List[dict],
    file2_data: List[dict],
    file1_count: int,
    file2_count: int
) -> Path:
    """生成组合文件"""
    slice1_count = get_slice_count(file1_count)
    slice2_count = get_slice_count(file2_count)
    
    combined_items = (
        file1_data[-slice1_count:] +
        file2_data[:slice2_count]
    )
    
    combined_path = file1_path.parent / f"{file1_path.stem}_{file2_path.stem}.json"
    write_json_file(combined_path, combined_items)
    return combined_path

def process_book_files(files: List[Path]) -> Dict[Path, FileInfo]:
    """处理同一本书的所有文件"""
    file_infos = {}
    
    # 读取所有文件并统计条目数
    for file_path in files:
        data = read_json_file(file_path)
        if data:
            # 使用实际的Path对象作为键
            file_infos[file_path] = FileInfo(file_path, len(data))
    
    if not file_infos:
        return {}
    
    # 生成辅助文件
    files_list = list(file_infos.items())
    
    # 处理首页辅助文件
    first_file, first_info = files_list[0]
    first_data = read_json_file(first_file)  # 注意这里改用first_file而不是path
    if aux_path := generate_auxiliary_file(first_file, first_data, first_info.items_count, True):
        aux_data = read_json_file(aux_path)
        if aux_data:
            file_infos[aux_path] = FileInfo(aux_path, len(aux_data))
    
    # 处理尾页辅助文件
    last_file, last_info = files_list[-1]
    last_data = read_json_file(last_file)  # 注意这里改用last_file而不是path
    if aux_path := generate_auxiliary_file(last_file, last_data, last_info.items_count, False):
        aux_data = read_json_file(aux_path)
        if aux_data:
            file_infos[aux_path] = FileInfo(aux_path, len(aux_data))
    
    # 生成相邻页面的组合文件
    for i in range(len(files_list) - 1):
        file1, info1 = files_list[i]
        file2, info2 = files_list[i + 1]
        
        data1 = read_json_file(info1.path)
        data2 = read_json_file(info2.path)
        
        combined_path = generate_combined_file(
            info1.path, info2.path,
            data1, data2,
            info1.items_count, info2.items_count
        )
        
        file_infos[combined_path] = FileInfo(
            combined_path,
            len(read_json_file(combined_path))
        )
    
    return file_infos

def process_original_files(files: List[Path]):
    """处理原始文件，清理内容并更新格式"""
    for file_path in files:
        data = read_json_file(file_path)
        if data:
            write_json_file(file_path, data)
            logging.info(f"Processed original file: {file_path}")

def main():
    setup_logging()
    
    # 确保输入目录存在
    input_dir = Path(PathConfig.CONTENT_PREPROCESSOR_INPUT)
    os.makedirs(input_dir, exist_ok=True)
    
    # 获取所有JSON文件并使用自然排序
    json_files = sorted(input_dir.glob("*.json"), key=natural_sort_key)
    
    # 首先处理原始文件
    process_original_files(json_files)
    
    # 按书名分组
    books: Dict[str, List[Path]] = {}
    for file_path in json_files:  # 这里不需要再次sorted，因为已经排序过了
        book_name = file_path.name.split('_page_')[0]
        if book_name not in books:
            books[book_name] = []
        books[book_name].append(file_path)
    
    # 处理每本书
    all_files = {}
    for book_name, book_files in books.items():
        logging.info(f"Processing book: {book_name}")
        try:
            book_file_infos = process_book_files(book_files)
            all_files.update(book_file_infos)
        except Exception as e:
            logging.error(f"Error processing book {book_name}: {str(e)}")
            continue
    
    # 输出处理结果统计
    logging.info(f"Total original files: {len(json_files)}")
    logging.info(f"Total files after preprocessing: {len(all_files)}")
    
    # 将文件信息保存到JSON文件中，供后续步骤使用
    file_info_json = {
        str(path): {
            "items_count": info.items_count
        } for path, info in all_files.items()
    }
    
    with open(input_dir / "file_info.json", 'w', encoding='utf-8') as f:
        json.dump(file_info_json, f, ensure_ascii=False, indent=2)
    
    post_process_all_files(input_dir)

if __name__ == "__main__":
    main()