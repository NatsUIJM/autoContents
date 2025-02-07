"""
文件名: ocr_analyzer.py (原 main.py)
功能: 阿里云OCR文字识别和投影分析工具
"""
import os
import sys
import json
from pathlib import Path
import concurrent.futures
import numpy as np
import cv2
from PIL import Image, ImageDraw
import io
import time
from alibabacloud_ocr_api20210707.client import Client as ocr_api20210707Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_darabonba_stream.client import Client as StreamClient
from alibabacloud_ocr_api20210707 import models as ocr_api_20210707_models
from alibabacloud_tea_util import models as util_models

from dotenv import load_dotenv
load_dotenv()

# 添加项目根目录到系统路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)


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

class AliyunOCRProcessor:
    def __init__(self):
        """初始化处理器"""
        if not os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID') or \
           not os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET'):
            raise ValueError("未找到阿里云访问凭证环境变量")
        
        self.client = self.create_client()
        self.output_dir = Path(os.environ['OCR_PROJ_ALIYUN_OUTPUT'])

    def create_client(self):
        """创建阿里云OCR客户端"""
        config = open_api_models.Config(
            access_key_id=os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'],
            access_key_secret=os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET']
        )
        config.endpoint = 'ocr-api.cn-hangzhou.aliyuncs.com'
        return ocr_api20210707Client(config)

    def resize_image_if_needed(self, img_path):
        """检查并在需要时调整图片尺寸"""
        with Image.open(img_path) as img:
            width, height = img.size
            max_size = 8150
            target_size = 8000
            
            if width > max_size or height > max_size:
                if width > height:
                    ratio = target_size / width
                    new_width = target_size
                    new_height = int(height * ratio)
                else:
                    ratio = target_size / height
                    new_height = target_size
                    new_width = int(width * ratio)
                
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format=img.format if img.format else 'JPEG')
                return img_byte_arr.getvalue()
                
        return None

    def convert_response(self, raw_response, img_path):
        """
        转换响应并保存三个版本:
        1. initial.json - 最原始的响应
        2. raw_response.json - Azure格式
        3. result.json - 处理后的标准格式
        """
        output_dir = self.output_dir
        img_name = Path(img_path).stem

        # 保存最原始的响应
        initial_json_path = output_dir / f"{img_name}_initial.json"
        with open(initial_json_path, 'w', encoding='utf-8') as f:
            json.dump(raw_response, f, ensure_ascii=False, indent=2)

        # 转换为Azure格式
        azure_format = {
            "content": raw_response.get("content", ""),
            "pages": [{
                "page_number": 1,
                "width": raw_response.get("width", 0),
                "height": raw_response.get("height", 0),
                "unit": "pixel",
                "lines": [],
                "words": []
            }]
        }

        words_info = raw_response.get("prism_wordsInfo", [])
        for word_info in words_info:
            if "word" not in word_info or "pos" not in word_info:
                continue

            # 转换polygon格式
            polygon = []
            for point in word_info["pos"]:
                polygon.extend([float(point["x"]), float(point["y"])])

            azure_word = {
                "content": word_info["word"],
                "confidence": float(word_info.get("prob", 100)) / 100,
                "polygon": polygon
            }

            azure_line = {
                "content": word_info["word"],
                "polygon": polygon
            }

            azure_format["pages"][0]["words"].append(azure_word)
            azure_format["pages"][0]["lines"].append(azure_line)

        # 保存Azure格式（命名为raw_response.json）
        azure_json_path = output_dir / f"{img_name}_raw_response.json"
        with open(azure_json_path, 'w', encoding='utf-8') as f:
            json.dump(azure_format, f, ensure_ascii=False, indent=2)

        # 生成标准格式结果
        standard_format = []
        current_text = None
        current_group = []
        
        for word_info in words_info:
            if 'word' not in word_info or 'pos' not in word_info:
                continue
                
            text = word_info['word']
            points = word_info['pos']
            bbox = []
            for point in points:
                bbox.append([point['x'], point['y']])
            
            if current_text is None:
                current_text = text
                
            if text == current_text:
                current_group.append({
                    'text': text,
                    'bbox': bbox
                })
            else:
                if current_group:
                    standard_format.append({
                        'text': current_text,
                        'instances': current_group
                    })
                current_text = text
                current_group = [{
                    'text': text,
                    'bbox': bbox
                }]
        
        if current_group:
            standard_format.append({
                'text': current_text,
                'instances': current_group
            })

        return standard_format, azure_format

    def calculate_projections(self, results, image_height, image_width):
        """计算水平和垂直投影"""
        h_projection = np.zeros(image_height, dtype=np.int32)
        v_projection = np.zeros(image_width, dtype=np.int32)
        
        for result in results:
            for instance in result['instances']:
                bbox = np.array(instance['bbox'])
                # 确保坐标为整数
                y_min = int(min(p[1] for p in bbox))
                y_max = int(max(p[1] for p in bbox))
                x_min = int(min(p[0] for p in bbox))
                x_max = int(max(p[0] for p in bbox))
                
                # 确保坐标在有效范围内
                y_min = max(0, min(y_min, image_height-1))
                y_max = max(0, min(y_max, image_height-1))
                x_min = max(0, min(x_min, image_width-1))
                x_max = max(0, min(x_max, image_width-1))
                
                h_projection[y_min:y_max + 1] += 1
                v_projection[x_min:x_max + 1] += 1
            
        return h_projection, v_projection

    def draw_visualization(self, image, results, h_projection, v_projection):
        """绘制OCR结果和投影图"""
        image_pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(image_pil)
        
        # 绘制文本框
        for result in results:
            for instance in result['instances']:
                bbox = np.array(instance['bbox'])
                points = [(int(x), int(y)) for x, y in bbox]
                draw.line([*points, points[0]], fill=(0, 255, 0), width=6)
        
        # 创建水平投影图
        h_plot_width = 300
        h_plot_height = image.shape[0]
        h_plot_img = np.ones((h_plot_height, h_plot_width, 3), dtype=np.uint8) * 255
        
        max_h_proj = max(h_projection.max(), 1)
        for y in range(h_plot_height):
            if y < len(h_projection):
                x = int((h_projection[y] / max_h_proj) * (h_plot_width - 20))
                cv2.line(h_plot_img, (0, y), (x, y), (255, 0, 0), 1)
        
        # 创建垂直投影图
        v_plot_width = image.shape[1]
        v_plot_height = 300
        v_plot_img = np.ones((v_plot_height, v_plot_width, 3), dtype=np.uint8) * 255
        
        max_v_proj = max(v_projection.max(), 1)
        for x in range(v_plot_width):
            if x < len(v_projection):
                y = int((v_projection[x] / max_v_proj) * (v_plot_height - 20))
                cv2.line(v_plot_img, (x, v_plot_height - y - 1), (x, v_plot_height - 1), (255, 0, 0), 1)
        
        # 添加网格和刻度
        grid_color = (200, 200, 200)
        
        # 水平投影图网格和刻度
        for i in range(0, h_plot_width, 50):
            cv2.line(h_plot_img, (i, 0), (i, h_plot_height), grid_color, 1)
        for i in range(0, h_plot_height, 50):
            cv2.line(h_plot_img, (0, i), (h_plot_width, i), grid_color, 1)
            cv2.putText(h_plot_img, f"{i}", (5, i), cv2.FONT_HERSHEY_SIMPLEX, 
                    0.5, (0, 0, 0), 1)
        
        # 垂直投影图网格和刻度
        for i in range(0, v_plot_width, 50):
            cv2.line(v_plot_img, (i, 0), (i, v_plot_height), grid_color, 1)
        for i in range(0, v_plot_height, 50):
            cv2.line(v_plot_img, (0, i), (v_plot_width, i), grid_color, 1)
        
        # 添加数值刻度
        for i in range(0, 6):
            x = int((h_plot_width - 20) * i / 5)
            value = int((max_h_proj * i / 5))
            cv2.putText(h_plot_img, f"{value}", (x, h_plot_height - 10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
            
            y = int((v_plot_height - 20) * i / 5)
            value = int((max_v_proj * i / 5))
            cv2.putText(v_plot_img, f"{value}", (10, v_plot_height - y - 10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        
        # 组合最终图像
        result_img = cv2.cvtColor(np.array(image_pil), cv2.COLOR_RGB2BGR)
        combined_h = np.hstack((result_img, h_plot_img))
        v_plot_padding = np.ones((v_plot_height, h_plot_width, 3), dtype=np.uint8) * 255
        v_plot_combined = np.hstack((v_plot_img, v_plot_padding))
        final_img = np.vstack((combined_h, v_plot_combined))
        
        return final_img
    @retry_with_delay(max_retries=10, delay=10)
    def process_image(self, img_path):
        """处理单张图片"""
        print(f"\n=== 开始处理图片: {img_path} ===")
        
        output_dir = self.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        
        resized_image = self.resize_image_if_needed(img_path)
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
        response = self.client.recognize_general_with_options(recognize_request, runtime)
        result = response.to_map()
        
        if 'body' in result and 'Data' in result['body']:
            data_str = result['body']['Data']
            raw_response = json.loads(data_str)
            
            # 转换响应格式并保存
            standard_format, azure_format = self.convert_response(raw_response, img_path)
            
            # 保存标准格式结果
            output_json_path = output_dir / f"{img_path.stem}_result.json"
            with open(output_json_path, 'w', encoding='utf-8') as f:
                json.dump(standard_format, f, ensure_ascii=False, indent=2)
            
            # 生成可视化结果
            image = cv2.imread(str(img_path))
            height, width = image.shape[:2]
            
            h_projection, v_projection = self.calculate_projections(standard_format, height, width)
            output_img = self.draw_visualization(image, standard_format, h_projection, v_projection)
            
            output_img_path = output_dir / f"{img_path.stem}_annotated.jpg"
            cv2.imwrite(str(output_img_path), output_img)
            
            print(f"处理完成，结果已保存：")
            print(f"- 原始响应：{output_dir}/{img_path.stem}_initial.json")
            print(f"- Azure格式：{output_dir}/{img_path.stem}_raw_response.json")
            print(f"- 标准格式：{output_json_path}")
            print(f"- 标注图片：{output_img_path}")

    def process_directory(self, input_dir, max_workers=5):
        """处理目录中的所有图片"""
        input_path = Path(input_dir)
        if not input_path.exists():
            raise ValueError(f"输入目录 {input_dir} 不存在")
        
        # 查找所有图片
        img_paths = []
        for ext in ['.jpg', '.jpeg', '.png']:
            img_paths.extend(list(input_path.glob(f'*{ext}')))
        
        if not img_paths:
            print("未找到需要处理的图片")
            return
        
        print(f"找到 {len(img_paths)} 张待处理的图片")
        
        # 使用线程池处理图片
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self.process_image, img_path) 
                      for img_path in img_paths]
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"线程执行错误: {str(e)}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description='阿里云OCR文字识别和投影分析工具')
    parser.add_argument('--input', default=os.environ['OCR_PROJ_ALIYUN_INPUT'], 
                       help='输入图片目录路径')
    parser.add_argument('--workers', type=int, default=5, 
                       help='并发处理的最大线程数')
    args = parser.parse_args()

    # 确保输出目录存在
    os.makedirs(os.environ['OCR_PROJ_ALIYUN_OUTPUT'], exist_ok=True)

    processor = AliyunOCRProcessor()
    processor.process_directory(args.input, args.workers)

if __name__ == '__main__':
    main()