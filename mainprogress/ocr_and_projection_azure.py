"""
文件名: ocr_and_projection.py (原名: OCR和投影（标准版）.py)
功能: 使用Azure文档智能服务进行OCR识别，并计算文本投影
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import base64
import json
from pathlib import Path
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
import io
import concurrent.futures
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from datetime import datetime
from config.paths import PathConfig

class OCRProcessor:
    def __init__(self):
        # Azure设置
        self.endpoint = os.getenv('AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT')
        self.key = os.getenv('AZURE_DOCUMENT_INTELLIGENCE_KEY')
        
        if not self.endpoint or not self.key:
            raise ValueError(
                "Please set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and "
                "AZURE_DOCUMENT_INTELLIGENCE_KEY environment variables"
            )
        
        # 确保目录存在
        self.input_dir = Path(PathConfig.OCR_PROJ_AZURE_INPUT)
        self.output_dir = Path(PathConfig.OCR_PROJ_AZURE_OUTPUT)
        self.output_dir.mkdir(exist_ok=True)
        self.input_dir.mkdir(exist_ok=True)

    def convert_polygon_points(self, polygon_points):
        """将Azure OCR返回的点数组转换为bbox格式"""
        bbox = []
        for point in polygon_points:
            bbox.append([int(point['x']), int(point['y'])])
        return bbox

    def process_azure_result(self, result):
        """处理Azure OCR返回的结果，转换为目标格式"""
        output_data = []
        try:
            for page in result.pages:
                current_group = []
                current_text = None
                
                for line in page.lines:
                    text = line.content
                    polygon = line.polygon
                    
                    if polygon:
                        bbox = [[int(polygon[i]), int(polygon[i+1])] 
                               for i in range(0, len(polygon), 2)]
                        
                        if current_text is None:
                            current_text = text
                            current_group = []
                        
                        if text == current_text:
                            current_group.append({
                                'text': text,
                                'bbox': bbox
                            })
                        else:
                            if current_group:
                                output_data.append({
                                    'text': current_text,
                                    'instances': current_group
                                })
                            current_text = text
                            current_group = [{
                                'text': text,
                                'bbox': bbox
                            }]
                
                # 保存最后一组
                if current_group:
                    output_data.append({
                        'text': current_text,
                        'instances': current_group
                    })
                
        except Exception as e:
            print(f"处理Azure结果时出错: {str(e)}")
            raise
        return output_data

    def resize_image_if_needed(self, img_path):
        """检查并在需要时调整图片尺寸"""
        with Image.open(img_path) as img:
            width, height = img.size
            max_size = 9990
            target_size = 9900
            
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

    def calculate_projections(self, results, image_height, image_width):
        """计算水平和垂直投影"""
        h_projection = np.zeros(image_height, dtype=np.int32)
        v_projection = np.zeros(image_width, dtype=np.int32)
        
        for result in results:
            for instance in result['instances']:
                bbox = np.array(instance['bbox'])
                y_min = min(p[1] for p in bbox)
                y_max = max(p[1] for p in bbox)
                x_min = min(p[0] for p in bbox)
                x_max = max(p[0] for p in bbox)
                
                h_projection[y_min:y_max + 1] += 1
                v_projection[x_min:x_max + 1] += 1
            
        return h_projection, v_projection

    def process_single_image(self, img_path):
        try:
            raw_response_path = Path(PathConfig.OCR_PROJ_AZURE_OUTPUT) / f"{img_path.stem}_raw_response.json"
            
            if raw_response_path.exists():
                print(f"找到缓存的响应数据，正在处理 {img_path.name}")
                with open(raw_response_path, 'r', encoding='utf-8') as f:
                    result = json.load(f)
            else:
                print(f"未找到缓存数据，正在请求Azure处理 {img_path.name}")
                document_intelligence_client = DocumentIntelligenceClient(
                    endpoint=self.endpoint,
                    credential=AzureKeyCredential(self.key)
                )

                resized_image = self.resize_image_if_needed(img_path)
                image_data = resized_image if resized_image else open(img_path, "rb").read()
                
                poller = document_intelligence_client.begin_analyze_document(
                    "prebuilt-read",
                    image_data
                )
                result = poller.result()
                
                # 保存原始响应
                with open(raw_response_path, 'w', encoding='utf-8') as f:
                    result_dict = {
                        "content": result.content,
                        "pages": []
                    }
                    
                    for page in result.pages:
                        page_dict = {
                            "page_number": page.page_number,
                            "width": page.width,
                            "height": page.height,
                            "unit": page.unit,
                            "lines": [],
                            "words": []
                        }
                        
                        for line in page.lines:
                            line_dict = {
                                "content": line.content,
                                "polygon": line.polygon if line.polygon else None
                            }
                            page_dict["lines"].append(line_dict)
                        
                        for word in page.words:
                            word_dict = {
                                "content": word.content,
                                "confidence": word.confidence,
                                "polygon": word.polygon if word.polygon else None
                            }
                            page_dict["words"].append(word_dict)
                        
                        result_dict["pages"].append(page_dict)
                    
                    json.dump(result_dict, f, ensure_ascii=False, indent=2)

            ocr_results = self.process_azure_result(result)
            
            image = cv2.imread(str(img_path))
            height, width = image.shape[:2]
            
            h_projection, v_projection = self.calculate_projections(ocr_results, height, width)
            
            output_json = Path(PathConfig.OCR_PROJ_AZURE_OUTPUT) / f"{img_path.stem}_result.json"
            with open(output_json, 'w', encoding='utf-8') as f:
                json.dump(ocr_results, f, ensure_ascii=False, indent=2)
            
            output_img = self.draw_ocr_results(image, ocr_results, h_projection, v_projection)
            output_img_path = Path(PathConfig.OCR_PROJ_AZURE_OUTPUT) / f"{img_path.stem}_annotated.jpg"
            cv2.imwrite(str(output_img_path), output_img)
            
            print(f"已完成处理 {img_path.name}")
            
        except Exception as e:
            print(f"处理 {img_path.name} 时出错: {str(e)}")
            import traceback
            print(traceback.format_exc())

    def draw_ocr_results(self, image, results, h_projection, v_projection):
        """在图片上绘制OCR结果和投影图"""
        image_pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(image_pil)
        
        # 只绘制绿色边框，删除文字标注
        for result in results:
            for instance in result['instances']:
                bbox = np.array(instance['bbox'])
                points = [(int(x), int(y)) for x, y in bbox]
                draw.line([*points, points[0]], fill=(0, 255, 0), width=6)
        
        h_plot_width = 300
        h_plot_height = image.shape[0]
        h_plot_img = np.ones((h_plot_height, h_plot_width, 3), dtype=np.uint8) * 255
        
        max_h_proj = max(h_projection.max(), 1)
        for y in range(h_plot_height):
            if y < len(h_projection):
                x = int((h_projection[y] / max_h_proj) * (h_plot_width - 20))
                cv2.line(h_plot_img, (0, y), (x, y), (255, 0, 0), 1)
        
        v_plot_width = image.shape[1]
        v_plot_height = 300
        v_plot_img = np.ones((v_plot_height, v_plot_width, 3), dtype=np.uint8) * 255
        
        max_v_proj = max(v_projection.max(), 1)
        for x in range(v_plot_width):
            if x < len(v_projection):
                y = int((v_projection[x] / max_v_proj) * (v_plot_height - 20))
                cv2.line(v_plot_img, (x, v_plot_height - y - 1), (x, v_plot_height - 1), (255, 0, 0), 1)
        
        grid_color = (200, 200, 200)
        
        for i in range(0, h_plot_width, 50):
            cv2.line(h_plot_img, (i, 0), (i, h_plot_height), grid_color, 1)
        for i in range(0, h_plot_height, 50):
            cv2.line(h_plot_img, (0, i), (h_plot_width, i), grid_color, 1)
            cv2.putText(h_plot_img, f"{i}", (5, i), cv2.FONT_HERSHEY_SIMPLEX, 
                    0.5, (0, 0, 0), 1)
        
        for i in range(0, v_plot_width, 50):
            cv2.line(v_plot_img, (i, 0), (i, v_plot_height), grid_color, 1)
        for i in range(0, v_plot_height, 50):
            cv2.line(v_plot_img, (0, i), (v_plot_width, i), grid_color, 1)
        
        for i in range(0, 6):
            x = int((h_plot_width - 20) * i / 5)
            value = int((max_h_proj * i / 5))
            cv2.putText(h_plot_img, f"{value}", (x, h_plot_height - 10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
            
            y = int((v_plot_height - 20) * i / 5)
            value = int((max_v_proj * i / 5))
            cv2.putText(v_plot_img, f"{value}", (10, v_plot_height - y - 10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        
        result_img = cv2.cvtColor(np.array(image_pil), cv2.COLOR_RGB2BGR)
        combined_h = np.hstack((result_img, h_plot_img))
        v_plot_padding = np.ones((v_plot_height, h_plot_width, 3), dtype=np.uint8) * 255
        v_plot_combined = np.hstack((v_plot_img, v_plot_padding))
        final_img = np.vstack((combined_h, v_plot_combined))
        
        return final_img

    def process_all_images(self):
        """处理所有图片"""
        img_paths = []
        for ext in ['.jpg', '.jpeg', '.png']:
            img_paths.extend(list(Path(PathConfig.OCR_PROJ_AZURE_INPUT).glob(f'*{ext}')))
        
        if not img_paths:
            print("输入目录中未找到图片")
            return
        
        print(f"找到 {len(img_paths)} 张图片待处理")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(self.process_single_image, img_path) 
                      for img_path in img_paths]
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"处理图片时出错: {str(e)}")

def main():
    processor = OCRProcessor()
    processor.process_all_images()

if __name__ == '__main__':
    main()