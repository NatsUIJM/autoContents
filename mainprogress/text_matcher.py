"""
文件名: text_matcher.py (修改版)
功能: 匹配文本和数字对，基于水平投影判定同一行
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import json
import os
from pathlib import Path
import numpy as np

import dotenv
dotenv.load_dotenv()

def is_pure_number(text):
    """检查文本是否为纯数字"""
    return text.replace('.', '').isdigit()

def calculate_reduced_height_box(bbox, reduction_percent=0.2):
    """计算缩减高度后的文本框范围"""
    bbox = np.array(bbox)
    y_min = bbox[:, 1].min()
    y_max = bbox[:, 1].max()
    height = y_max - y_min
    center_y = (y_max + y_min) / 2
    reduced_height = height * (1 - reduction_percent)
    new_y_min = center_y - (reduced_height / 2)
    new_y_max = center_y + (reduced_height / 2)
    return new_y_min, new_y_max

def create_horizontal_projection(bboxes, image_height):
    """创建水平投影数组"""
    projection = np.zeros(image_height, dtype=np.int32)
    
    for bbox in bboxes:
        y_min, y_max = calculate_reduced_height_box(bbox)
        y_min = max(0, int(y_min))
        y_max = min(image_height - 1, int(y_max))
        projection[y_min:y_max + 1] += 1
        
    return projection

def find_text_pairs(results, image_height):
    """识别文本配对，基于水平投影判定同一行"""
    # 过滤掉非纯数字的文本（右侧数字）
    text_boxes = []
    number_boxes = []
    
    for result in results:
        bbox = result['bbox']
        text = result['text']
        
        if is_pure_number(text):
            number_boxes.append({
                'text': text,
                'bbox': bbox
            })
        else:
            text_boxes.append({
                'text': text,
                'bbox': bbox
            })
    
    # 创建投影数组
    all_bboxes = [result['bbox'] for result in results]
    projection = create_horizontal_projection(all_bboxes, image_height)
    
    # 寻找分割线
    split_positions = np.where((projection == 0))[0]

    if len(split_positions) == 0 or split_positions[0] != 0:
        split_positions = np.concatenate([[0], split_positions])

    if split_positions[-1] != image_height - 1:
        split_positions = np.concatenate((split_positions, [image_height - 1]))

    # 寻找连续的分割线区间
    line_boundaries = []
    start_idx = 0
    for i in range(1, len(split_positions)):
        if split_positions[i] != split_positions[i-1] + 1:
            line_boundaries.append((split_positions[start_idx], split_positions[i-1]))
            start_idx = i
    if start_idx < len(split_positions):
        line_boundaries.append((split_positions[start_idx], split_positions[-1]))

    # 找出文本行区域
    text_regions = []
    for i in range(len(line_boundaries)-1):
        current_end = line_boundaries[i][1]
        next_start = line_boundaries[i+1][0]
        if next_start - current_end > 1:
            text_regions.append((current_end + 1, next_start - 1))

    # 配对结果
    paired_results = []

    # 为每个文本行区域匹配文本和数字
    for region_start, region_end in text_regions:
        # 获取在当前行的文本框
        region_text_boxes = []
        for text_box in text_boxes:
            bbox = np.array(text_box['bbox'], dtype=np.int32)
            text_center_y = (bbox[:, 1].min() + bbox[:, 1].max()) / 2
            if region_start <= text_center_y <= region_end:
                region_text_boxes.append(text_box)

        # 获取在当前行的数字框
        region_number_boxes = []
        for number_box in number_boxes:
            bbox = np.array(number_box['bbox'], dtype=np.int32)
            number_center_y = (bbox[:, 1].min() + bbox[:, 1].max()) / 2
            if region_start <= number_center_y <= region_end:
                region_number_boxes.append(number_box)

        # 匹配文本和数字
        for text_box in region_text_boxes:
            pair = {'text': text_box['text'], 'number': None}
            for number_box in region_number_boxes:
                pair['number'] = number_box['text']
                region_number_boxes.remove(number_box)  # 防止重复匹配
                break
            paired_results.append(pair)

        # 添加未配对的数字
        for number_box in region_number_boxes:
            paired_results.append({'text': None, 'number': number_box['text']})

    return paired_results

def main():
    # 创建输出目录
    output_dir = Path(os.getenv('TEXT_MATCHER_OUTPUT'))
    output_dir.mkdir(exist_ok=True)
    
    # 遍历OCR结果文件
    input_dir = Path(os.getenv('TEXT_MATCHER_INPUT'))
    for json_path in input_dir.glob('*.json'):
        # 跳过标注图片的文件名
        if json_path.stem.endswith('_annotated'):
            continue
            
        # 读取JSON文件
        with open(json_path, 'r', encoding='utf-8') as f:
            ocr_results = json.load(f)
        
        # 获取图片高度信息（假设所有文本框都在同一张图片上）
        image_height = max(max(point[1] for point in result['bbox']) for result in ocr_results)
        
        # 执行配对
        paired_results = find_text_pairs(ocr_results, image_height)
        
        # 保存配对结果
        output_path = output_dir / json_path.name
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(paired_results, f, ensure_ascii=False, indent=2)
        
        print(f"Processed {json_path.name}")

if __name__ == '__main__':
    main()
