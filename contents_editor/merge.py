import os
import csv
import fitz  # PyMuPDF
import codecs
from pathlib import Path

def normalize_toc_levels(toc_entries):
    """
    规范化 TOC 层级，确保：
    1. 第一个条目 level 为 1
    2. 层级跳跃不超过 1 (例如不能从 1 直接到 3)
    """
    if not toc_entries:
        return []
    
    # 先按页码排序
    toc_entries.sort(key=lambda x: x[2])
    
    normalized = []
    # 栈用于跟踪当前的层级路径，这里简化处理，只确保相对层级合法
    # 更简单的策略：如果当前 level 比上一个 level 大超过 1，则调整为 prev_level + 1
    # 如果第一个 level 不是 1，强制为 1
    
    for i, entry in enumerate(toc_entries):
        level, title, page = entry
        
        if i == 0:
            if level != 1:
                print(f"警告: 第一条目录项 '{title}' (页码 {page}) 层级为 {level}，已强制调整为 1")
                level = 1
        else:
            prev_level = normalized[-1][0]
            # 如果当前层级比上一层级大超过 1，说明中间缺了父级，强制调整为 prev_level + 1
            if level > prev_level + 1:
                print(f"警告: 目录项 '{title}' (页码 {page}) 层级 {level} 跳跃过大 (前一项层级 {prev_level})，已调整为 {prev_level + 1}")
                level = prev_level + 1
            # 如果层级小于 1，强制为 1
            if level < 1:
                level = 1
                
        normalized.append([level, title, page])
        
    return normalized

def main():
    # 获取脚本所在目录
    target_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 检查目标目录是否存在
    if not os.path.exists(target_dir):
        print(f"目录 '{target_dir}' 不存在。")
        return
    
    # 获取目标目录中的所有CSV文件
    csv_files = [f for f in os.listdir(target_dir) if f.endswith('.csv')]
    
    if not csv_files:
        print(f"在 '{target_dir}' 目录中未找到CSV文件。")
        return
    
    selected_csv = None
    if len(csv_files) == 1:
        selected_csv = csv_files[0]
    else:
        print("找到多个CSV文件，请选择一个：")
        for i, csv_file in enumerate(csv_files, 1):
            print(f"{i}. {csv_file}")
        
        while True:
            try:
                choice = int(input("请输入文件编号: "))
                if 1 <= choice <= len(csv_files):
                    selected_csv = csv_files[choice-1]
                    break
                else:
                    print(f"请输入1到{len(csv_files)}之间的数字")
            except ValueError:
                print("请输入有效的数字")
    
    if selected_csv:
        # 提取PDF文件名（不含扩展名）
        pdf_name = os.path.splitext(selected_csv)[0]
        pdf_path = os.path.join(target_dir, f"{pdf_name}.pdf")
        
        if not os.path.exists(pdf_path):
            print(f"未找到对应的PDF文件: {pdf_name}.pdf")
            return
        
        # 读取CSV文件内容（UTF-8 with BOM）
        toc_entries = []
        csv_path = os.path.join(target_dir, selected_csv)
        
        with codecs.open(csv_path, 'r', 'utf-8-sig') as csvfile:
            reader = csv.reader(csvfile)
            header = next(reader)  # 读取标题行
            print(f"CSV标题行: {header}")
            
            for row_num, row in enumerate(reader, start=2):  # 从第2行开始计数
                if len(row) >= 3:
                    try:
                        title, page, level = row[0], int(row[1]), int(row[2])
                        
                        # 验证层级值（通常应该是正整数）
                        if level < 1:
                            print(f"警告: 第{row_num}行的层级值({level})小于1，已调整为1")
                            level = 1
                        
                        toc_entries.append([level, title, page])
                        # 减少输出，避免刷屏，只在出错时详细看
                        # print(f"读取条目: 层级={level}, 标题='{title}', 页码={page}")
                    except ValueError as e:
                        print(f"警告: 第{row_num}行数据格式错误，跳过该行: {row} 错误: {e}")
                else:
                    # 忽略空行或列数不足的行
                    pass 
        
        if not toc_entries:
            print(f"CSV文件 '{selected_csv}' 中没有找到有效的目录条目。")
            return
        
        print(f"\n共读取 {len(toc_entries)} 条目录条目。")
        
        # 规范化层级
        toc_entries = normalize_toc_levels(toc_entries)
        
        print("\n规范化后的前5条目录条目:")
        for i, entry in enumerate(toc_entries[:5]):
            print(f"{i+1}. 层级={entry[0]}, 标题='{entry[1]}', 页码={entry[2]}")
        
        # 修改PDF文件
        try:
            doc = fitz.open(pdf_path)
            print(f"\nPDF总页数: {doc.page_count}")
            
            # 验证页码有效性
            invalid_entries = []
            for i, entry in enumerate(toc_entries):
                level, title, page = entry
                if page < 1 or page > doc.page_count:
                    invalid_entries.append((i, entry))
                    # 只打印前几个无效条目，避免刷屏
                    if len(invalid_entries) <= 5:
                        print(f"警告: 条目'{title}'的页码({page})超出有效范围(1-{doc.page_count})")
            
            if invalid_entries:
                print(f"... 共 {len(invalid_entries)} 个无效页码条目。")
                print("发现无效页码条目，是否继续处理？(y/n): ", end="")
                if input().lower() != 'y':
                    doc.close()
                    return
            
            # 删除原始目录
            doc.set_toc([])
            
            # 添加新目录
            # 此时 toc_entries 已经过规范化，应该符合 fitz 要求
            doc.set_toc(toc_entries)
            
            # 保存为新文件
            output_path = os.path.join(target_dir, f"{pdf_name}_edited.pdf")
            doc.save(output_path)
            doc.close()
            
            print(f"\n成功创建修改后的PDF文件: {output_path}")
            
        except Exception as e:
            print(f"处理PDF文件时出错: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()