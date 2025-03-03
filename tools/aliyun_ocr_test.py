"""
文件名: test_ocr_aliyun.py
功能: 测试阿里云OCR服务，处理测试图片并保存原始OCR结果
"""
import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path
import io
from alibabacloud_ocr_api20210707.client import Client as ocr_api20210707Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_darabonba_stream.client import Client as StreamClient
from alibabacloud_ocr_api20210707 import models as ocr_api_20210707_models
from alibabacloud_tea_util import models as util_models
from PIL import Image
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def create_client():
    """创建阿里云OCR客户端"""
    config = open_api_models.Config(
        access_key_id=os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'],
        access_key_secret=os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET']
    )
    config.endpoint = 'ocr-api.cn-hangzhou.aliyuncs.com'
    return ocr_api20210707Client(config)

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

def test_aliyun_ocr():
    """测试阿里云OCR功能"""
    print("=== 开始测试阿里云OCR ===")
    
    # 验证环境变量
    if not os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID') or not os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET'):
        raise ValueError("Aliyun credentials not found in environment variables")
    
    # 获取测试图片路径
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    img_path = script_dir / 'aliyun_ocr_test_figure.jpg'
    
    if not img_path.exists():
        raise FileNotFoundError(f"测试图片不存在: {img_path}")
    
    print(f"测试图片: {img_path}")
    
    # 创建OCR客户端
    client = create_client()
    
    # 检查是否需要调整图片尺寸
    resized_image = resize_image_if_needed(img_path)
    
    if resized_image:
        print("图片尺寸超过限制，已自动调整")
        body_stream = resized_image
    else:
        body_stream = StreamClient.read_from_file_path(str(img_path))
    
    # 创建请求
    recognize_request = ocr_api_20210707_models.RecognizeGeneralRequest(
        body=body_stream
    )
    
    runtime = util_models.RuntimeOptions(
        read_timeout=10000,
        connect_timeout=10000
    )
    
    # 调用OCR API
    print("调用阿里云OCR API...")
    start_time = time.time()
    response = client.recognize_general_with_options(recognize_request, runtime)
    elapsed_time = time.time() - start_time
    print(f"API调用完成，耗时: {elapsed_time:.2f}秒")
    
    result = response.to_map()
    
    # 生成输出文件名
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output_file = script_dir / f"{timestamp}.json"
    
    # 保存原始结果
    if 'body' in result and 'Data' in result['body']:
        data_str = result['body']['Data']
        try:
            data_json = json.loads(data_str)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data_json, f, ensure_ascii=False, indent=2)
            
            print(f"原始OCR结果已保存到: {output_file}")
            
            # 分析结果
            if 'prism_wordsInfo' in data_json:
                print(f"识别到 {len(data_json['prism_wordsInfo'])} 个文本块")
                
                # 打印部分结果示例
                if len(data_json['prism_wordsInfo']) > 0:
                    print("\n识别结果示例:")
                    for i, word_info in enumerate(data_json['prism_wordsInfo'][:3]):
                        if 'word' in word_info:
                            print(f"  {i+1}. {word_info['word']}")
                    
                    if len(data_json['prism_wordsInfo']) > 3:
                        print(f"  ... 共 {len(data_json['prism_wordsInfo'])} 个文本")
            
        except json.JSONDecodeError as e:
            print(f"解析Data字段失败: {str(e)}")
            print("保存原始Data字符串...")
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(data_str)
            
            print(f"原始数据已保存到: {output_file}")
    else:
        print("API响应中没有找到Data字段")
        print("保存完整响应...")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"完整响应已保存到: {output_file}")
    
    print("=== 测试完成 ===")

if __name__ == '__main__':
    try:
        test_aliyun_ocr()
    except Exception as e:
        print(f"测试过程中发生错误: {str(e)}")
        import traceback
        traceback.print_exc()