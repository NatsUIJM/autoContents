import os
import json
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass
import logging

@dataclass
class FileInfo:
    path: Path
    items_count: int

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

def read_json_file(file_path: Path) -> List[dict]:
    """读取JSON文件并返回数据"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error reading {file_path}: {str(e)}")
        return []

def write_json_file(file_path: Path, data: List[dict]):
    """写入JSON文件"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, ensure_ascii=False, indent=2, fp=f)
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
            file_infos[file_path] = FileInfo(file_path, len(data))
    
    if not file_infos:
        return {}
    
    # 生成辅助文件
    files_list = list(file_infos.items())
    
    # 处理首页辅助文件
    first_file, first_info = files_list[0]
    first_data = read_json_file(first_info.path)
    if aux_path := generate_auxiliary_file(first_info.path, first_data, first_info.items_count, True):
        file_infos[aux_path] = FileInfo(aux_path, len(read_json_file(aux_path)))
    
    # 处理尾页辅助文件
    last_file, last_info = files_list[-1]
    last_data = read_json_file(last_info.path)
    if aux_path := generate_auxiliary_file(last_info.path, last_data, last_info.items_count, False):
        file_infos[aux_path] = FileInfo(aux_path, len(read_json_file(aux_path)))
    
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

def main():
    setup_logging()
    input_dir = Path("4_initialContentInfo")
    
    # 获取所有JSON文件
    json_files = list(input_dir.glob("*.json"))
    
    # 按书名分组
    books: Dict[str, List[Path]] = {}
    for file_path in sorted(json_files):
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

if __name__ == "__main__":
    main()