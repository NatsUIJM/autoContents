import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import os
import json
from pdf2image import convert_from_path
from PIL import Image
import numpy as np
import cv2  # 引入OpenCV库用于自适应二值化

import dotenv
dotenv.load_dotenv()

def resize_image(image_path, max_dimension=2000):
    """将图片长边调整为最多max_dimension像素"""
    img = Image.open(image_path)
    width, height = img.size
    
    # 如果图片的长边超过max_dimension，则进行缩放
    if max(width, height) > max_dimension:
        if width > height:
            new_width = max_dimension
            new_height = int(height * max_dimension / width)
        else:
            new_height = max_dimension
            new_width = int(width * max_dimension / height)
            
        img = img.resize((new_width, new_height), Image.LANCZOS)
        img.save(image_path, 'JPEG', quality=95)
        print(f"已调整图片尺寸: {image_path} -> {new_width}x{new_height}")

def adaptive_binarize_image(image_path, block_size=25, C=5):
    """针对条纹问题优化的自适应二值化处理"""
    # 读取图片
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    
    # 步骤1: 使用非局部均值去噪去除微小噪声，该算法能较好地保留细节
    # h参数越小，保留的细节越多
    denoised = cv2.fastNlMeansDenoising(img, None, h=10, templateWindowSize=7, searchWindowSize=21)
    
    # 步骤2: 使用较大的block_size，这样自适应阈值对局部变化不会太敏感
    # 增加C值，减少误判为前景的背景像素
    binary_img = cv2.adaptiveThreshold(
        denoised,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,  # 高斯加权通常比均值效果更好
        cv2.THRESH_BINARY,
        block_size,  # 增大block_size减少条纹
        C  # 增大C值抑制背景噪声
    )
    
    # 保存处理后的图片
    cv2.imwrite(image_path, binary_img)
    
    return image_path

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
            
            # 保存图片
            saved_images = []  # 记录保存的图片路径
            for i, page in enumerate(pages, start=toc_start):
                output_path = os.path.join(
                    os.getenv('PDF2JPG_OUTPUT'),
                    f"{pdf_name}_page_{i}.jpg"
                )
                page.save(output_path, 'JPEG')
                saved_images.append(output_path)
                print(f"已保存: {output_path}")
            
            # 先调整图片尺寸，再进行自适应二值化处理
            print("\n开始调整图片尺寸...")
            for image_path in saved_images:
                resize_image(image_path, max_dimension=2000)
                print(f"已完成尺寸调整: {image_path}")
            
            print("\n开始自适应二值化处理...")
            for image_path in saved_images:
                adaptive_binarize_image(image_path, block_size=11, C=2)
                print(f"已完成自适应二值化: {image_path}")
            
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
