"""
文件名: image_preprocessor.py (原名: 2_picProcess.py)
功能: 处理图像，包括裁剪、分割和拼接操作
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import os
import json
from PIL import Image
import numpy as np
from typing import Dict, List, Tuple
import logging

import dotenv
dotenv.load_dotenv()

class ImageProcessor:
    def __init__(self):
        self.input_dir = os.getenv('IMAGE_PREPROCESSOR_INPUT')
        self.json_dir = os.getenv('IMAGE_PREPROCESSOR_JSON')
        self.output_dir = os.getenv('IMAGE_PREPROCESSOR_OUTPUT')
        self.cut_dir = os.getenv('IMAGE_PREPROCESSOR_CUT')
        self.setup_dirs()
        self.setup_logging()

    def setup_dirs(self):
        """创建必要的目录"""
        for dir_path in [self.output_dir, self.cut_dir]:
            os.makedirs(dir_path, exist_ok=True)

    def setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(message)s'
        )

    def load_json_data(self, json_path: str) -> Dict:
        """加载JSON文件"""
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_corresponding_json(self, image_name: str) -> str:
        """获取对应的JSON文件路径"""
        base_name = os.path.splitext(image_name)[0]
        json_path = os.path.join(self.json_dir, f"{base_name}.json")
        return json_path if os.path.exists(json_path) else None

    def crop_main_rectangle(self, image: Image.Image, points: Dict, image_name: str) -> Image.Image:
        """根据ABCD点裁切主矩形"""
        left = points['A']['x']
        top = points['A']['y']
        right = points['B']['x']
        bottom = points['D']['y']
        cropped = image.crop((left, top, right, bottom))
        # 保存主矩形到cut_dir
        cropped.save(os.path.join(self.cut_dir, image_name))
        return cropped

    def get_horizontal_splits(self, points: Dict) -> List[int]:
        """获取水平分割点，如果没有M点则返回空列表"""
        splits = []
        for key in points.keys():
            if key.startswith('M') and 'y' in points[key]:
                # 只添加 Y 坐标大于 A 点的 M 点
                if points[key]['y'] > points['A']['y']:
                    splits.append(points[key]['y'])
        splits.sort()
        return splits

    def get_vertical_split_info(self, points: Dict, y_start: float, y_end: float) -> Tuple[bool, float]:
        """判断是否需要垂直分割"""
        if 'E' not in points or 'x' not in points['E']:
            return (False, 0)
        
        for key in points.keys():
            if key.startswith('X'):
                if 'y' in points[key]:
                    y = points[key]['y']
                    if y_start <= y <= y_end:
                        return (False, 0)
        
        return (True, points['E']['x'])

    def split_image(self, image: Image.Image, points: Dict) -> List[Image.Image]:
        """分割图片"""
        result_images = []
        
        h_splits = self.get_horizontal_splits(points)
        h_splits = [points['A']['y']] + h_splits + [points['D']['y']]
        
        for i in range(len(h_splits) - 1):
            y_start = h_splits[i]
            y_end = h_splits[i + 1]
            
            segment = image.crop((0, y_start - points['A']['y'], 
                                image.width, y_end - points['A']['y']))
            
            needs_split, split_x = self.get_vertical_split_info(points, y_start, y_end)
            
            if needs_split and split_x > 0:
                left_part = segment.crop((0, 0, split_x - points['A']['x'], segment.height))
                right_part = segment.crop((split_x - points['A']['x'], 0, segment.width, segment.height))
                result_images.extend([left_part, right_part])
            else:
                result_images.append(segment)
        
        return result_images

    def concatenate_images(self, images: List[Image.Image]) -> Image.Image:
        """垂直拼接图片，将所有图片等比例缩放到最大宽度"""
        if not images:
            return None
            
        max_width = max(img.width for img in images)
        scaled_images = []
        total_height = 0
        
        for img in images:
            if img.width != max_width:
                scale_ratio = max_width / img.width
                new_height = int(img.height * scale_ratio)
                scaled_img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                scaled_images.append(scaled_img)
                total_height += new_height
            else:
                scaled_images.append(img)
                total_height += img.height
        
        result = Image.new('RGB', (max_width, total_height), 'white')
        y_offset = 0
        
        for img in scaled_images:
            result.paste(img, (0, y_offset))
            y_offset += img.height
            
        return result

    def process_image(self, image_path: str):
        """处理单个图片"""
        try:
            image_name = os.path.basename(image_path)
            json_path = self.get_corresponding_json(image_name)
            if not json_path:
                logging.error(f"No corresponding JSON found for {image_name}")
                return

            image = Image.open(image_path)
            json_data = self.load_json_data(json_path)
            
            cropped = self.crop_main_rectangle(image, json_data['points'], image_name)
            split_images = self.split_image(cropped, json_data['points'])
            final_image = self.concatenate_images(split_images)
            
            output_path = os.path.join(self.output_dir, image_name)
            final_image.save(output_path)
            logging.info(f"Successfully processed {image_name}")
            
        except Exception as e:
            logging.error(f"Error processing {image_name}: {str(e)}")

    def process_all_images(self):
        """处理所有图片"""
        for filename in os.listdir(self.input_dir):
            if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                image_path = os.path.join(self.input_dir, filename)
                self.process_image(image_path)

def main():
    processor = ImageProcessor()
    processor.process_all_images()

if __name__ == "__main__":
    main()