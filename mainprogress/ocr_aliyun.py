"""
文件名: ocr_aliyun.py (原名: 3_2_AliyunOCR.py)
功能: 使用阿里云OCR服务识别图片文本
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import os
import json
from pathlib import Path
import concurrent.futures
from PIL import Image
import io
from alibabacloud_ocr_api20210707.client import Client as ocr_api20210707Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_darabonba_stream.client import Client as StreamClient
from alibabacloud_ocr_api20210707 import models as ocr_api_20210707_models
from alibabacloud_tea_util import models as util_models
from config.paths import PathConfig

def create_client():
    """创建阿里云OCR客户端"""
    config = open_api_models.Config(
        access_key_id=os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'],
        access_key_secret=os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET']
    )
    config.endpoint = 'ocr-api.cn-hangzhou.aliyuncs.com'
    return ocr_api20210707Client(config)

def process_aliyun_json(data_json):
    """将阿里云OCR结果转换为目标格式"""
    output_data = []
    
    if 'prism_wordsInfo' in data_json:
        for word_info in data_json['prism_wordsInfo']:
            if 'word' in word_info and 'pos' in word_info:
                text = word_info['word']
                bbox = []
                for point in word_info['pos']:
                    bbox.append([int(point['x']), int(point['y'])])
                item = {
                    'text': text,
                    'bbox': bbox
                }
                output_data.append(item)
    
    return output_data

def resize_image_if_needed(img_path):
    """检查并在需要时调整图片尺寸"""
    with Image.open(img_path) as img:
        width, height = img.size
        max_size = 8150
        target_size = 8000
        
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

def process_image(img_path, output_dir):
    """处理单张图片的OCR并保存结果"""
    try:
        print(f"\n=== 开始处理图片: {img_path} ===")
        
        client = create_client()
        
        # 检查是否需要调整图片尺寸
        resized_image = resize_image_if_needed(img_path)
        
        if resized_image:
            print("图片尺寸超过限制，已自动调整")
            body_stream = resized_image
        else:
            body_stream = StreamClient.read_from_file_path(str(img_path))
        
        recognize_request = ocr_api_20210707_models.RecognizeGeneralRequest(
            body=body_stream
        )
        
        runtime = util_models.RuntimeOptions(
            read_timeout=10000,
            connect_timeout=10000
        )
        
        print("调用阿里云OCR API...")
        response = client.recognize_general_with_options(recognize_request, runtime)
        result = response.to_map()
        
        if 'body' in result and 'Data' in result['body']:
            data_str = result['body']['Data']
            try:
                data_json = json.loads(data_str)
                processed_data = process_aliyun_json(data_json)
                
                print(f"处理完成，共转换 {len(processed_data)} 个文本块")
                
                json_path = output_dir / f"{img_path.stem}.json"
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(processed_data, f, ensure_ascii=False, indent=2)
                
                print(f"结果已保存到: {json_path}")
                
            except json.JSONDecodeError as e:
                print(f"解析Data字段失败: {str(e)}")
                print("Data内容:")
                print(data_str[:200] + "...") 
        
        print(f"=== 处理完成: {img_path} ===\n")
        
    except Exception as e:
        print(f"Error processing {img_path.name}: {str(e)}")
        print("Full error details:")
        import traceback
        print(traceback.format_exc())

def main():
    # 验证环境变量
    if not os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID') or not os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET'):
        raise ValueError("Aliyun credentials not found in environment variables")
        
    # 创建输出目录
    output_dir = Path(PathConfig.ALIYUN_OCR_OUTPUT)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 读取输入目录中的图片
    input_dir = Path(PathConfig.ALIYUN_OCR_INPUT)
    if not input_dir.exists():
        raise ValueError(f"Input directory {input_dir} does not exist")
    
    img_paths = []
    for ext in ['.jpg', '.jpeg', '.png']:
        img_paths.extend(list(input_dir.glob(f'*{ext}')))
    
    if not img_paths:
        print("No images found in input directory")
        return
    
    print(f"Found {len(img_paths)} images to process")
    
    # 使用线程池处理图片，最大并发数为10
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