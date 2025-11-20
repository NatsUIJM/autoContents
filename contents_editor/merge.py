import os
import csv
import fitz  # PyMuPDF
import codecs
from pathlib import Path

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
                        print(f"读取条目: 层级={level}, 标题='{title}', 页码={page}")
                    except ValueError as e:
                        print(f"警告: 第{row_num}行数据格式错误，跳过该行: {row} 错误: {e}")
                else:
                    print(f"警告: 第{row_num}行列数不足，跳过该行: {row}")
        
        if not toc_entries:
            print(f"CSV文件 '{selected_csv}' 中没有找到有效的目录条目。")
            return
        
        # 按页码从小到大排序
        print("\n排序前的目录条目:")
        for i, entry in enumerate(toc_entries):
            print(f"{i+1}. 层级={entry[0]}, 标题='{entry[1]}', 页码={entry[2]}")
        
        toc_entries.sort(key=lambda x: x[2])
        
        print("\n排序后的目录条目:")
        for i, entry in enumerate(toc_entries):
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
                    print(f"警告: 条目'{title}'的页码({page})超出有效范围(1-{doc.page_count})")
            
            if invalid_entries:
                print("发现无效页码条目，是否继续处理？(y/n): ", end="")
                if input().lower() != 'y':
                    doc.close()
                    return
            
            # 删除原始目录
            doc.set_toc([])
            
            # 添加新目录
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
