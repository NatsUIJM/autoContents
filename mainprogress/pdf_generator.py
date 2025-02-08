"""
文件名: pdf_generator.py (原名: 7_processPDF.py)
功能: 处理PDF文件，添加书签结构
"""
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
    os.makedirs(os.getenv('PDF_GENERATOR_OUTPUT_1'), exist_ok=True)
    
    for filename in os.listdir(os.getenv('PDF_GENERATOR_INPUT_1')):
        if not filename.endswith('_final.json'):
            continue
            
        base_name = filename.replace('_final.json', '')
        pdf_path = os.path.join(os.getenv('PDF_GENERATOR_INPUT_2'), f'{base_name}.pdf')
        info_json_path = os.path.join(os.getenv('PDF_GENERATOR_INPUT_2'), f'{base_name}.json')
        content_json_path = os.path.join(os.getenv('PDF_GENERATOR_INPUT_1'), filename)
        
        print(f"正在处理 {base_name}...")

        try:
            # 读取content_start和toc_start
            with open(info_json_path, 'r', encoding='utf-8') as f:
                info_data = json.load(f)
            content_start = info_data.get('content_start', 1)
            toc_start = info_data.get('toc_start', 1)
            
            # 读取目录数据
            with open(content_json_path, 'r', encoding='utf-8') as f:
                toc_data = json.load(f)
            
            # 添加"目录"条目
            toc_entry = {
                'text': '目录',
                'number': toc_start,
                'level': 1
            }
            toc_data['items'].insert(0, toc_entry)
            
            # 调整页码
            for item in toc_data['items']:
                if item['text'] != '目录':  # 不调整"目录"条目的页码
                    item['number'] = item['number'] + content_start - 1
            
            # 使用pikepdf处理PDF
            pdf = pikepdf.Pdf.open(pdf_path)
            
            # 创建书签结构
            def create_bookmark_tree(items):
                current_l1 = None
                bookmarks = []
                
                for item in items:
                    try:
                        # 检查页码是否有效
                        if item['number'] < 1 or item['number'] > len(pdf.pages):
                            print(f"警告: 页码 {item['number']} 超出范围!")
                            continue
                        
                        print(f"\n创建书签:")
                        print(f"标题: {item['text']}")
                        print(f"页码: {item['number']}")
                        print(f"级别: {item['level']}")
                        
                        # 创建书签，页码从0开始计数
                        bookmark = pikepdf.OutlineItem(item['text'], item['number'] - 1, 'Fit')
                        
                        if item['level'] == 1:
                            current_l1 = bookmark
                            bookmarks.append(bookmark)
                            if not hasattr(current_l1, 'children'):
                                current_l1.children = []
                        elif item['level'] == 2:
                            if current_l1 is not None:
                                if not hasattr(current_l1, 'children'):
                                    current_l1.children = []
                                current_l1.children.append(bookmark)
                                if not hasattr(bookmark, 'children'):
                                    bookmark.children = []
                            else:
                                bookmarks.append(bookmark)
                        elif item['level'] == 3:
                            if current_l1 and current_l1.children:
                                parent = current_l1.children[-1]
                                if not hasattr(parent, 'children'):
                                    parent.children = []
                                parent.children.append(bookmark)
                            else:
                                bookmarks.append(bookmark)
                                
                    except Exception as e:
                        print(f"创建书签时出错: {str(e)}")
                        continue
                
                return bookmarks

            # 清除现有书签
            pdf.Root.Outlines = pdf.make_indirect(pikepdf.Dictionary())
            
            # 创建新书签
            bookmarks = create_bookmark_tree(toc_data['items'])
            
            # 将书签添加到PDF
            with pdf.open_outline() as outline:
                outline.root.extend(bookmarks)
            
            # 添加元数据
            pdf.docinfo = pdf.make_indirect(pikepdf.Dictionary({
                '/Creator': 'autoContents',
                '/Producer': 'autoContents v1.0',
                '/CreationDate': datetime.now().strftime("D:%Y%m%d%H%M%S"),
                '/URL': 'https://github.com/NatsUijm/autoContents',
                '/Comments': '本PDF书签由autoContents程序生成。感谢您使用本程序！该程序在GitHub开源，明确禁止未经授权的商业使用。如果您是通过付费渠道获得此PDF，建议您访问GitHub官方网站查询程序的授权情况。如果确认未经授权，建议您申请退款。若您愿意将销售相关信息告知作者，将不胜感激。作者邮箱：uijm2004@outlook.com'
            }))
            
            # 保存处理后的PDF到新目录
            output_path = os.path.join(os.getenv('PDF_GENERATOR_OUTPUT_1'), f'{base_name}_with_toc.pdf')
            pdf.save(output_path)
            print(f"\n已成功处理 {base_name}")
            
        except Exception as e:
            print(f"处理 {base_name} 时出错: {str(e)}")
            import traceback
            print(traceback.format_exc())

if __name__ == '__main__':
    process_pdf_with_bookmarks()