"""
文件名: result_merger.py (原名: 5_3_result_merge.py)
功能: 合并和处理LLM处理后的内容结果
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging
from dataclasses import dataclass
import os
from config.paths import PathConfig
import re

@dataclass
class ProcessedFile:
    original_path: Path
    processed_path: Path
    backup_path: Optional[Path]
    items: List[dict]
    backup_items: Optional[List[dict]] = None
    is_auxiliary: bool = False
    is_combined: bool = False

    def __post_init__(self):
        """初始化后检查并处理模型错误"""
        if check_model_error(self.items):
            if self.backup_items:
                # 如果主文件有错误且存在备用文件，则交换
                self.items, self.backup_items = self.backup_items, self.items
                print(f"检测到模型错误，切换到备用结果: {self.processed_path}")

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

def standardize_text(text: str) -> str:
    """标准化文本:
    1. 处理空值情况
    2. 只保留中文、英文字母和数字
    3. 移除所有空格
    """
    if text is None or text == "null":
        return ""
    # 使用正则表达式只保留中文、英文字母和数字
    text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text)
    # 移除所有空格
    return ''.join(text.split())

def find_duplicate_titles(files: List[ProcessedFile]) -> Dict[str, int]:
    """查找所有文件中重复出现的标题及其出现次数（忽略空格）"""
    title_count = {}
    # 收集所有标题的出现次数
    for file in files:
        for item in file.items:
            # 跳过无效条目
            if (item.get('text') is None or item.get('text') == "null") and \
               (item.get('number') is None or item.get('number') == "null"):
                continue
                
            title = standardize_text(item['text'])
            if title:  # 只处理非空标题
                title_count[title] = title_count.get(title, 0) + 1
            
    # 只保留重复出现的标题
    return {title: count for title, count in title_count.items() if count > 2}


def validate_context_match(list1: List[dict], list2: List[dict], idx1: int, idx2: int) -> bool:
    """验证两个位置的上下文是否匹配（忽略空格）"""
    matches = 0
    total_checks = 0
    
    # 检查前两条
    for offset in [-2, -1]:
        pos1 = idx1 + offset
        pos2 = idx2 + offset
        if pos1 >= 0 and pos2 >= 0:
            total_checks += 1
            if standardize_text(list1[pos1]['text']) == standardize_text(list2[pos2]['text']):
                matches += 1

    # 检查后两条
    for offset in [1, 2]:
        pos1 = idx1 + offset
        pos2 = idx2 + offset
        if pos1 < len(list1) and pos2 < len(list2):
            total_checks += 1
            if standardize_text(list1[pos1]['text']) == standardize_text(list2[pos2]['text']):
                matches += 1
    
    # 如果能检查的上下文太少（比如在文件开头或结尾），降低匹配要求
    if total_checks <= 2:
        return matches >= 1
    
    return matches >= 3
def find_reliable_overlap_indices(list1: List[dict], list2: List[dict], 
                                duplicate_titles: Dict[str, int]) -> Tuple[Optional[int], Optional[int]]:
    """查找可靠的重叠起始点"""
    for i in range(len(list1)):
        title1 = list1[i]['text']
        # 跳过重复标题
        if title1 in duplicate_titles:
            continue
            
        for j in range(len(list2)):
            if check_exact_match(list1[i], list2[j])[0]:
                return i, j
            
            # 如果找到标题匹配但页码不匹配，验证上下文
            if (title1 == list2[j]['text'] and 
                validate_context_match(list1, list2, i, j)):
                list1[i]['confirmed'] = False
                return i, j
    
    return None, None

def find_reliable_end_overlap_indices(list1: List[dict], list2: List[dict], 
                                    duplicate_titles: Dict[str, int]) -> Tuple[Optional[int], Optional[int]]:
    """从后向前查找可靠的重叠终止点"""
    for i in range(len(list1) - 1, -1, -1):
        title1 = list1[i]['text']
        # 跳过重复标题
        if title1 in duplicate_titles:
            continue
            
        for j in range(len(list2) - 1, -1, -1):
            if check_exact_match(list1[i], list2[j])[0]:
                return i, j
            
            # 如果找到标题匹配但页码不匹配，验证上下文
            if (title1 == list2[j]['text'] and 
                validate_context_match(list1, list2, i, j)):
                list1[i]['confirmed'] = False
                return i, j
    
    return None, None

def check_model_error(items: List[dict]) -> bool:
    """检查是否存在模型错误"""
    if not items:
        return True
        
    # 检查第一个错误类型：以"模型错误，错误码"开头
    first_text = items[0].get('text', '')
    if first_text.startswith('模型错误，错误码'):
        return True
        
    # 检查第二个错误类型：四个字段分别为'i', 't', 'e', 'm'
    if len(items) >= 4:
        error_pattern = ['i', 't', 'e', 'm']
        for i, expected in enumerate(error_pattern):
            if i >= len(items):
                break
            if items[i].get('text', '') == expected:
                # 如果找到一个匹配，继续检查后续项
                continue
            # 如果有不匹配，说明不是这种错误
            break
        else:
            # 如果所有项都匹配，说明是这种错误
            return True
            
    return False

def read_json_file(file_path: Path) -> List[dict]:
    """读取JSON文件并返回数据"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            items = data.get('items', [])
            
            # 检查是否为空列表
            if not items:
                logging.warning(f"文件为空: {file_path}")
                return []
            
            return items
            
    except json.JSONDecodeError as e:
        logging.error(f"JSON解析错误 {file_path}: {str(e)}")
        return []
    except FileNotFoundError:
        logging.error(f"文件不存在: {file_path}")
        return []
    except Exception as e:
        logging.error(f"读取文件时发生错误 {file_path}: {str(e)}")
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
    # 检查文本(忽略空格)和页码是否匹配
    basic_match = (standardize_text(item1['text']) == standardize_text(item2['text']) and 
                  item1['number'] == item2['number'])
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
    """检查两个条目的标题是否匹配（忽略空格）"""
    return standardize_text(item1['text']) == standardize_text(item2['text'])

def find_overlap_indices(list1: List[dict], list2: List[dict]) -> Tuple[Optional[int], Optional[int]]:
    """从前向后查找两个列表的重叠部分起始索引"""
    # 从list1的第一条开始向后查找
    for i in range(len(list1)):
        for j in range(len(list2)):
            if check_exact_match(list1[i], list2[j])[0]:
                return i, j
    
    # 如果没有找到完全匹配，尝试从第一条开始查找标题匹配
    for i in range(len(list1)):
        for j in range(len(list2)):
            if check_title_match(list1[i], list2[j]):
                list1[i]['confirmed'] = False  # 标记为不确定
                return i, j
    
    return None, None
def find_end_overlap_indices(list1: List[dict], list2: List[dict]) -> Tuple[Optional[int], Optional[int]]:
    """从后向前查找两个列表的重叠部分终止索引"""
    # 从list1的最后一条开始向前查找
    for i in range(len(list1) - 1, -1, -1):
        for j in range(len(list2) - 1, -1, -1):
            if check_exact_match(list1[i], list2[j])[0]:
                return i, j
    
    # 如果没有找到完全匹配，尝试从最后一条开始向前查找标题匹配
    for i in range(len(list1) - 1, -1, -1):
        for j in range(len(list2) - 1, -1, -1):
            if check_title_match(list1[i], list2[j]):
                list1[i]['confirmed'] = False  # 标记为不确定
                return i, j
    
    return None, None
def validate_page_number(item: dict) -> dict:
    """验证并调整页码确认状态"""
    item = item.copy()
    # 只处理页码为None或"null"字符串的情况
    if item['number'] is None or item['number'] == "null":
        item['confirmed'] = False
    return item

# ... (previous imports and classes remain the same)

def determine_confirmation_status(item1: dict, item2: dict, 
                                list1: List[dict], list2: List[dict], 
                                idx1: int, idx2: int,
                                duplicate_titles: Dict[str, int]) -> bool:
    """确定两个匹配项的确认状态"""
    # 如果页码为null，confirmed一定为False
    if (item1['number'] is None or item1['number'] == "null"):
        return False
    
    # 如果不是重复标题，使用原有逻辑
    if item1['text'] not in duplicate_titles:
        return item1['confirmed'] and item2['confirmed']
    
    # 对于重复标题，进行严格的上下文验证
    matches = 0
    total_checks = 0
    
    # 检查前两条和后两条
    for offset in [-2, -1, 1, 2]:
        pos1 = idx1 + offset
        pos2 = idx2 + offset
        if 0 <= pos1 < len(list1) and 0 <= pos2 < len(list2):
            total_checks += 1
            if (standardize_text(list1[pos1]['text']) == standardize_text(list2[pos2]['text']) and 
                list1[pos1].get('number') == list2[pos2].get('number')):
                matches += 1

    
    # 如果在文件边界，降低要求
    min_required_matches = 3 if total_checks >= 4 else (2 if total_checks >= 3 else 1)
    
    # 只有在以下所有条件都满足时，才返回True：
    # 1. 足够的上下文匹配
    # 2. 两个条目的页码完全相同
    # 3. 两个条目原本都是confirmed状态
    return (matches >= min_required_matches and 
            item1.get('number') == item2.get('number') and 
            item1['confirmed'] and item2['confirmed'])

def merge_results(file1: ProcessedFile, file2: ProcessedFile) -> List[dict]:
    """改进后的合并函数 - 支持备用数据"""
    print(f"\n开始合并文件:")
    print(f"文件1: {file1.original_path.name}")
    print(f"文件2: {file2.original_path.name}")
    
    def try_merge_with_items(items1: List[dict], items2: List[dict], 
                           is_backup: bool = False) -> Tuple[List[dict], bool]:
        """尝试使用给定的两组数据进行合并"""
        # 预处理：过滤掉无效条目
        items1 = [item for item in items1 
                if not ((item.get('text') is None or item.get('text') == "null") and 
                       (item.get('number') is None or item.get('number') == "null"))]
        items2 = [item for item in items2 
                if not ((item.get('text') is None or item.get('text') == "null") and 
                       (item.get('number') is None or item.get('number') == "null"))]
        
        # 查找重复标题
        duplicate_titles = find_duplicate_titles([
            ProcessedFile(file1.original_path, file1.processed_path, None, items1),
            ProcessedFile(file2.original_path, file2.processed_path, None, items2)
        ])
        
        # 查找可靠的重叠部分起始位置
        start_idx1, start_idx2 = find_reliable_overlap_indices(items1, items2, duplicate_titles)
        if start_idx1 is None or start_idx2 is None:
            if is_backup:
                print(f"备用数据也未找到可靠的重叠起始点！")
            return None, False
        
        # 查找可靠的重叠部分终止位置
        end_idx1, end_idx2 = find_reliable_end_overlap_indices(items1, items2, duplicate_titles)
        if end_idx1 is None or end_idx2 is None:
            end_idx1 = len(items1)
            end_idx2 = len(items2)
        
        # 合并结果
        merged = []
        
        # 添加第一个文件的前半部分
        merged.extend([validate_page_number(item) for item in items1[:start_idx1]])
        
        # 处理重叠部分
        for i in range(start_idx1, end_idx1 + 1):
            item = items1[i].copy()
            matched = False
            
            # 在第二个文件中查找匹配项
            for j in range(start_idx2, end_idx2 + 1):
                if item['text'] == items2[j]['text']:  # Changed from file2_items to file2.items
                    # 确定确认状态
                    confirmed = determine_confirmation_status(
                        item, items2[j],  # Changed from file2_items to file2.items
                        items1, items2,  # Changed from file2_items to file2.items
                        i, j,
                        duplicate_titles
                    )
                    item['confirmed'] = confirmed
                    matched = True
                    break
            
            if not matched and item['text'] in duplicate_titles:
                item['confirmed'] = False
            
            merged.append(validate_page_number(item))
        
        # 添加第二个文件的后半部分
        merged.extend([validate_page_number(item) for item in items2[end_idx2 + 1:]])  # Changed from file2_items to file2.items
        
        return merged, True

    # 首先尝试使用主数据合并
    merged_results, success = try_merge_with_items(file1.items, file2.items)
    
    # 如果主数据合并失败，尝试使用备用数据
    if not success:
        print(f"\n主数据合并失败，尝试使用备用数据...")
        
        # 尝试不同的备用数据组合
        backup_combinations = [
            (file1.backup_items, file2.items),  # 文件1使用备用
            (file1.items, file2.backup_items),  # 文件2使用备用
            (file1.backup_items, file2.backup_items)  # 都使用备用
        ]
        
        for items1, items2 in backup_combinations:
            if items1 is None or items2 is None:
                continue
                
            merged_results, success = try_merge_with_items(items1, items2, True)
            if success:
                print(f"使用备用数据合并成功")
                break
        
    if not success:
        print(f"所有合并尝试均失败！返回文件1的全部内容")
        return [validate_page_number(item) for item in file1.items]
        
    return merged_results

def get_page_number(file_path: Path) -> int:
    """从文件名中提取页码"""
    parts = file_path.stem.split('_page_')
    if len(parts) < 2:
        return 0
    # 只取第一个数字
    page_str = parts[1].split('_')[0]
    try:
        return int(page_str)
    except ValueError:
        return 0

def post_process_confirmation_status(merged_results: List[dict], 
                                   processed_files: List[ProcessedFile],
                                   duplicate_titles: Dict[str, int]) -> List[dict]:
    """后处理函数，修正重复标题的确认状态"""
    # 深拷贝结果以避免修改原始数据
    results = [item.copy() for item in merged_results]
    
    # 遍历所有需要检查的条目
    for i, item in enumerate(results):
        # 只处理被标记为false且属于重复标题的条目
        if not item['confirmed'] and item['text'] in duplicate_titles:
            matching_items = []
            
            # 在所有分页文件中查找匹配项
            for processed_file in processed_files:
                for source_item in processed_file.items:
                    # 检查标题和页码是否完全匹配
                    if (source_item['text'] == item['text'] and 
                        source_item['number'] == item['number'] and 
                        source_item['confirmed']):
                        matching_items.append(source_item)
            
            # 如果找到两个或以上的确认匹配项，将状态改为true
            if len(matching_items) >= 2:
                print(f"修正确认状态: {item['text']} (页码: {item['number']}) - 找到 {len(matching_items)} 个匹配项")
                results[i]['confirmed'] = True
    
    return results

def interpolate_null_numbers(results: List[dict], duplicate_titles: Dict[str, int]) -> List[dict]:
    """为重复标题中number为null的条目插值，并标记为未确认"""
    processed_results = [item.copy() for item in results]
    
    for i in range(len(processed_results)):
        item = processed_results[i]
        
        # 只处理number为null且属于重复标题的条目
        if (item['number'] is None or item['number'] == "null") and item['text'] in duplicate_titles:
            prev_number = None
            next_number = None
            
            # 向前查找最近的有效页码
            for j in range(i-1, -1, -1):
                if (processed_results[j]['number'] is not None and 
                    processed_results[j]['number'] != "null" and
                    str(processed_results[j]['number']).isdigit()):
                    prev_number = int(str(processed_results[j]['number']))
                    break
            
            # 向后查找最近的有效页码
            for j in range(i+1, len(processed_results)):
                if (processed_results[j]['number'] is not None and 
                    processed_results[j]['number'] != "null" and
                    str(processed_results[j]['number']).isdigit()):
                    next_number = int(str(processed_results[j]['number']))
                    break
            
            # 计算插值并标记为未确认
            if prev_number is not None and next_number is not None:
                interpolated_number = (prev_number + next_number) // 2
                print(f"插值处理: {item['text']} - 前:{prev_number} 后:{next_number} 插值:{interpolated_number}")
                processed_results[i]['number'] = interpolated_number
                processed_results[i]['confirmed'] = False
            elif prev_number is not None:
                processed_results[i]['number'] = prev_number
                processed_results[i]['confirmed'] = False
                print(f"插值处理: {item['text']} - 使用前值:{prev_number}")
            elif next_number is not None:
                processed_results[i]['number'] = next_number
                processed_results[i]['confirmed'] = False
                print(f"插值处理: {item['text']} - 使用后值:{next_number}")
    
    return processed_results

def final_post_process(results: List[dict]) -> List[dict]:
    """
    最终的后处理步骤:
    1. 如果level的最小值不为1，将所有level减少到从1开始
    2. 删除所有level >= 4的标题
    """
    if not results:
        return results
    
    # 找到最小level
    min_level = min(item['level'] for item in results)
    
    # 如果最小level不为1，调整所有level
    if min_level != 1:
        print(f"\n检测到最小level为{min_level}，将所有level减{min_level-1}")
        results = [{**item, 'level': item['level'] - (min_level-1)} for item in results]
    
    # 过滤掉level >= 4的标题
    original_count = len(results)
    results = [item for item in results if item['level'] < 4]
    filtered_count = original_count - len(results)
    if filtered_count > 0:
        print(f"\n删除了{filtered_count}个level >= 4的标题")
    
    return results

def process_book_results(processed_dir: Path, file_info_path: Path, output_dir: Path):
    """处理一本书的所有结果"""
    # 读取文件信息
    with open(file_info_path, 'r', encoding='utf-8') as f:
        file_info = json.load(f)
    
    # 创建ProcessedFile对象列表
    processed_files: Dict[str, ProcessedFile] = {}

    def get_backup_path(processed_path: Path) -> Optional[Path]:
        """根据deepseek处理文件路径获取dashscope备用文件路径"""
        if '_deepseek_processed' not in processed_path.stem:
            return None
        return processed_path.parent / f"{processed_path.stem.replace('_deepseek_', '_dashscope_')}.json"

    print("\n=== 阶段1：文件加载 ===")
    for original_path_str in file_info.keys():
        original_path = Path(original_path_str)
        # 查找deepseek处理文件
        processed_path = processed_dir / f"{original_path.stem}_deepseek_processed.json"
        backup_path = get_backup_path(processed_path)
        
        if not processed_path.exists():
            print(f"未找到主处理文件: {processed_path}")
            continue
        
        items = read_json_file(processed_path)
        backup_items = None
        if backup_path and backup_path.exists():
            backup_items = read_json_file(backup_path)
        
        # 检查主文件是否有模型错误
        if check_model_error(items):
            if backup_items:
                print(f"检测到模型错误，使用备用文件: {backup_path}")
                items, backup_items = backup_items, items
            else:
                print(f"警告：检测到模型错误但没有可用的备用文件: {processed_path}")
        
        if not items and not backup_items:
            print(f"主文件和备用文件均为空: {processed_path}")
            continue
        
        # 改进文件类型判断逻辑
        stem = original_path.stem
        is_auxiliary = '_辅助' in stem
        # 如果文件名中包含两个书名，则为链接文件
        book_name = stem.split('_page_')[0]
        is_combined = stem.count(book_name) > 1
        
        print(f"加载文件: {original_path.stem}")
        print(f"  - 主数据条目数: {len(items)}")
        if backup_items:
            print(f"  - 备用数据条目数: {len(backup_items)}")
        print(f"  - 类型: {'辅助文件' if is_auxiliary else '链接文件' if is_combined else '基础文件'}")
        
        processed_files[original_path.stem] = ProcessedFile(
            original_path=original_path,
            processed_path=processed_path,
            backup_path=backup_path,
            items=items,
            backup_items=backup_items,
            is_auxiliary=is_auxiliary,
            is_combined=is_combined
        )

    # ... 后续代码保持不变 ...

    print("\n=== 阶段2：按书籍分组 ===")
    book_results: Dict[str, List[dict]] = {}
    
    # 按书名整理文件
    book_files: Dict[str, List[ProcessedFile]] = {}
    for file_stem, processed_file in processed_files.items():
        if processed_file.is_combined:  # 跳过链接文件
            continue
        book_name = file_stem.split('_page_')[0]
        if book_name not in book_files:
            book_files[book_name] = []
        book_files[book_name].append(processed_file)

    # 处理每本书
    for book_name, files in book_files.items():
        print(f"\n开始处理书籍: {book_name}")
        
        # 1. 分类文件
        base_files = []
        auxiliary_files = []
        link_files = []
        
        for file_stem, processed_file in processed_files.items():
            if book_name not in file_stem:
                continue
                
            if processed_file.is_auxiliary:
                auxiliary_files.append(processed_file)
            elif processed_file.is_combined:
                link_files.append(processed_file)
            elif '_page_' in file_stem:
                base_files.append(processed_file)
        
        # 按页码排序基础文件
        base_files.sort(key=lambda x: get_page_number(x.original_path))
        
        print("\n基础文件:")
        for f in base_files:
            print(f"  - {f.original_path.stem}")
        
        print("\n辅助文件:")
        for f in auxiliary_files:
            print(f"  - {f.original_path.stem}")
            
        print("\n链接文件:")
        for f in link_files:
            print(f"  - {f.original_path.stem}")

        # 2. 构建合并序列
        merge_sequence = []
        
        # 检查第一个基础文件是否有辅助文件
        first_base = base_files[0]
        first_aux_stem = f"{first_base.original_path.stem}_辅助"
        for aux in auxiliary_files:
            if aux.original_path.stem == first_aux_stem:
                merge_sequence.append(aux)
                print(f"\n添加第一个基础文件的辅助文件: {aux.original_path.stem}")
                break
        
        # 处理基础文件和链接文件
        for i in range(len(base_files)):
            merge_sequence.append(base_files[i])
            print(f"\n添加基础文件: {base_files[i].original_path.stem}")
            
            if i < len(base_files) - 1:
                # 查找链接文件
                current_stem = base_files[i].original_path.stem
                next_stem = base_files[i + 1].original_path.stem
                link_stem = f"{current_stem}_{next_stem}"
                
                for link in link_files:
                    if link.original_path.stem == link_stem:
                        merge_sequence.append(link)
                        print(f"添加链接文件: {link.original_path.stem}")
                        break
        
        # 检查最后一个基础文件是否有辅助文件
        last_base = base_files[-1]
        last_aux_stem = f"{last_base.original_path.stem}_辅助"
        for aux in auxiliary_files:
            if aux.original_path.stem == last_aux_stem:
                merge_sequence.append(aux)
                print(f"\n添加最后一个基础文件的辅助文件: {aux.original_path.stem}")
                break

        print("\n最终合并序列:")
        for f in merge_sequence:
            print(f"  - {f.original_path.stem}")
        
        # 3. 执行合并
        if merge_sequence:
            current_result = merge_sequence[0].items
            for i in range(1, len(merge_sequence)):
                current_result = merge_results(
                    ProcessedFile(
                        original_path=merge_sequence[i-1].original_path,
                        processed_path=merge_sequence[i-1].processed_path,
                        backup_path=None,
                        items=current_result
                    ),
                    merge_sequence[i]
                )

            book_results[book_name] = current_result
            print(f"\n{book_name} 最终条目数: {len(current_result)}")

    print("\n=== 阶段3：保存结果 ===")
    for book_name, results in book_results.items():
        # 首先过滤results
        results = [item for item in results 
                  if not ((item.get('text') is None or item.get('text') == "null") and 
                         (item.get('number') is None or item.get('number') == "null"))]
        
        # 获取这本书的所有分页文件
        book_files = [
            processed_file for processed_file in processed_files.values()
            if book_name in processed_file.original_path.stem and not processed_file.is_combined
        ]
        
        # 查找重复标题
        duplicate_titles = {}
        for processed_file in book_files:
            for item in processed_file.items:
                if ((item.get('text') is None or item.get('text') == "null") and 
                    (item.get('number') is None or item.get('number') == "null")):
                    continue
                title = standardize_text(item.get('text', ''))
                if title:
                    duplicate_titles[title] = duplicate_titles.get(title, 0) + 1
        duplicate_titles = {title: count for title, count in duplicate_titles.items() 
                          if count > 2}
        
        print("\n处理空页码的重复标题...")
        # 先进行页码插值
        results_with_numbers = interpolate_null_numbers(results, duplicate_titles)
        
        print("\n修正确认状态...")
        # 进行确认状态的修正
        results_with_confirmation = post_process_confirmation_status(
            results_with_numbers, book_files, duplicate_titles)
        
        print("\n进行最终后处理...")
        # 进行最终的后处理
        final_results = final_post_process(results_with_confirmation)
        
        # 最后一次过滤，确保没有无效条目
        final_results = [item for item in final_results 
                        if not ((item.get('text') is None or item.get('text') == "null") and 
                               (item.get('number') is None or item.get('number') == "null"))]
        
        output_path = output_dir / f"{book_name}_final.json"
        write_json_file(output_path, final_results)
        
        output_path = output_dir / f"{book_name}_final.json"
        write_json_file(output_path, final_results)
        print(f"\n书籍: {book_name}")
        print(f"最终条目数: {len(final_results)}")
        print(f"保存路径: {output_path}")
        
        # 输出统计信息
        original_null_numbers = sum(1 for item in results 
                                if (item['number'] is None or item['number'] == "null") 
                                and item['text'] in duplicate_titles)
        final_null_numbers = sum(1 for item in final_results 
                            if (item['number'] is None or item['number'] == "null") 
                            and item['text'] in duplicate_titles)
        
        original_confirmed = sum(1 for item in results if item['confirmed'])
        final_confirmed = sum(1 for item in final_results if item['confirmed'])
        
        level_distribution = {}
        for item in final_results:
            level = item['level']
            level_distribution[level] = level_distribution.get(level, 0) + 1
        
        print(f"\n统计信息:")
        print(f"页码处理:")
        print(f"  - 原始空页码数: {original_null_numbers}")
        print(f"  - 最终空页码数: {final_null_numbers}")
        print(f"确认状态:")
        print(f"  - 处理前确认条目数: {original_confirmed}")
        print(f"  - 处理后确认条目数: {final_confirmed}")
        print(f"  - 修正条目数: {final_confirmed - original_confirmed}")
        print(f"层级分布:")
        for level in sorted(level_distribution.keys()):
            print(f"  - Level {level}: {level_distribution[level]}条")


def main():
    # 设置日志
    logs_dir = Path(PathConfig.RESULT_MERGER_LOGS)
    logs_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(logs_dir / 'result_merge.log', encoding='utf-8')
        ]
    )
    
    # 设置输入输出目录路径
    input_dir = Path(PathConfig.RESULT_MERGER_INPUT_RAW)
    processed_dir = Path(PathConfig.RESULT_MERGER_INPUT_LLM)
    output_dir = Path(PathConfig.RESULT_MERGER_OUTPUT)
    
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 处理结果
    process_book_results(
        processed_dir=processed_dir,
        file_info_path=input_dir / "file_info.json",
        output_dir=output_dir
    )
    
    logging.info("Result merging completed")

if __name__ == "__main__":
    main()