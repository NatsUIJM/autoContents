"""
文件名: abcd_marker.py (原名: 2_ABCD标记.py)
功能: 在图像上标记ABCD及其他特征点
"""
import os
import sys
import json
import logging
import traceback
from datetime import datetime
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

# 设置日志记录
def setup_logger():
    # 确保输出目录存在
    os.makedirs(ABCD_OUTPUT, exist_ok=True)
    
    # 创建日志文件名，包含时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(ABCD_OUTPUT, f"abcd_marker_{timestamp}.log")
    
    # 配置日志记录器
    logger = logging.getLogger('abcd_marker')
    logger.setLevel(logging.DEBUG)
    
    # 创建文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 创建日志格式
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # 添加处理器到日志记录器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logger()

def get_projection(boxes, min_x, max_x):
    logger.debug(f"计算投影，min_x={min_x}, max_x={max_x}")
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
        
    logger.debug(f"投影计算完成，投影数组: {projection[45:66]}")
    return projection

def find_e_point(projection, a_point, b_point):
    logger.debug(f"查找E点，A点={a_point}, B点={b_point}")
    n1 = min(projection[45:56])
    n2 = max(projection[55:66])
    
    logger.debug(f"区间[45:56]最小值={n1}, 区间[55:66]最大值={n2}, 差值={n2-n1}")
    
    if n2 - n1 >= 10:
        e_x = (a_point[0] + b_point[0]) / 2
        e_point = (e_x, a_point[1])
        logger.debug(f"找到E点: {e_point}")
        return e_point
    
    logger.debug("未找到E点，条件不满足")
    return None

def process_mx_points(mx_points, green_boxes):
    logger.debug(f"处理MX点，原始点数量: {len(mx_points)}")
    processed_points = []
    
    # 1. 移动M点位置
    for point in mx_points:
        if point['type'].startswith('M'):  # 检查是否为M点
            original_coords = point['coords']
            if point['is_upper']:  # 上方M点上移5像素
                point['coords'] = (point['coords'][0], point['coords'][1] - 5)
                logger.debug(f"{point['type']} 上移5像素: {original_coords} -> {point['coords']}")
            else:  # 下方M点下移5像素
                point['coords'] = (point['coords'][0], point['coords'][1] + 5)
                logger.debug(f"{point['type']} 下移5像素: {original_coords} -> {point['coords']}")
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
                    logger.debug(f"上方M点 {point['type']} 在 y={point['coords'][1]} 处有绿色框 (下边沿y={box_max_y})")
                    break
            if has_box_above:
                valid_points.append(point)
            else:
                logger.debug(f"上方M点 {point['type']} 在 y={point['coords'][1]} 处没有绿色框，将被移除")
        else:
            # 检查是否有绿色文本框的上边沿y值大于它
            has_box_below = False
            for box in green_boxes:
                coords = box["coordinates"]
                box_ys = [coords[i+1] for i in range(0, len(coords), 2)]
                box_min_y = min(box_ys)  # 上边沿
                if box_min_y > point['coords'][1]:
                    has_box_below = True
                    logger.debug(f"下方M点 {point['type']} 在 y={point['coords'][1]} 处有绿色框 (上边沿y={box_min_y})")
                    break
            if has_box_below:
                valid_points.append(point)
            else:
                logger.debug(f"下方M点 {point['type']} 在 y={point['coords'][1]} 处没有绿色框，将被移除")
    
    logger.debug(f"有效点数量: {len(valid_points)}，包括 {[p['type'] for p in valid_points]}")
    
    # 4. 重新编号M点
    m_points = [p for p in valid_points if p['type'].startswith('M')]
    x_points = [p for p in valid_points if p['type'].startswith('X')]
    
    # 按y坐标排序M点
    m_points.sort(key=lambda p: p['coords'][1])
    
    # 重新编号
    final_points = []
    m_count = 1
    for point in m_points:
        old_type = point['type']
        new_point = {
            'type': f'M{m_count}',
            'coords': point['coords']
        }
        logger.debug(f"重新编号: {old_type} -> {new_point['type']} 坐标: {new_point['coords']}")
        final_points.append(new_point)
        m_count += 1
    
    # 添加X点（保持原有编号）
    logger.debug(f"保留X点: {[p['type'] for p in x_points]}")
    final_points.extend(x_points)
    
    logger.debug(f"处理后的MX点数量: {len(final_points)}")
    return final_points

def find_mx_points(boxes, e_point, min_x, max_x):
    logger.debug(f"查找MX点，E点={e_point}")
    if not e_point:
        logger.debug("没有E点，不能查找MX点")
        return []
        
    e_x = e_point[0]
    mx_points = []
    
    def normalize_x(x):
        return (x - min_x) * 100 / (max_x - min_x)
    
    # 存储符合条件的文本框信息
    valid_boxes = []
    
    # 遍历所有文本框
    for idx, box in enumerate(boxes):
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
        crosses_e = (norm_min_x < normalize_x(e_x) and norm_max_x > normalize_x(e_x))
        in_exclusion_zone = ((49.5 < norm_min_x < 50) or (50 < norm_max_x < 50.5))
        
        if crosses_e and not in_exclusion_zone:
            valid_boxes.append({
                'min_y': box_min_y,
                'max_y': box_max_y,
                'center_y': (box_min_y + box_max_y) / 2,
                'idx': idx
            })
            logger.debug(f"框 #{idx} 符合条件: 跨越E点, 范围=[{norm_min_x:.1f}, {norm_max_x:.1f}], y范围=[{box_min_y}, {box_max_y}]")
        else:
            if not crosses_e:
                logger.debug(f"框 #{idx} 不跨越E点: 范围=[{norm_min_x:.1f}, {norm_max_x:.1f}], E点归一化x={normalize_x(e_x):.1f}")
            elif in_exclusion_zone:
                logger.debug(f"框 #{idx} 在排除区域: 范围=[{norm_min_x:.1f}, {norm_max_x:.1f}]")
    
    # 按中心点y坐标排序
    valid_boxes.sort(key=lambda b: b['center_y'])
    logger.debug(f"有效框数量: {len(valid_boxes)}")
    
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
        logger.debug(f"为框 #{box['idx']} 添加 M{i}(上), X{i}, M{i}(下) 点")
    
    # 应用后处理步骤
    logger.debug("开始后处理MX点")
    mx_points = process_mx_points(mx_points, [b for b in boxes if b["color"] == "green"])
            
    return mx_points

def process_file(json_file):
    logger.info(f"开始处理文件: {json_file}")
    
    try:
        # 读取JSON文件
        json_path = os.path.join(ABCD_INPUT_JSON, json_file)
        logger.debug(f"读取JSON文件: {json_path}")
        
        with open(json_path, 'r', encoding='utf-8') as f:
            boxes = json.load(f)
        
        logger.debug(f"JSON文件已加载, 框数量: {len(boxes)}")
        
        # 获取对应的JPG文件名
        jpg_file = json_file.replace("_boxes.json", ".jpg")
        jpg_path = os.path.join(ABCD_INPUT_JPG, jpg_file)
        
        if not os.path.exists(jpg_path):
            logger.error(f"找不到对应的JPG文件: {jpg_file}")
            return
        
        logger.debug(f"找到JPG文件: {jpg_path}")
        
        # 打开图片并获取原始高度
        img = Image.open(jpg_path)
        original_height = img.height
        logger.debug(f"图片尺寸: {img.width} x {original_height}")
        
        draw = ImageDraw.Draw(img)
        
        # 筛选绿色框,获取坐标
        green_boxes = [box for box in boxes if box["color"] == "green"]
        logger.debug(f"绿色框数量: {len(green_boxes)}")
        
        if not green_boxes:
            logger.warning(f"没有找到绿色框: {json_file}")
            return
            
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
        
        logger.debug(f"坐标范围: X=[{min_x}, {max_x}], Y=[{min_y}, {max_y}]")
        
        points = {
            'A': (min_x - 5, min_y),  # A点左移5像素
            'B': (max_x + 5, min_y),  # B点右移5像素
            'C': (min_x - 5, max_y),  # C点左移5像素
            'D': (max_x + 5, max_y)   # D点右移5像素
        }
        
        logger.debug(f"ABCD点初始坐标: A={points['A']}, B={points['B']}, C={points['C']}, D={points['D']}")
        
        # 计算投影并查找E点
        logger.debug("开始计算投影并查找E点")
        projection = get_projection(boxes, min_x, max_x)
        e_point = find_e_point(projection, points['A'], points['B'])
        
        if e_point:
            points['E'] = e_point
            points['F'] = (e_point[0], max_y)  # 添加F点
            logger.debug(f"E点坐标: {e_point}, F点坐标: {points['F']}")
            
            # 查找M和X点
            logger.debug("开始查找MX点")
            mx_points = find_mx_points(boxes, e_point, min_x, max_x)
            
            # 添加处理后的点到points字典
            for point in mx_points:
                points[point['type']] = point['coords']
                logger.debug(f"添加点 {point['type']}: {point['coords']}")
        else:
            logger.warning("未找到E点")
        
        # 在图片上标记点
        radius = 5
        logger.debug("开始在图片上标记点")
        
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
        output_path = os.path.join(ABCD_OUTPUT, jpg_file)
        img.save(output_path)
        logger.info(f"已保存标记图片: {output_path}")
        
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
                
            logger.debug(f"已保存点坐标JSON: {json_output_path}")
            logger.debug(f"JSON内容: {json.dumps(output_json, indent=2)}")
        
        return True
        
    except Exception as e:
        logger.error(f"处理文件 {json_file} 时出错: {str(e)}")
        logger.error(traceback.format_exc())
        return False

def main():
    logger.info("=== ABCD标记程序开始执行 ===")
    logger.info(f"输入JSON路径: {ABCD_INPUT_JSON}")
    logger.info(f"输入JPG路径: {ABCD_INPUT_JPG}")
    logger.info(f"输出路径: {ABCD_OUTPUT}")
    
    # 确保输出目录存在
    os.makedirs(ABCD_OUTPUT, exist_ok=True)
    
    # 检查输入目录是否存在
    if not os.path.exists(ABCD_INPUT_JSON):
        logger.error(f"输入JSON目录不存在: {ABCD_INPUT_JSON}")
        return
        
    if not os.path.exists(ABCD_INPUT_JPG):
        logger.error(f"输入JPG目录不存在: {ABCD_INPUT_JPG}")
        return
    
    # 获取所有JSON文件
    json_files = [f for f in os.listdir(ABCD_INPUT_JSON) if f.endswith(".json")]
    logger.info(f"找到 {len(json_files)} 个JSON文件")
    
    if not json_files:
        logger.warning("没有找到JSON文件，程序结束")
        return
    
    # 处理文件数量计数
    success_count = 0
    failed_count = 0
    
    # 遍历JSON文件
    for json_file in json_files:
        if process_file(json_file):
            success_count += 1
        else:
            failed_count += 1
    
    logger.info(f"处理完成: 成功 {success_count} 个, 失败 {failed_count} 个")
    logger.info("=== ABCD标记程序执行结束 ===")

if __name__ == "__main__":
    main()