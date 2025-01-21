import os
import json
from PIL import Image
import numpy as np
from typing import Dict, List, Tuple
import logging

class ImageProcessor:
    def __init__(self, input_dir: str, json_dir: str, output_dir: str, info_dir: str):
        self.input_dir = input_dir
        self.json_dir = json_dir
        self.output_dir = output_dir
        self.info_dir = info_dir
        self.setup_dirs()
        self.setup_logging()

    def setup_dirs(self):
        """创建必要的目录"""
        for dir_path in [self.output_dir, self.info_dir]:
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)

    def setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            filename=os.path.join(self.info_dir, 'process.log'),
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

    def crop_main_rectangle(self, image: Image.Image, points: Dict) -> Image.Image:
        """根据ABCD点裁切主矩形"""
        left = points['A']['x']
        top = points['A']['y']
        right = points['B']['x']
        bottom = points['D']['y']
        cropped = image.crop((left, top, right, bottom))
        cropped.save(os.path.join(self.info_dir, "1_main_rectangle.png"))
        return cropped

    def get_horizontal_splits(self, points: Dict) -> List[int]:
        """获取水平分割点"""
        splits = []
        # 收集所有M点的y坐标
        for key in points.keys():
            if key.startswith('M'):
                splits.append(points[key]['y'])
        splits.sort()
        return splits

    def get_vertical_split_info(self, points: Dict, y_start: float, y_end: float) -> Tuple[bool, float]:
        """判断是否需要垂直分割"""
        # 检查是否有X点在当前水平区域内
        has_x_point = False
        for key in points.keys():
            if key.startswith('X'):
                y = points[key]['y']
                if y_start <= y <= y_end:
                    has_x_point = True
                    break
        return (not has_x_point, points['E']['x'])

    def split_image(self, image: Image.Image, points: Dict) -> List[Image.Image]:
        """分割图片"""
        result_images = []
        
        # 获取水平分割点
        h_splits = self.get_horizontal_splits(points)
        h_splits = [points['A']['y']] + h_splits + [points['C']['y']]
        
        # 逐段处理
        for i in range(len(h_splits) - 1):
            y_start = h_splits[i]
            y_end = h_splits[i + 1]
            
            # 裁切水平段
            segment = image.crop((0, y_start - points['A']['y'], 
                                image.width, y_end - points['A']['y']))
            
            # 保存中间结果
            segment.save(os.path.join(self.info_dir, f"2_horizontal_segment_{i}.png"))
            
            # 检查是否需要垂直分割
            needs_split, split_x = self.get_vertical_split_info(points, y_start, y_end)
            
            if needs_split:
                # 垂直分割
                left_part = segment.crop((0, 0, split_x - points['A']['x'], segment.height))
                right_part = segment.crop((split_x - points['A']['x'], 0, segment.width, segment.height))
                
                # 保存中间结果
                left_part.save(os.path.join(self.info_dir, f"3_vertical_left_{i}.png"))
                right_part.save(os.path.join(self.info_dir, f"3_vertical_right_{i}.png"))
                
                result_images.extend([left_part, right_part])
            else:
                result_images.append(segment)
        
        return result_images

    def concatenate_images(self, images: List[Image.Image]) -> Image.Image:
        """垂直拼接图片，将所有图片等比例缩放到最大宽度"""
        if not images:
            return None
            
        # 找出最大宽度
        max_width = max(img.width for img in images)
        
        # 等比例缩放所有图片
        scaled_images = []
        total_height = 0
        
        for img in images:
            if img.width != max_width:
                # 计算缩放比例
                scale_ratio = max_width / img.width
                new_height = int(img.height * scale_ratio)
                # 使用LANCZOS重采样方法进行高质量缩放
                scaled_img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                scaled_images.append(scaled_img)
                total_height += new_height
            else:
                scaled_images.append(img)
                total_height += img.height
        
        # 创建最终图像
        result = Image.new('RGB', (max_width, total_height), 'white')
        y_offset = 0
        
        # 拼接图像
        for img in scaled_images:
            result.paste(img, (0, y_offset))
            y_offset += img.height
            
        return result

    def process_image(self, image_path: str):
        """处理单个图片"""
        try:
            # 加载图片和JSON数据
            image_name = os.path.basename(image_path)
            json_path = self.get_corresponding_json(image_name)
            if not json_path:
                logging.error(f"No corresponding JSON found for {image_name}")
                return

            image = Image.open(image_path)
            json_data = self.load_json_data(json_path)
            
            # 主要处理步骤
            cropped = self.crop_main_rectangle(image, json_data['points'])
            split_images = self.split_image(cropped, json_data['points'])
            final_image = self.concatenate_images(split_images)
            
            # 保存结果
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
    processor = ImageProcessor(
        input_dir='1_picMark/inputPic',
        json_dir='1_picMark/picJSON',
        output_dir='2_outputPic',
        info_dir='info'
    )
    processor.process_all_images()

if __name__ == "__main__":
    main()