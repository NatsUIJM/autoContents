import os
import sys
from datetime import datetime
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import json
import pikepdf

import dotenv
dotenv.load_dotenv()

def process_pdf_with_bookmarks():
    # 确保输出目录存在
    output_dir = os.getenv('PDF_GENERATOR_OUTPUT_1')
    if not output_dir:
        print("错误：未设置环境变量 PDF_GENERATOR_OUTPUT_1")
        return
    os.makedirs(output_dir, exist_ok=True)
    
    input_dir_1 = os.getenv('PDF_GENERATOR_INPUT_1')
    input_dir_2 = os.getenv('PDF_GENERATOR_INPUT_2')
    
    if not input_dir_1 or not input_dir_2:
        print("错误：未设置环境变量 PDF_GENERATOR_INPUT_1 或 PDF_GENERATOR_INPUT_2")
        return

    # 直接查找 PDF_GENERATOR_INPUT_1 下唯一的_final.json 文件
    try:
        json_files = [f for f in os.listdir(input_dir_1) if f.endswith('_final.json')]
    except FileNotFoundError:
        print(f"错误：找不到目录 {input_dir_1}")
        return
    
    if len(json_files) != 1:
        print(f"错误：在 {input_dir_1} 找到了 {len(json_files)} 个_final.json 文件，期望只有 1 个")
        return
        
    filename = json_files[0]
    base_name = filename.replace('_final.json', '')
    
    # 直接查找 PDF_GENERATOR_INPUT_2 下唯一的 pdf 文件
    try:
        pdf_files = [f for f in os.listdir(input_dir_2) if f.endswith('.pdf')]
    except FileNotFoundError:
        print(f"错误：找不到目录 {input_dir_2}")
        return
    
    if len(pdf_files) != 1:
        print(f"错误：在 {input_dir_2} 找到了 {len(pdf_files)} 个 PDF 文件，期望只有 1 个")
        return
    
    pdf_path = os.path.join(input_dir_2, pdf_files[0])
    
    # 直接查找 PDF_GENERATOR_INPUT_2 下唯一的 json 文件（不以_final.json 结尾）
    try:
        info_json_files = [f for f in os.listdir(input_dir_2) if f.endswith('.json') and not f.endswith('_final.json')]
    except FileNotFoundError:
        print(f"错误：找不到目录 {input_dir_2}")
        return
    
    if len(info_json_files) != 1:
        print(f"错误：在 {input_dir_2} 找到了 {len(info_json_files)} 个 info JSON 文件，期望只有 1 个")
        return
    
    info_json_path = os.path.join(input_dir_2, info_json_files[0])
    content_json_path = os.path.join(input_dir_1, filename)
    
    print(f"正在处理 {base_name}...")

    try:
        # 读取 content_start 和 toc_start
        with open(info_json_path, 'r', encoding='utf-8') as f:
            info_data = json.load(f)
        content_start = info_data.get('content_start', 1)
        toc_start = info_data.get('toc_start', 1)
        
        # 读取目录数据
        with open(content_json_path, 'r', encoding='utf-8') as f:
            toc_data = json.load(f)
            
        # 移除 JSON 中可能已存在的 "目录" 项，避免重复
        toc_data = [item for item in toc_data if item.get('text') != '目录']
        
        # 先将所有页码 +1
        for item in toc_data:
            if 'number' in item and isinstance(item['number'], (int, float)):
                item['number'] = item['number'] + 1
        
        # 添加硬编码的"目录"条目，作为第一个 L1 标题
        toc_entry = {
            'text': '目录',
            'number': toc_start,
            'level': 1
        }
        toc_data.insert(0, toc_entry)
        
        # 验证并调整页码，收集有效条目（保留所有有效项，不再删除孤立标题）
        valid_items = []
        for item in toc_data:
            try:
                if item['text'] != '目录':
                    if not isinstance(item['number'], (int, float)):
                        print(f"警告：跳过无效页码的条目 '{item['text']}'")
                        continue
                    # 应用内容起始页偏移
                    item['number'] = item['number'] + content_start - 1
                
                valid_items.append(item)
            except (KeyError, TypeError) as e:
                print(f"警告：跳过格式错误的条目：{str(e)}")
                continue
        
        # 使用 pikepdf 处理 PDF
        pdf = pikepdf.Pdf.open(pdf_path)
        
        # 创建书签结构
        def create_bookmark_tree(items):
            current_l1 = None
            current_l2 = None
            current_l3 = None
            bookmarks = []
            
            for item in items:
                try:
                    # 检查页码是否有效
                    if item['number'] < 1 or item['number'] > len(pdf.pages):
                        print(f"警告：页码 {item['number']} 超出范围 (1-{len(pdf.pages)})，跳过条目 '{item['text']}'")
                        continue
                    
                    bookmark = pikepdf.OutlineItem(item['text'], item['number'] - 1, 'Fit')
                    
                    if item['level'] == 1:
                        current_l1 = bookmark
                        bookmarks.append(bookmark)
                        current_l1.children = []
                        # 重置下级指针
                        current_l2 = None
                        current_l3 = None
                        
                    elif item['level'] == 2:
                        if current_l1 is not None:
                            current_l1.children.append(bookmark)
                            current_l2 = bookmark
                            current_l2.children = []
                            current_l3 = None
                        else:
                            # 降级处理：无 L1 时直接挂根
                            bookmarks.append(bookmark)
                            current_l2 = bookmark
                            current_l2.children = []
                            current_l3 = None
                            
                    elif item['level'] == 3:
                        if current_l2 and current_l1:
                            current_l2.children.append(bookmark)
                            current_l3 = bookmark
                            current_l3.children = []
                        elif current_l1:
                            # 缺少 L2，降级挂到 L1
                            current_l1.children.append(bookmark)
                            current_l3 = bookmark
                            current_l3.children = []
                        else:
                            bookmarks.append(bookmark)
                            
                    elif item['level'] >= 4:
                        if current_l3 and current_l2 and current_l1:
                            current_l3.children.append(bookmark)
                        elif current_l2 and current_l1:
                            current_l2.children.append(bookmark)
                        elif current_l1:
                            current_l1.children.append(bookmark)
                        else:
                            bookmarks.append(bookmark)
                            
                except Exception as e:
                    print(f"警告：创建书签时出错，跳过条目 '{item.get('text', '未知')}': {str(e)}")
                    continue
            
            return bookmarks

        # 清除现有书签
        if '/Outlines' in pdf.Root:
            del pdf.Root.Outlines
            
        # 创建新书签
        bookmarks = create_bookmark_tree(valid_items)
        
        # 将书签添加到 PDF
        if bookmarks:
            with pdf.open_outline() as outline:
                outline.root.extend(bookmarks)
        
        # 添加元数据
        with pdf.open_metadata() as meta:
            meta['xmp:CreatorTool'] = 'autoContents'
            meta['pdf:Producer'] = 'autoContents v2.0'
            meta['xmp:CreateDate'] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            
        # 添加文档信息
        pdf.docinfo = pdf.make_indirect(pikepdf.Dictionary({
            '/Creator': 'autoContents',
            '/Producer': 'autoContents v2.0',
            '/CreationDate': datetime.now().strftime("D:%Y%m%d%H%M%S"),
            '/URL': 'https://github.com/NatsUijm/autoContents',
            '/Comments': '本 PDF 书签由 autoContents 程序生成，感谢您使用本程序！'
        }))
        
        # 保存处理后的 PDF
        output_path = os.path.join(output_dir, f'{base_name}_with_toc.pdf')
        pdf.save(output_path)
        print(f"\n已成功处理 {base_name}")
        print(f"输出文件：{output_path}")
        
    except Exception as e:
        print(f"处理 {base_name} 时出错：{str(e)}")
        import traceback
        print(traceback.format_exc())

if __name__ == '__main__':
    process_pdf_with_bookmarks()