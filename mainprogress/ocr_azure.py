"""
文件名: ocr_azure.py (原名: 3_1_AzureOCR.py)
功能: 使用Azure OCR服务处理图片并生成文字识别结果
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import os
import json
import time
from pathlib import Path
import concurrent.futures
from PIL import Image
import io
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient
from config.paths import PathConfig

from dotenv import load_dotenv
load_dotenv()

# Azure设置
endpoint = os.getenv('AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT')
key = os.getenv('AZURE_DOCUMENT_INTELLIGENCE_KEY')

def retry_with_delay(max_retries=10, delay=10):
    """重试装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    if retries == max_retries:
                        print(f"达到最大重试次数 {max_retries}，操作失败")
                        raise
                    print(f"发生错误: {str(e)}")
                    print(f"第 {retries} 次重试，等待 {delay} 秒...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

def convert_polygon_points(polygon_points):
    """将Azure OCR返回的点数组转换为bbox格式"""
    bbox = []
    for point in polygon_points:
        bbox.append([int(point['x']), int(point['y'])])
    return bbox

def process_azure_json(result):
    """处理Azure OCR返回的JSON，转换为目标格式"""
    output_data = []
    
    try:
        for page in result.get('pages', []):
            for line in page.get('lines', []):
                polygon = line.get('polygon', [])
                if polygon:
                    item = {
                        'text': line.get('content', ''),
                        'bbox': convert_polygon_points(polygon)
                    }
                    output_data.append(item)
    except Exception as e:
        print(f"Error in process_azure_json: {str(e)}")
        print(f"Result structure: {json.dumps(result, indent=2)}")
        raise
    
    return output_data

def resize_image_if_needed(img_path):
    """检查并在需要时调整图片尺寸"""
    with Image.open(img_path) as img:
        width, height = img.size
        max_size = 9990
        target_size = 9900
        
        if width > max_size or height > max_size:
            # 计算缩放比例
            if width > height:
                if width > max_size:
                    ratio = target_size / width
                    new_width = target_size
                    new_height = int(height * ratio)
            else:
                if height > max_size:
                    ratio = target_size / height
                    new_height = target_size
                    new_width = int(width * ratio)
            
            # 调整图片尺寸
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 将调整后的图片保存到内存
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format=img.format if img.format else 'JPEG')
            return img_byte_arr.getvalue()
            
    # 如果不需要调整，返回None
    return None

@retry_with_delay(max_retries=10, delay=10)
def process_image(img_path, output_dir):
    """处理单张图片的OCR并保存结果"""
    document_analysis_client = DocumentAnalysisClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key)
    )
    
    # 检查是否需要调整图片尺寸
    resized_image = resize_image_if_needed(img_path)
    
    if resized_image:
        print(f"图片 {img_path.name} 尺寸超过限制，已自动调整")
        image_data = resized_image
    else:
        with open(str(img_path), "rb") as image_file:
            image_data = image_file.read()
    
    print(f"Starting OCR for {img_path.name}")
    poller = document_analysis_client.begin_analyze_document(
        "prebuilt-document",
        document=image_data
    )
    result = poller.result()
    
    result_dict = result.to_dict()
    processed_data = process_azure_json(result_dict)
    
    json_path = output_dir / f"{img_path.stem}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(processed_data, f, ensure_ascii=False, indent=2)
    
    print(f"Successfully processed {img_path.name}")

def main():
    if not endpoint or not key:
        raise ValueError("Azure credentials not found in environment variables")
        
    # 创建输出目录
    output_dir = Path(os.getenv('OCR_AZURE_OUTPUT_1'))
    os.makedirs(output_dir, exist_ok=True)
    
    # 读取输入目录中的图片
    input_dir = Path(os.getenv('OCR_AZURE_INPUT_1'))
    if not input_dir.exists():
        raise ValueError(f"Input directory {input_dir} does not exist")
    
    img_paths = []
    for ext in ['.jpg', '.jpeg', '.png']:
        img_paths.extend(list(input_dir.glob(f'*{ext}')))
    
    if not img_paths:
        print("No images found in input directory")
        return
    
    print(f"Found {len(img_paths)} images to process")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_image, img_path, output_dir) 
                  for img_path in img_paths]
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"Error in thread: {str(e)}")

if __name__ == '__main__':
    main()