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

# ... (previous imports and classes remain the same)

def merge_results(file1: ProcessedFile, file2: ProcessedFile) -> List[dict]:
    """合并两个文件的处理结果"""
    print(f"\n开始合并文件:")
    print(f"文件1: {file1.original_path.name}")
    print(f"文件2: {file2.original_path.name}")
    
    # 查找重叠部分起始位置
    start_idx1, start_idx2 = find_overlap_indices(file1.items, file2.items)
    if start_idx1 is None or start_idx2 is None:
        print(f"未找到重叠部分！返回文件1的全部内容")
        return [validate_page_number(item) for item in file1.items]
    
    print(f"找到起始重叠点:")
    print(f"文件1起始位置: {start_idx1}, 内容: {file1.items[start_idx1]['text']}")
    print(f"文件2起始位置: {start_idx2}, 内容: {file2.items[start_idx2]['text']}")
    
    # 查找重叠部分终止位置
    end_idx1, end_idx2 = find_end_overlap_indices(file1.items, file2.items)
    
    if end_idx1 is not None and end_idx2 is not None:
        print(f"找到结束重叠点:")
        print(f"文件1结束位置: {end_idx1}, 内容: {file1.items[end_idx1]['text']}")
        print(f"文件2结束位置: {end_idx2}, 内容: {file2.items[end_idx2]['text']}")
    else:
        end_idx1 = len(file1.items)
        end_idx2 = len(file2.items)
        print("未找到结束重叠点，使用文件末尾")
    
    # 合并结果
    merged = []
    
    # 添加第一个文件的前半部分
    front_part = [validate_page_number(item) for item in file1.items[:start_idx1]]
    merged.extend(front_part)
    print(f"\n合并结构:")
    print(f"1. 使用文件1的前半部分: {len(front_part)}条")
    
    # 重叠部分的处理
    overlap_section = []
    for i in range(start_idx1, end_idx1 + 1):  # 包含end_idx1
        item = file1.items[i].copy()
        # 在第二个文件中查找匹配项
        for j in range(start_idx2, end_idx2 + 1):  # 包含end_idx2
            is_match, final_confirmed = check_exact_match(item, file2.items[j])
            if is_match:
                item['confirmed'] = final_confirmed
                break
            elif item['text'] == file2.items[j]['text']:
                item['confirmed'] = False
                break
        item = validate_page_number(item)
        overlap_section.append(item)
    merged.extend(overlap_section)
    print(f"2. 重叠部分: {len(overlap_section)}条")
    
    # 添加第二个文件的后半部分
    back_part = [validate_page_number(item) for item in file2.items[end_idx2 + 1:]]
    merged.extend(back_part)
    print(f"3. 使用文件2的后半部分: {len(back_part)}条")
    
    print(f"合并后总条目数: {len(merged)}\n")
    return merged

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

def process_book_results(processed_dir: Path, file_info_path: Path, output_dir: Path):
    """处理一本书的所有结果"""
    # 读取文件信息
    with open(file_info_path, 'r', encoding='utf-8') as f:
        file_info = json.load(f)
    
    # 创建ProcessedFile对象列表
    processed_files: Dict[str, ProcessedFile] = {}
    
    print("\n=== 阶段1：文件加载 ===")
    for original_path_str in file_info.keys():
        original_path = Path(original_path_str)
        processed_path = processed_dir / f"{original_path.stem}_processed.json"
        
        if not processed_path.exists():
            print(f"未找到处理文件: {processed_path}")
            continue
        
        items = read_json_file(processed_path)
        if not items:
            print(f"文件为空: {processed_path}")
            continue
        
        # 改进文件类型判断逻辑
        stem = original_path.stem
        is_auxiliary = '_辅助' in stem
        # 如果文件名中包含两个书名，则为链接文件
        book_name = stem.split('_page_')[0]
        is_combined = stem.count(book_name) > 1
        
        print(f"加载文件: {original_path.stem}")
        print(f"  - 条目数: {len(items)}")
        print(f"  - 类型: {'辅助文件' if is_auxiliary else '链接文件' if is_combined else '基础文件'}")
        
        processed_files[original_path.stem] = ProcessedFile(
            original_path=original_path,
            processed_path=processed_path,
            items=items,
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
                        items=current_result
                    ),
                    merge_sequence[i]
                )

            book_results[book_name] = current_result
            print(f"\n{book_name} 最终条目数: {len(current_result)}")

    # 保存最终结果
    print("\n=== 阶段3：保存结果 ===")
    for book_name, results in book_results.items():
        output_path = output_dir / f"{book_name}_final.json"
        write_json_file(output_path, results)
        print(f"\n书籍: {book_name}")
        print(f"最终条目数: {len(results)}")
        print(f"保存路径: {output_path}")

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