import os
import json
from pathlib import Path
import concurrent.futures
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient

# Azure设置
endpoint = os.getenv('AZURE_DOCUMENT_ENDPOINT')
key = os.getenv('AZURE_DOCUMENT_KEY')

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
        # 处理每一页
        for page in result.get('pages', []):
            # 处理每一行文本
            for line in page.get('lines', []):
                # 获取多边形坐标
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

def process_image(img_path, output_dir):
    """处理单张图片的OCR并保存结果"""
    try:
        # 创建Azure客户端
        document_analysis_client = DocumentAnalysisClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(key)
        )
        
        # 读取图片
        with open(str(img_path), "rb") as image_file:
            image_data = image_file.read()
        
        # 调用Azure OCR
        print(f"Starting OCR for {img_path.name}")
        poller = document_analysis_client.begin_analyze_document(
            "prebuilt-document",
            document=image_data
        )
        result = poller.result()
        
        # 转换为字典并处理
        result_dict = result.to_dict()
        processed_data = process_azure_json(result_dict)
        
        # 保存处理后的JSON
        json_path = output_dir / f"{img_path.stem}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=2)
        
        print(f"Successfully processed {img_path.name}")
        
    except Exception as e:
        print(f"Error processing {img_path.name}: {str(e)}")
        print("Full error details:")
        import traceback
        print(traceback.format_exc())

def main():
    # 验证环境变量
    if not endpoint or not key:
        raise ValueError("Azure credentials not found in environment variables")
        
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