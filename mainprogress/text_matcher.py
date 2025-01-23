"""
文件名: text_matcher.py (原名: 4_matchText.py)
功能: 匹配文本和数字对，生成配对结果
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import json
import os
from pathlib import Path
import numpy as np
from config.paths import PathConfig

def is_pure_number(text):
    """检查文本是否为纯数字"""
    return text.replace('.', '').isdigit()

def is_right_side_number(bbox, image_width, text):
    """检查是否为右侧数字"""
    # 获取文本框左端的x坐标
    left_x = bbox[0][0]
    # 如果文本框在图片右侧60%区域内且内容为纯数字，则为右侧数字
    return left_x > (image_width * 0.6) and is_pure_number(text)

def find_text_pairs(results):
    """识别文本配对"""
    # 获取所有文本框的最大x坐标作为图片宽度参考
    max_x = max(max(box[0] for box in result['bbox']) for result in results)
    
    # 分离文本和数字
    text_boxes = []
    number_boxes = []
    
    for result in results:
        bbox = result['bbox']
        text = result['text']
        
        if is_right_side_number(bbox, max_x, text):
            number_boxes.append({
                'text': text,
                'y_center': (min(point[1] for point in bbox) + max(point[1] for point in bbox)) / 2
            })
        else:
            text_boxes.append({
                'text': text,
                'y_center': (min(point[1] for point in bbox) + max(point[1] for point in bbox)) / 2
            })
    
    # 对文本框按y坐标排序
    text_boxes.sort(key=lambda x: x['y_center'])
    number_boxes.sort(key=lambda x: x['y_center'])
    
    # 配对结果
    paired_results = []
    
    # 为每个文本框找到最近的数字框
    for text_box in text_boxes:
        pair = {'text': text_box['text'], 'number': None}
        min_distance = float('inf')
        
        for number_box in number_boxes:
            distance = abs(text_box['y_center'] - number_box['y_center'])
            if distance < min_distance:
                min_distance = distance
                # 只有当垂直距离在合理范围内时才配对
                if distance < 50:  # 可以调整这个阈值
                    pair['number'] = number_box['text']
        
        paired_results.append(pair)
    
    # 添加未配对的数字
    for number_box in number_boxes:
        is_paired = False
        for pair in paired_results:
            if pair['number'] == number_box['text']:
                is_paired = True
                break
        
        if not is_paired:
            paired_results.append({'text': None, 'number': number_box['text']})
    
    return paired_results

def main():
    # 创建输出目录
    output_dir = Path(PathConfig.TEXT_MATCHER_OUTPUT)
    output_dir.mkdir(exist_ok=True)
    
    # 遍历OCR结果文件
    input_dir = Path(PathConfig.TEXT_MATCHER_INPUT)
    for json_path in input_dir.glob('*.json'):
        # 跳过标注图片的文件名
        if json_path.stem.endswith('_annotated'):
            continue
            
        # 读取JSON文件
        with open(json_path, 'r', encoding='utf-8') as f:
            ocr_results = json.load(f)
        
        # 执行配对
        paired_results = find_text_pairs(ocr_results)
        
        # 保存配对结果
        output_path = output_dir / json_path.name
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(paired_results, f, ensure_ascii=False, indent=2)
        
        print(f"Processed {json_path.name}")

if __name__ == '__main__':
    main()