import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import os
import json
from pdf2image import convert_from_path
from PIL import Image

import dotenv
dotenv.load_dotenv()

def resize_image(image_path, max_dimension=2000):
    """将图片长边调整为最多 max_dimension 像素"""
    img = Image.open(image_path)
    width, height = img.size
    
    # 如果图片的长边超过 max_dimension，则进行缩放
    if max(width, height) > max_dimension:
        if width > height:
            new_width = max_dimension
            new_height = int(height * max_dimension / width)
        else:
            new_height = max_dimension
            new_width = int(width * max_dimension / height)
            
        img = img.resize((new_width, new_height), Image.LANCZOS)
        img.save(image_path, 'JPEG', quality=95)
        print(f"已调整图片尺寸：{image_path} -> {new_width}x{new_height}")

def convert_pdf_to_jpg():
    # 确保输出目录存在
    os.makedirs(os.getenv('PDF2JPG_OUTPUT'), exist_ok=True)
    
    # 获取所有 PDF 文件
    input_dir = os.getenv('PDF2JPG_INPUT')
    if not input_dir:
        print("错误：未找到环境变量 PDF2JPG_INPUT")
        return

    output_dir = os.getenv('PDF2JPG_OUTPUT')
    
    pdf_files = [f for f in os.listdir(input_dir) 
                 if f.lower().endswith('.pdf')]
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(input_dir, pdf_file)
        pdf_name = os.path.splitext(pdf_file)[0]
        json_path = os.path.join(input_dir, f"{pdf_name}.json")
        
        print(f"\n处理文件：{pdf_file}")
        try:
            # 从 JSON 文件读取数据
            if not os.path.exists(json_path):
                print(f"未找到对应的 JSON 文件：{json_path}")
                continue
                
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
                
            toc_start = json_data['toc_start']
            toc_end = json_data['toc_end']
            # content_start 变量在原代码中读取但未使用，此处保留读取以避免潜在逻辑缺失，若确无需可删除
            # content_start = json_data['content_start'] 
            
            # 转换 PDF 页面为图片
            pages = convert_from_path(
                pdf_path,
                first_page=toc_start,
                last_page=toc_end,
                dpi=300
            )
            
            # 保存图片
            saved_images = []  # 记录保存的图片路径
            for i, page in enumerate(pages, start=toc_start):
                output_path = os.path.join(
                    output_dir,
                    f"{pdf_name}_page_{i}.jpg"
                )
                page.save(output_path, 'JPEG')
                saved_images.append(output_path)
                print(f"已保存：{output_path}")
            
            # 仅执行图片尺寸调整
            print("\n开始调整图片尺寸...")
            for image_path in saved_images:
                resize_image(image_path, max_dimension=2000)
                print(f"已完成尺寸调整：{image_path}")
            
        except json.JSONDecodeError as e:
            print(f"JSON 文件格式错误 {json_path}: {e}")
            continue
        except KeyError as e:
            print(f"JSON 文件缺少必要的键 {json_path}: {e}")
            continue
        except Exception as e:
            print(f"处理文件 {pdf_file} 时发生错误：{e}")
            continue

if __name__ == "__main__":
    try:
        convert_pdf_to_jpg()
        print("\n所有文件处理完成!")
    except Exception as e:
        print(f"程序执行出错：{e}")