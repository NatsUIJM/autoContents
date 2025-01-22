import os
import json
from pathlib import Path
import concurrent.futures
from alibabacloud_ocr_api20210707.client import Client as ocr_api20210707Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_darabonba_stream.client import Client as StreamClient
from alibabacloud_ocr_api20210707 import models as ocr_api_20210707_models
from alibabacloud_tea_util import models as util_models

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
                # 提取文本内容
                text = word_info['word']
                
                # 转换坐标格式
                bbox = []
                for point in word_info['pos']:
                    bbox.append([int(point['x']), int(point['y'])])
                
                # 创建输出项
                item = {
                    'text': text,
                    'bbox': bbox
                }
                output_data.append(item)
    
    return output_data

def process_image(img_path, output_dir):
    """处理单张图片的OCR并保存结果"""
    try:
        print(f"\n=== 开始处理图片: {img_path} ===")
        
        # 创建阿里云客户端
        client = create_client()
        
        # 读取图片
        body_stream = StreamClient.read_from_file_path(str(img_path))
        
        # 准备请求
        recognize_request = ocr_api_20210707_models.RecognizeGeneralRequest(
            body=body_stream
        )
        
        # 设置运行时选项
        runtime = util_models.RuntimeOptions(
            read_timeout=10000,
            connect_timeout=10000
        )
        
        print("调用阿里云OCR API...")
        # 调用阿里云OCR API
        response = client.recognize_general_with_options(recognize_request, runtime)
        result = response.to_map()
        
        # 解析嵌套的JSON结构并转换格式
        if 'body' in result and 'Data' in result['body']:
            data_str = result['body']['Data']
            try:
                data_json = json.loads(data_str)
                
                # 转换为目标格式
                processed_data = process_aliyun_json(data_json)
                
                print(f"处理完成，共转换 {len(processed_data)} 个文本块")
                
                # 保存转换后的数据
                json_path = output_dir / f"{img_path.stem}.json"
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(processed_data, f, ensure_ascii=False, indent=2)
                
                print(f"结果已保存到: {json_path}")
                
            except json.JSONDecodeError as e:
                print(f"解析Data字段失败: {str(e)}")
                print("Data内容:")
                print(data_str[:200] + "...") # 只打印前200个字符
        
        print(f"=== 处理完成: {img_path} ===\n")
        
    except Exception as e:
        print(f"Error processing {img_path.name}: {str(e)}")
        print("Full error details:")
        import traceback
        print(traceback.format_exc())

def process_image(img_path, output_dir):
    """处理单张图片的OCR并保存结果"""
    try:
        print(f"\n=== 开始处理图片: {img_path} ===")
        
        # 创建阿里云客户端
        client = create_client()
        
        # 读取图片
        body_stream = StreamClient.read_from_file_path(str(img_path))
        
        # 准备请求
        recognize_request = ocr_api_20210707_models.RecognizeGeneralRequest(
            body=body_stream
        )
        
        # 设置运行时选项
        runtime = util_models.RuntimeOptions(
            read_timeout=10000,
            connect_timeout=10000
        )
        
        print("调用阿里云OCR API...")
        # 调用阿里云OCR API
        response = client.recognize_general_with_options(recognize_request, runtime)
        result = response.to_map()
        
        # 解析嵌套的JSON结构并转换格式
        if 'body' in result and 'Data' in result['body']:
            data_str = result['body']['Data']
            try:
                data_json = json.loads(data_str)
                
                # 转换为目标格式
                processed_data = process_aliyun_json(data_json)
                
                print(f"处理完成，共转换 {len(processed_data)} 个文本块")
                
                # 保存转换后的数据
                json_path = output_dir / f"{img_path.stem}.json"
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(processed_data, f, ensure_ascii=False, indent=2)
                
                print(f"结果已保存到: {json_path}")
                
            except json.JSONDecodeError as e:
                print(f"解析Data字段失败: {str(e)}")
                print("Data内容:")
                print(data_str[:200] + "...") # 只打印前200个字符
        
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
    output_dir = Path('3_1_OCRServiceBack')
    output_dir.mkdir(exist_ok=True)
    
    # 读取输入目录中的图片
    input_dir = Path('2_outputPic')
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