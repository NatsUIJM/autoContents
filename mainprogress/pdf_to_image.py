"""
文件名: pdf2jpg.py (原名: 0_pdf2jpg.py)
功能: 将PDF文件转换为高质量JPG图片，并进行二值化处理
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import os
import json
from pdf2image import convert_from_path
from PIL import Image
import numpy as np

import dotenv
dotenv.load_dotenv()

def binarize_image(image_path, threshold=200):
    """对图片进行二值化处理"""
    # 打开图片
    img = Image.open(image_path)
    # 转换为灰度图
    img = img.convert('L')
    # 转换为numpy数组
    img_array = np.array(img)
    # 二值化处理
    binary_array = (img_array > threshold) * 255
    # 转回PIL图片
    binary_img = Image.fromarray(binary_array.astype(np.uint8))
    # 覆盖保存
    binary_img.save(image_path, 'JPEG')

def convert_pdf_to_jpg():
    # 确保输出目录存在
    os.makedirs(os.getenv('PDF2JPG_OUTPUT'), exist_ok=True)
    
    # 获取所有PDF文件
    pdf_files = [f for f in os.listdir(os.getenv('PDF2JPG_INPUT')) 
                 if f.lower().endswith('.pdf')]
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(os.getenv('PDF2JPG_INPUT'), pdf_file)
        pdf_name = os.path.splitext(pdf_file)[0]
        json_path = os.path.join(os.getenv('PDF2JPG_INPUT'), f"{pdf_name}.json")
        
        print(f"\n处理文件: {pdf_file}")
        try:
            # 从JSON文件读取数据
            if not os.path.exists(json_path):
                print(f"未找到对应的JSON文件: {json_path}")
                continue
                
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
                
            toc_start = json_data['toc_start']
            toc_end = json_data['toc_end']
            content_start = json_data['content_start']
            
            # 转换PDF页面为图片
            pages = convert_from_path(
                pdf_path,
                first_page=toc_start,
                last_page=toc_end,
                dpi=300
            )
            
            # 保存图片并进行二值化处理
            saved_images = []  # 记录保存的图片路径
            for i, page in enumerate(pages, start=toc_start):
                output_path = os.path.join(
                    os.getenv('PDF2JPG_OUTPUT'),
                    f"{pdf_name}_page_{i}.jpg"
                )
                page.save(output_path, 'JPEG')
                saved_images.append(output_path)
                print(f"已保存: {output_path}")
            
            # 对保存的图片进行二值化处理
            print("\n开始二值化处理...")
            for image_path in saved_images:
                binarize_image(image_path, threshold=200)
                print(f"已完成二值化: {image_path}")
            
        except json.JSONDecodeError as e:
            print(f"JSON文件格式错误 {json_path}: {e}")
            continue
        except KeyError as e:
            print(f"JSON文件缺少必要的键 {json_path}: {e}")
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