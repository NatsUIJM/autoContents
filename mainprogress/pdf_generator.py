import os
import sys
from datetime import datetime
import re
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import json
import pikepdf

import dotenv
dotenv.load_dotenv()

def replace_filename_placeholders(template, original_filename, toc_start=None, toc_end=None):
    """
    替换文件名中的占位符
    :param template: 文件名模板，如 "%name-toc_%date"
    :param original_filename: 原始文件名
    :param toc_start: 目录起始页
    :param toc_end: 目录结束页
    :return: 替换后的文件名（不含扩展名）
    """
    # 获取不带扩展名的文件名
    name_without_ext = os.path.splitext(original_filename)[0]
    
    # 替换占位符
    result = template.replace('%name', name_without_ext)
    result = result.replace('%date', datetime.now().strftime("%Y%m%d_%H%M%S"))
    
    # 处理%range 占位符
    if toc_start is not None and toc_end is not None:
        range_str = f"{toc_start}-{toc_end}"
        result = result.replace('%range', range_str)
    else:
        # 如果没有页数范围，移除%range 占位符
        result = result.replace('%range', '')
    
    # 清理非法字符
    invalid_chars = '<>:"/\\|？*'
    for char in invalid_chars:
        result = result.replace(char, '_')
    
    return result

def should_remove_item(text, toc_structure):
    """
    根据toc_structure规则判断是否应该删除该书签项
    """
    if toc_structure == "original":
        return False
    elif toc_structure == "ignore_xxx":
        # 匹配 ^[0-9]+\.[0-9]+\.[0-9]+.* 或 ^[0-9]+-[0-9]+-[0-9]+.*
        pattern1 = r'^[0-9]+\.[0-9]+\.[0-9]+.*'
        pattern2 = r'^[0-9]+-[0-9]+-[0-9]+.*'
        return bool(re.match(pattern1, text)) or bool(re.match(pattern2, text))
    elif toc_structure == "ignore_xxxx":
        # 匹配 ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+.* 或 ^[0-9]+-[0-9]+-[0-9]+-[0-9]+.*
        pattern1 = r'^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+.*'
        pattern2 = r'^[0-9]+-[0-9]+-[0-9]+-[0-9]+.*'
        return bool(re.match(pattern1, text)) or bool(re.match(pattern2, text))
    return False

def process_pdf_with_bookmarks():
    # 确保输出目录存在
    os.makedirs(os.getenv('PDF_GENERATOR_OUTPUT_1'), exist_ok=True)
    
    # 直接查找PDF_GENERATOR_INPUT_1下唯一的_final.json文件
    json_files = [f for f in os.listdir(os.getenv('PDF_GENERATOR_INPUT_1')) if f.endswith('_final.json')]
    
    if len(json_files) != 1:
        print(f"错误: 找到了 {len(json_files)} 个_final.json文件，期望只有1个")
        return
        
    filename = json_files[0]
    base_name = filename.replace('_final.json', '')
    
    # 直接查找PDF_GENERATOR_INPUT_2下唯一的pdf文件
    pdf_files = [f for f in os.listdir(os.getenv('PDF_GENERATOR_INPUT_2')) if f.endswith('.pdf')]
    
    if len(pdf_files) != 1:
        print(f"错误: 找到了 {len(pdf_files)} 个PDF文件，期望只有1个")
        return
    
    pdf_path = os.path.join(os.getenv('PDF_GENERATOR_INPUT_2'), pdf_files[0])
    
    # 直接查找PDF_GENERATOR_INPUT_2下唯一的json文件（不以_final.json结尾）
    info_json_files = [f for f in os.listdir(os.getenv('PDF_GENERATOR_INPUT_2')) if f.endswith('.json') and not f.endswith('_final.json')]
    
    if len(info_json_files) != 1:
        print(f"错误: 找到了 {len(info_json_files)} 个info JSON文件，期望只有1个")
        return
    
    info_json_path = os.path.join(os.getenv('PDF_GENERATOR_INPUT_2'), info_json_files[0])
    content_json_path = os.path.join(os.getenv('PDF_GENERATOR_INPUT_1'), filename)
    
    print(f"正在处理 {base_name}...")

    try:
        # 读取 content_start 和 toc_start 以及 toc_structure
        with open(info_json_path, 'r', encoding='utf-8') as f:
            info_data = json.load(f)
        content_start = info_data.get('content_start', 1)
        toc_start = info_data.get('toc_start', 1)
        toc_end = info_data.get('toc_end', toc_start)  # 如果没有 toc_end，使用 toc_start
        toc_structure = info_data.get('toc_structure', 'original')  # 默认为 original
        export_filename_template = info_data.get('export_filename', '%name-toc')  # 默认为%name-toc
        original_filename = info_data.get('original_filename', base_name + '.pdf')  # 原始文件名
        
        # 读取目录数据
        with open(content_json_path, 'r', encoding='utf-8') as f:
            toc_data = json.load(f)
        
        # 修改：先将所有页码+1
        for item in toc_data:
            if 'number' in item and isinstance(item['number'], (int, float)):
                item['number'] = item['number'] + 1
        
        # 添加"目录"条目，将其指向当前页面的下一页
        toc_entry = {
            'text': '目录',
            'number': toc_start,  # 原来的toc_start是当前页，+1就是下一页
            'level': 1
        }
        toc_data.insert(0, toc_entry)
        
        # 根据toc_structure过滤不需要的条目
        filtered_items = []
        for item in toc_data:
            # "目录"条目始终保留
            if item['text'] == '目录':
                filtered_items.append(item)
            # 根据规则决定是否移除其他条目
            elif should_remove_item(item['text'], toc_structure):
                print(f"根据toc_structure规则移除条目: {item['text']}")
            else:
                filtered_items.append(item)
        
        # 调整页码（注意：不再调整"目录"条目的页码）
        valid_items = []
        for item in filtered_items:
            try:
                if item['text'] != '目录':  # 不调整"目录"条目的页码
                    if not isinstance(item['number'], (int, float)):
                        print(f"警告: 跳过无效页码的条目 '{item['text']}'")
                        continue
                    item['number'] = item['number'] + content_start - 1
                
                valid_items.append(item)
            except (KeyError, TypeError) as e:
                print(f"警告: 跳过格式错误的条目: {str(e)}")
                continue
        
        # 按页码排序
        valid_items.sort(key=lambda x: x['number'])
        
        # 使用pikepdf处理PDF
        pdf = pikepdf.Pdf.open(pdf_path)
        
        # 创建书签结构
        def create_bookmark_tree(items):
            current_l1 = None
            current_l2 = None
            current_l3 = None
            bookmarks = []
            
            for item in items:
                try:
                    # 检查页码是否有效（页码从1开始，pdf.pages索引从0开始）
                    if item['number'] < 1 or item['number'] > len(pdf.pages):
                        print(f"警告: 页码 {item['number']} 超出范围(1-{len(pdf.pages)})，跳过条目 '{item['text']}'")
                        continue
                    
                    print(f"\n创建书签:")
                    print(f"标题: {item['text']}")
                    print(f"页码: {item['number']}")
                    print(f"级别: {item['level']}")
                    
                    # 创建书签，页码需要转换为0基索引
                    bookmark = pikepdf.OutlineItem(item['text'], item['number'] - 1, 'Fit')
                    
                    if item['level'] == 1:
                        current_l1 = bookmark
                        bookmarks.append(bookmark)
                        if not hasattr(current_l1, 'children'):
                            current_l1.children = []
                        # 重置下级指针
                        current_l2 = None
                        current_l3 = None
                    elif item['level'] == 2:
                        if current_l1 is not None:
                            if not hasattr(current_l1, 'children'):
                                current_l1.children = []
                            current_l1.children.append(bookmark)
                            current_l2 = bookmark
                            if not hasattr(current_l2, 'children'):
                                current_l2.children = []
                            # 重置下级指针
                            current_l3 = None
                        else:
                            bookmarks.append(bookmark)
                    elif item['level'] == 3:
                        if current_l2 and current_l1:
                            if not hasattr(current_l2, 'children'):
                                current_l2.children = []
                            current_l2.children.append(bookmark)
                            current_l3 = bookmark
                            if not hasattr(current_l3, 'children'):
                                current_l3.children = []
                        elif current_l1:
                            if not hasattr(current_l1, 'children'):
                                current_l1.children = []
                            current_l1.children.append(bookmark)
                        else:
                            bookmarks.append(bookmark)
                    elif item['level'] == 4:
                        if current_l3 and current_l2 and current_l1:
                            if not hasattr(current_l3, 'children'):
                                current_l3.children = []
                            current_l3.children.append(bookmark)
                        elif current_l2 and current_l1:
                            if not hasattr(current_l2, 'children'):
                                current_l2.children = []
                            current_l2.children.append(bookmark)
                        elif current_l1:
                            if not hasattr(current_l1, 'children'):
                                current_l1.children = []
                            current_l1.children.append(bookmark)
                        else:
                            bookmarks.append(bookmark)
                            
                except Exception as e:
                    print(f"警告: 创建书签时出错，跳过条目 '{item.get('text', '未知')}': {str(e)}")
                    continue
            
            return bookmarks

        # 清除现有书签
        if '/Outlines' in pdf.Root:
            del pdf.Root.Outlines
            
        # 创建新书签
        bookmarks = create_bookmark_tree(valid_items)
        
        # 将书签添加到PDF
        if bookmarks:  # 只有当有书签时才添加
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
            '/Comments': '本 PDF 书签由 autoContents 程序生成，感谢您使用本程序！该程序在 GitHub 开源，明确禁止未经授权的商业使用。如果您是通过付费渠道获得此 PDF，建议您访问 GitHub 官方网站查询程序的授权情况。如果确认未经授权，建议您申请退款。若您愿意将销售相关信息告知作者，将不胜感激。作者邮箱：uijm2004@outlook.com'
        }))
        
        # 生成输出文件名
        output_filename_base = replace_filename_placeholders(
            export_filename_template, 
            original_filename,
            toc_start,
            toc_end
        )
        
        # 保存处理后的 PDF 到新目录
        output_path = os.path.join(os.getenv('PDF_GENERATOR_OUTPUT_1'), f'{output_filename_base}.pdf')
        pdf.save(output_path)
        print(f"\n已成功处理 {output_filename_base}")
        
    except Exception as e:
        print(f"处理 {base_name} 时出错: {str(e)}")
        import traceback
        print(traceback.format_exc())

if __name__ == '__main__':
    process_pdf_with_bookmarks()
