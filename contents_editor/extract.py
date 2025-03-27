import os
import csv
import sys
import fitz  # PyMuPDF库
import codecs
import io

def get_pdf_file():
    """获取脚本所在目录下的PDF文件"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_files = [f for f in os.listdir(current_dir) if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        print("当前目录下没有找到PDF文件。")
        sys.exit(1)
    
    if len(pdf_files) == 1:
        return os.path.join(current_dir, pdf_files[0])
    else:
        print("发现多个PDF文件，请选择：")
        for i, file in enumerate(pdf_files, 1):
            print(f"{i}. {file}")
        
        while True:
            try:
                choice = int(input("请输入文件序号: "))
                if 1 <= choice <= len(pdf_files):
                    return os.path.join(current_dir, pdf_files[choice-1])
                else:
                    print(f"请输入1到{len(pdf_files)}之间的数字")
            except ValueError:
                print("请输入有效的数字")

def extract_toc_to_csv(pdf_path):
    """提取PDF的目录并保存为CSV文件"""
    try:
        # 准备CSV文件名
        pdf_filename = os.path.basename(pdf_path)
        csv_filename = os.path.splitext(pdf_filename)[0] + ".csv"
        csv_path = os.path.join(os.path.dirname(pdf_path), csv_filename)
        
        # 检查CSV文件是否已存在
        if os.path.exists(csv_path):
            print(f"错误: CSV文件 '{csv_filename}' 已存在，不进行覆盖。")
            return
            
        doc = fitz.open(pdf_path)
        toc = doc.get_toc()
        
        if not toc:
            print(f"错误: PDF文件 '{os.path.basename(pdf_path)}' 没有目录结构。")
            doc.close()
            return
        
        # 使用 UTF-8 with BOM 编码写入CSV文件
        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow(["标题", "页码", "层级"])
            
            for item in toc:
                level, title, page = item
                csv_writer.writerow([title, page, level])
        
        print(f"已成功将目录保存为 '{csv_filename}'（使用UTF-8 with BOM编码）")
        doc.close()
        
    except Exception as e:
        print(f"提取目录时发生错误: {str(e)}")

def main():
    pdf_path = get_pdf_file()
    print(f"已选择: {os.path.basename(pdf_path)}")
    extract_toc_to_csv(pdf_path)

if __name__ == "__main__":
    main()