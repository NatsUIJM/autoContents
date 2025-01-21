import os
import json
from pdf2image import convert_from_path

def convert_pdf_to_jpg():
    # 确保目录存在
    pdf_dir = "0_originPDF"
    output_dir = os.path.join("1_picMark", "inputPic")
    os.makedirs(output_dir, exist_ok=True)
    
    # 获取所有PDF文件
    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.pdf')]
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(pdf_dir, pdf_file)
        pdf_name = os.path.splitext(pdf_file)[0]
        
        # 请求用户输入
        print(f"\n处理文件: {pdf_file}")
        try:
            toc_start = int(input("请输入目录起始页 (PDF第几页): "))
            toc_end = int(input("请输入目录结束页 (PDF第几页): "))
            content_start = int(input("请输入正文第1页 (PDF第几页): "))
            
            # 保存JSON数据
            json_data = {
                "toc_start": toc_start,
                "toc_end": toc_end,
                "content_start": content_start
            }
            
            json_path = os.path.join(pdf_dir, f"{pdf_name}.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)
            
            # 转换PDF页面为图片
            pages = convert_from_path(
                pdf_path,
                first_page=toc_start,
                last_page=toc_end,
                dpi=300
            )
            
            # 保存图片
            for i, page in enumerate(pages, start=toc_start):
                output_path = os.path.join(output_dir, f"{pdf_name}_page_{i}.jpg")
                page.save(output_path, 'JPEG')
                print(f"已保存: {output_path}")
            
        except ValueError as e:
            print(f"输入错误: {e}")
            continue
        except Exception as e:
            print(f"处理文件 {pdf_file} 时发生错误: {e}")
            continue

if __name__ == "__main__":
    try:
        convert_pdf_to_jpg()
        print("\n所有文件处理完成!")
    except Exception as e:
        print(f"程序执行出错: {e}")