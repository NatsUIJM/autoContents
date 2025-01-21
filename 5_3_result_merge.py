import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging
from dataclasses import dataclass

@dataclass
class ProcessedFile:
    original_path: Path
    processed_path: Path
    items: List[dict]
    is_auxiliary: bool = False
    is_combined: bool = False

def setup_logging():

    logs_dir = Path('logs')
    logs_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler( logs_dir / 'result_merge.log', encoding='utf-8')
        ]
    )

def read_json_file(file_path: Path) -> List[dict]:
    """读取JSON文件并返回数据"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('items', [])
    except Exception as e:
        logging.error(f"Error reading {file_path}: {str(e)}")
        return []

def write_json_file(file_path: Path, data: List[dict]):
    """写入JSON文件"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({"items": data}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Error writing {file_path}: {str(e)}")

def check_exact_match(item1: dict, item2: dict) -> Tuple[bool, bool]:
    """检查两个条目是否匹配，返回是否完全匹配以及最终的confirmed状态"""
    # 检查文本和页码是否匹配
    basic_match = (item1['text'] == item2['text'] and item1['number'] == item2['number'])
    if not basic_match:
        return False, False
    
    # 确定最终的confirmed状态
    # 如果页码为null或个位数，confirmed一定为False
    if (item1['number'] is None or item1['number'] == "null" or 
        (isinstance(item1['number'], (int, str)) and 
         str(item1['number']).isdigit() and 0 <= int(str(item1['number'])) < 10)):
        return True, False
    
    # 否则，只有两者都为True时才为True
    final_confirmed = item1['confirmed'] and item2['confirmed']
    return True, final_confirmed

def check_title_match(item1: dict, item2: dict) -> bool:
    """检查两个条目的标题是否匹配"""
    return item1['text'] == item2['text']

def find_overlap_indices(list1: List[dict], list2: List[dict], start_ratio: float = 1/3) -> Tuple[Optional[int], Optional[int]]:
    """查找两个列表的重叠部分起始索引"""
    start_idx = int(len(list1) * start_ratio)
    
    # 从list1的start_idx开始向后查找
    for i in range(start_idx, len(list1)):
        for j in range(len(list2)):
            if check_exact_match(list1[i], list2[j]):
                return i, j
    
    # 如果没有找到完全匹配，尝试从start_idx开始向后查找标题匹配
    for i in range(start_idx, len(list1)):
        for j in range(len(list2)):
            if check_title_match(list1[i], list2[j]):
                list1[i]['confirmed'] = False  # 标记为不确定
                return i, j
    
    return None, None

def validate_page_number(item: dict) -> dict:
    """验证并调整页码确认状态"""
    item = item.copy()
    # 处理页码为None或"null"字符串的情况
    if item['number'] is None or item['number'] == "null":
        item['confirmed'] = False
    else:
        try:
            # 将页码转换为整数进行比较
            page_num = int(str(item['number']))
            if 0 <= page_num < 10:
                item['confirmed'] = False
        except (ValueError, TypeError):
            # 如果转换失败，标记为不确定
            item['confirmed'] = False
    return item

def merge_results(file1: ProcessedFile, file2: ProcessedFile) -> List[dict]:
    """合并两个文件的处理结果"""
    # 查找重叠部分
    start_idx1, start_idx2 = find_overlap_indices(file1.items, file2.items)
    if start_idx1 is None or start_idx2 is None:
        logging.error(f"No overlap found between {file1.original_path} and {file2.original_path}")
        # 返回第一个文件的结果，但要确保验证页码
        return [validate_page_number(item) for item in file1.items]
    
    # 查找结束索引（从后向前）
    end_idx1, end_idx2 = find_overlap_indices(
        file1.items[start_idx1:], 
        file2.items[start_idx2:],
        start_ratio=2/3
    )
    
    if end_idx1 is not None and end_idx2 is not None:
        end_idx1 += start_idx1
        end_idx2 += start_idx2
    else:
        # 如果找不到结束重叠，使用起始重叠后的所有内容
        end_idx1 = len(file1.items)
        end_idx2 = len(file2.items)
    
    # 合并结果
    merged = []
    # 添加第一个文件的前半部分（验证页码）
    merged.extend(validate_page_number(item) for item in file1.items[:start_idx1])
    
    # 重叠部分的处理
    overlap_section = []
    for i in range(start_idx1, end_idx1):
        item = file1.items[i].copy()
        # 在第二个文件中查找匹配项
        for j in range(start_idx2, end_idx2):
            is_match, final_confirmed = check_exact_match(item, file2.items[j])
            if is_match:
                item['confirmed'] = final_confirmed
                break
            elif item['text'] == file2.items[j]['text']:
                # 如果只有标题匹配，设为false
                item['confirmed'] = False
                break
        # 验证页码
        item = validate_page_number(item)
        overlap_section.append(item)
    merged.extend(overlap_section)
    
    # 添加第二个文件的后半部分（验证页码）
    merged.extend(validate_page_number(item) for item in file2.items[end_idx2:])
    
    return merged

def process_book_results(processed_dir: Path, file_info_path: Path, output_dir: Path):
    """处理一本书的所有结果"""
    # 读取文件信息
    with open(file_info_path, 'r', encoding='utf-8') as f:
        file_info = json.load(f)
    
    # 创建ProcessedFile对象列表
    processed_files: Dict[str, ProcessedFile] = {}
    for original_path_str in file_info.keys():
        original_path = Path(original_path_str)
        processed_path = processed_dir / f"{original_path.stem}_processed.json"
        
        if not processed_path.exists():
            logging.error(f"Processed file not found: {processed_path}")
            continue
        
        items = read_json_file(processed_path)
        if not items:
            continue
        
        processed_files[original_path.stem] = ProcessedFile(
            original_path=original_path,
            processed_path=processed_path,
            items=items,
            is_auxiliary='_辅助' in original_path.stem,
            is_combined='_page_' not in original_path.stem and not '_辅助' in original_path.stem
        )
    
    # 按书名分组处理文件
    book_results: Dict[str, List[dict]] = {}
    for file_stem, processed_file in processed_files.items():
        if processed_file.is_combined or processed_file.is_auxiliary:
            continue
        
        book_name = file_stem.split('_page_')[0]
        if book_name not in book_results:
            # 初始化使用原始文件的结果
            book_results[book_name] = processed_file.items
        
        # 查找并处理相关的辅助文件和组合文件
        for other_stem, other_file in processed_files.items():
            if other_stem.startswith(file_stem) and (other_file.is_auxiliary or other_file.is_combined):
                book_results[book_name] = merge_results(
                    ProcessedFile(
                        original_path=processed_file.original_path,
                        processed_path=processed_file.processed_path,
                        items=book_results[book_name]
                    ),
                    other_file
                )
    
    # 保存最终结果
    for book_name, results in book_results.items():
        output_path = output_dir / f"{book_name}_final.json"
        write_json_file(output_path, results)
        logging.info(f"Saved final results for {book_name}")

def main():
    setup_logging()
    
    # 设置目录路径
    input_dir = Path("4_initialContentInfo")
    processed_dir = Path("4_1_LLMProcessed")
    output_dir = Path("5_processedContentInfo")
    
    # 创建输出目录
    output_dir.mkdir(exist_ok=True)
    
    # 处理结果
    process_book_results(
        processed_dir=processed_dir,
        file_info_path=input_dir / "file_info.json",
        output_dir=output_dir
    )
    
    logging.info("Result merging completed")

if __name__ == "__main__":
    main()