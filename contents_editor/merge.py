import os
import csv
import codecs
from pathlib import Path
import pikepdf

def main():
    # 获取脚本所在目录
    target_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"工作目录: {target_dir}")
    
    # 检查目标目录是否存在
    if not os.path.exists(target_dir):
        print(f"目录 '{target_dir}' 不存在。")
        return
    
    # 获取目标目录中的所有CSV文件
    csv_files = [f for f in os.listdir(target_dir) if f.endswith('.csv')]
    print(f"找到CSV文件: {csv_files}")
    
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
        print(f"选中的CSV文件: {selected_csv}")
        # 提取PDF文件名（不含扩展名）
        pdf_name = os.path.splitext(selected_csv)[0]
        pdf_path = os.path.join(target_dir, f"{pdf_name}.pdf")
        print(f"对应的PDF文件路径: {pdf_path}")
        
        if not os.path.exists(pdf_path):
            print(f"未找到对应的PDF文件: {pdf_name}.pdf")
            return
        
        # 读取CSV文件内容（UTF-8 with BOM）
        toc_entries = []
        csv_path = os.path.join(target_dir, selected_csv)
        print(f"读取CSV文件: {csv_path}")
        
        with codecs.open(csv_path, 'r', 'utf-8-sig') as csvfile:
            reader = csv.reader(csvfile)
            header = next(reader)  # 跳过标题行
            print(f"CSV标题行: {header}")
            
            for i, row in enumerate(reader):
                print(f"读取行 {i+2}: {row}")
                if len(row) >= 3:
                    title, page, level = row[0], int(row[1]), int(row[2])
                    toc_entries.append([level, title, page])
                    print(f"  添加目录项: 级别={level}, 标题={title}, 页面={page}")
                else:
                    print(f"  跳过无效行: {row}")
        
        print(f"总共读取到 {len(toc_entries)} 个目录条目")
        if not toc_entries:
            print(f"CSV文件 '{selected_csv}' 中没有找到有效的目录条目。")
            return
        
        # 显示所有目录条目
        print("目录条目详情:")
        for entry in toc_entries:
            print(f"  级别: {entry[0]}, 标题: {entry[1]}, 页面: {entry[2]}")
        
        # 修改PDF文件
        try:
            print(f"打开PDF文件: {pdf_path}")
            with pikepdf.open(pdf_path) as pdf:
                print(f"PDF总页数: {len(pdf.pages)}")
                
                # 显示原有书签
                print("原有书签:")
                if hasattr(pdf, 'outlines') and pdf.outlines:
                    def print_outline(items, indent=0):
                        for item in items:
                            print("  " * indent + f"- {item.title}")
                            if hasattr(item, 'children') and item.children:
                                print_outline(item.children, indent + 1)
                    print_outline(pdf.outlines)
                else:
                    print("  无原有书签")
                
                # 构建新的书签结构（正确处理层级嵌套）
                print("构建新书签结构...")
                outline_items = []
                level_stack = [outline_items]  # 栈用于跟踪当前层级
                
                for level, title, page in toc_entries:
                    print(f"  创建书签: 级别={level}, 标题={title}, 页面={page}")
                    if page <= len(pdf.pages):
                        page_obj = pdf.pages[page - 1]  # pikepdf使用0基页码
                        outline_item = pikepdf.OutlineItem(title, page_obj)
                        
                        # 调整层级栈以匹配当前级别
                        while len(level_stack) > level:
                            level_stack.pop()
                        while len(level_stack) < level:
                            # 如果需要更深层级，创建一个临时列表
                            level_stack.append([])
                        
                        # 将当前项添加到适当的父级
                        if level == 1:
                            outline_items.append(outline_item)
                        else:
                            # 确保父级有children属性
                            parent = level_stack[level-2][-1]  # 父级是上一级的最后一项
                            if not hasattr(parent, 'children'):
                                parent.children = []
                            parent.children.append(outline_item)
                        
                        # 更新层级栈
                        if len(level_stack) <= level:
                            level_stack.append([outline_item])
                        else:
                            level_stack[level-1].append(outline_item)
                    else:
                        print(f"    警告: 页面 {page} 超出PDF范围 ({len(pdf.pages)} 页)")
                
                # 设置PDF的书签
                pdf.outlines = outline_items
                print(f"新书签已设置")

                # 保存为新文件
                output_path = os.path.join(target_dir, f"{pdf_name}_edited.pdf")
                print(f"保存PDF到: {output_path}")
                pdf.save(output_path)
                print("PDF保存完成")

            print(f"成功创建修改后的PDF文件: {output_path}")
            
        except Exception as e:
            print(f"处理PDF文件时出错: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()
