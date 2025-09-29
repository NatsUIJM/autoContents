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
            next(reader)  # 跳过标题行
            
            for row in reader:
                if len(row) >= 3:
                    title, page, level = row[0], int(row[1]), int(row[2])
                    toc_entries.append([level, title, page])
        
        if not toc_entries:
            print(f"CSV文件 '{selected_csv}' 中没有找到有效的目录条目。")
            return
        
        # 修改PDF文件
        try:
            doc = fitz.open(pdf_path)
            # 删除原始目录
            doc.set_toc([])
            
            # 添加新目录
            doc.set_toc(toc_entries)
            
            # 保存为新文件
            output_path = os.path.join(target_dir, f"{pdf_name}_edited.pdf")
            doc.save(output_path)
            doc.close()
            
            print(f"成功创建修改后的PDF文件: {output_path}")
            
        except Exception as e:
            print(f"处理PDF文件时出错: {e}")

if __name__ == "__main__":
    main()