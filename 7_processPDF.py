import json
import os
import pikepdf

def process_pdf_with_bookmarks(root_dir):
    content_dir = os.path.join(root_dir, '6_confirmedContentInfo')
    pdf_dir = os.path.join(root_dir, '0_originPDF')
    
    for filename in os.listdir(content_dir):
        if not filename.endswith('_processed.json'):
            continue
            
        base_name = filename.replace('_processed.json', '')
        pdf_path = os.path.join(pdf_dir, f'{base_name}.pdf')
        info_json_path = os.path.join(pdf_dir, f'{base_name}.json')
        content_json_path = os.path.join(content_dir, filename)
        
        print(f"正在处理 {base_name}...")

        try:
            # 读取content_start
            with open(info_json_path, 'r', encoding='utf-8') as f:
                info_data = json.load(f)
            content_start = info_data.get('content_start', 1)
            
            # 读取目录数据
            with open(content_json_path, 'r', encoding='utf-8') as f:
                toc_data = json.load(f)
            
            # 调整页码
            for item in toc_data['items']:
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
            
            # 保存处理后的PDF
            output_path = os.path.join(pdf_dir, f'{base_name}_with_toc.pdf')
            pdf.save(output_path)
            print(f"\n已成功处理 {base_name}")
            
        except Exception as e:
            print(f"处理 {base_name} 时出错: {str(e)}")
            import traceback
            print(traceback.format_exc())

if __name__ == '__main__':
    root_dir = '.'  # 项目根目录
    process_pdf_with_bookmarks(root_dir)