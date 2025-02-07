"""
文件名: abcd_marker.py (原名: 2_ABCD标记.py)
功能: 在图像上标记ABCD及其他特征点
"""
import os
import sys
import json
from PIL import Image, ImageDraw
import numpy as np

# 添加项目根目录到系统路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

import dotenv
dotenv.load_dotenv()

# 从环境变量获取路径配置
ABCD_OUTPUT = os.getenv('ABCD_OUTPUT', 'output/abcd')
ABCD_INPUT_JSON = os.getenv('ABCD_INPUT_JSON', 'input/abcd/json')
ABCD_INPUT_JPG = os.getenv('ABCD_INPUT_JPG', 'input/abcd/jpg')

def get_projection(boxes, min_x, max_x):
    def normalize_x(x):
        return (x - min_x) * 100 / (max_x - min_x)
    
    projection = np.zeros(101)
    
    for box in boxes:
        coords = box["coordinates"]
        box_xs = [coords[i] for i in range(0, len(coords), 2)]
        box_min_x = min(box_xs)
        box_max_x = max(box_xs)
        
        start_idx = int(normalize_x(box_min_x))
        end_idx = int(normalize_x(box_max_x))
        projection[start_idx:end_idx+1] += 1
        
    return projection

def find_e_point(projection, a_point, b_point):
    n1 = min(projection[45:56])
    n2 = max(projection[55:66])
    
    if n2 - n1 >= 5:
        e_x = (a_point[0] + b_point[0]) / 2
        return (e_x, a_point[1])
    return None

def process_mx_points(mx_points, green_boxes):
    processed_points = []
    
    # 1. 移动M点位置
    for point in mx_points:
        if point['type'].startswith('M'):  # 检查是否为M点
            if point['is_upper']:  # 上方M点上移5像素
                point['coords'] = (point['coords'][0], point['coords'][1] - 5)
            else:  # 下方M点下移5像素
                point['coords'] = (point['coords'][0], point['coords'][1] + 5)
        processed_points.append(point)
    
    # 2&3. 检查M点是否有对应的绿色文本框
    valid_points = []
    for point in processed_points:
        if not point['type'].startswith('M'):
            valid_points.append(point)
            continue
            
        if point['is_upper']:
            # 检查是否有绿色文本框的下边沿y值小于它
            has_box_above = False
            for box in green_boxes:
                coords = box["coordinates"]
                box_ys = [coords[i+1] for i in range(0, len(coords), 2)]
                box_max_y = max(box_ys)  # 下边沿
                if box_max_y < point['coords'][1]:
                    has_box_above = True
                    break
            if has_box_above:
                valid_points.append(point)
        else:
            # 检查是否有绿色文本框的上边沿y值大于它
            has_box_below = False
            for box in green_boxes:
                coords = box["coordinates"]
                box_ys = [coords[i+1] for i in range(0, len(coords), 2)]
                box_min_y = min(box_ys)  # 上边沿
                if box_min_y > point['coords'][1]:
                    has_box_below = True
                    break
            if has_box_below:
                valid_points.append(point)
    
    # 4. 重新编号M点
    m_points = [p for p in valid_points if p['type'].startswith('M')]
    x_points = [p for p in valid_points if p['type'].startswith('X')]
    
    # 按y坐标排序M点
    m_points.sort(key=lambda p: p['coords'][1])
    
    # 重新编号
    final_points = []
    m_count = 1
    for point in m_points:
        new_point = {
            'type': f'M{m_count}',
            'coords': point['coords']
        }
        final_points.append(new_point)
        m_count += 1
    
    # 添加X点（保持原有编号）
    final_points.extend(x_points)
    
    return final_points

def find_mx_points(boxes, e_point, min_x, max_x):
    if not e_point:
        return []
        
    e_x = e_point[0]
    mx_points = []
    
    def normalize_x(x):
        return (x - min_x) * 100 / (max_x - min_x)
    
    # 存储符合条件的文本框信息
    valid_boxes = []
    
    # 遍历所有文本框
    for box in boxes:
        coords = box["coordinates"]
        box_xs = [coords[i] for i in range(0, len(coords), 2)]
        box_ys = [coords[i+1] for i in range(0, len(coords), 2)]
        
        box_min_x = min(box_xs)
        box_max_x = max(box_xs)
        box_min_y = min(box_ys)
        box_max_y = max(box_ys)
        
        # 归一化坐标
        norm_min_x = normalize_x(box_min_x)
        norm_max_x = normalize_x(box_max_x)
        
        # 检查是否跨越E点且不在排除区域
        if (norm_min_x < normalize_x(e_x) and norm_max_x > normalize_x(e_x) and
            not (47.5 < norm_min_x < 50) and not (50 < norm_max_x < 52.5)):
            valid_boxes.append({
                'min_y': box_min_y,
                'max_y': box_max_y,
                'center_y': (box_min_y + box_max_y) / 2
            })
    
    # 按中心点y坐标排序
    valid_boxes.sort(key=lambda b: b['center_y'])
    
    # 为每个有效的文本框添加点
    for i, box in enumerate(valid_boxes, 1):
        # 添加上方的M点
        mx_points.append({
            'type': f'M{i}',
            'coords': (e_x, box['min_y']),
            'is_upper': True
        })
        
        # 添加X点
        mx_points.append({
            'type': f'X{i}',
            'coords': (e_x, box['center_y'])
        })
        
        # 添加下方的M点
        mx_points.append({
            'type': f'M{i}',
            'coords': (e_x, box['max_y']),
            'is_upper': False
        })
    
    # 应用后处理步骤
    mx_points = process_mx_points(mx_points, [b for b in boxes if b["color"] == "green"])
            
    return mx_points

def main():
    # 确保输出目录存在
    os.makedirs(ABCD_OUTPUT, exist_ok=True)
    
    # 遍历JSON文件
    for json_file in os.listdir(ABCD_INPUT_JSON):
        if not json_file.endswith(".json"):
            continue
            
        # 读取JSON文件
        with open(os.path.join(ABCD_INPUT_JSON, json_file), 'r', encoding='utf-8') as f:
            boxes = json.load(f)
        
        # 获取对应的JPG文件名
        jpg_file = json_file.replace("_boxes.json", ".jpg")
        jpg_path = os.path.join(ABCD_INPUT_JPG, jpg_file)
        
        if not os.path.exists(jpg_path):
            print(f"找不到对应的JPG文件: {jpg_file}")
            continue
        
        # 打开图片并获取原始高度
        img = Image.open(jpg_path)
        original_height = img.height
        draw = ImageDraw.Draw(img)
        
        # 筛选绿色框,获取坐标
        green_boxes = [box for box in boxes if box["color"] == "green"]
        
        if not green_boxes:
            print(f"没有找到绿色框: {json_file}")
            continue
            
        # 获取所有x和y坐标
        all_x = []
        all_y = []
        for box in green_boxes:
            coords = box["coordinates"]
            for i in range(0, len(coords), 2):
                all_x.append(coords[i])
                all_y.append(coords[i+1])
                
        # 计算ABCD点坐标
        min_x = min(all_x)
        max_x = max(all_x)
        min_y = min(all_y)
        max_y = max(all_y)
        
        points = {
            'A': (min_x - 5, min_y),  # A点左移5像素
            'B': (max_x + 5, min_y),  # B点右移5像素
            'C': (min_x - 5, max_y),  # C点左移5像素
            'D': (max_x + 5, max_y)   # D点右移5像素
        }
        
        # 计算投影并查找E点
        projection = get_projection(boxes, min_x, max_x)
        e_point = find_e_point(projection, points['A'], points['B'])
        if e_point:
            points['E'] = e_point
            points['F'] = (e_point[0], max_y)  # 添加F点
            
            # 查找M和X点
            mx_points = find_mx_points(boxes, e_point, min_x, max_x)
            
            # 添加处理后的点到points字典
            for point in mx_points:
                points[point['type']] = point['coords']
        
        # 在图片上标记点
        radius = 5
        for label, (x, y) in points.items():
            # 根据点类型选择颜色
            if label in ['E', 'F']:
                color = 'green'
            elif label.startswith(('M', 'X')):
                color = 'blue'
            else:
                color = 'red'
                
            # 画点
            draw.ellipse([x-radius, y-radius, x+radius, y+radius], fill=color)
            # 添加标签
            draw.text((x+radius+2, y-radius), label, fill=color)
        
        # 保存标记后的图片
        img.save(os.path.join(ABCD_OUTPUT, jpg_file))
        print(f"已处理: {jpg_file}")
        
        # 保存所有点的坐标信息到JSON文件（新格式）
        if points:
            output_json = {
                "original_height": original_height,
                "points": {
                    label: {
                        "x": float(coord[0]), 
                        "y": float(coord[1])
                    } 
                    for label, coord in points.items()
                }
            }
            json_output_path = os.path.join(ABCD_OUTPUT, jpg_file.replace('.jpg', '.json'))
            with open(json_output_path, 'w', encoding='utf-8') as f:
                json.dump(output_json, f, indent=2)

    print("处理完成")

if __name__ == "__main__":
    main()