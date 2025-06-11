"""
文件名: ocr_processor.py (原名: 3_3_OCRProcess.py)
功能: OCR结果后处理，包括文本行合并与可视化
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import os
import json
from pathlib import Path
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
import concurrent.futures
import io

import dotenv
dotenv.load_dotenv()

def is_dot_between_numbers(text, index):
    """检查某个位置的点是否在两个数字之间（忽略空格）"""
    if index <= 0 or index >= len(text) - 1:
        return False
    
    # 向左查找第一个非空格字符
    left_idx = index - 1
    while left_idx >= 0 and text[left_idx].isspace():
        left_idx -= 1
    if left_idx < 0:
        return False
    
    # 向右查找第一个非空格字符
    right_idx = index + 1
    while right_idx < len(text) and text[right_idx].isspace():
        right_idx += 1
    if right_idx >= len(text):
        return False
    
    return text[left_idx].isdigit() and text[right_idx].isdigit()
def clean_text(text):
    """清理文本中的点，但保留数字之间的点"""
    result = ""
    i = 0
    while i < len(text):
        char = text[i]
        if char in ['.', '·', '…', '●','•', '。']:
            if is_dot_between_numbers(text, i):
                result += char
        else:
            result += char
        i += 1
    return result

def is_pure_number(text):
    """检查文本是否为纯数字或被括号包围的数字"""
    # 移除首尾的括号（如果存在）
    text = text.strip()
    if len(text) >= 2 and text[0] in "({[<" and text[-1] in ")}]>":
        text = text[1:-1].strip()
    
    return text.replace('.', '').replace('·', '').replace('…', '').replace('●', '').replace('•', '').replace('。', '').isdigit()

def is_short_english(text):
    """检查是否为5个以下的纯英文字符"""
    text = text.strip()
    return (len(text) < 5 and 
            text.replace(' ', '').isascii() and 
            text.replace(' ', '').isalpha())

def has_text_box_on_right(current_bbox, all_bboxes, margin=50):
    """检查当前文本框右侧是否有其他文本框"""
    current_right = current_bbox[1][0]  # 当前文本框右边界的x坐标
    current_y_center = (current_bbox[0][1] + current_bbox[2][1]) / 2  # 当前文本框的y轴中心

    for other_bbox in all_bboxes:
        if np.array_equal(current_bbox, other_bbox):
            continue

        other_left = other_bbox[0][0]  # 其他文本框左边界的x坐标
        other_y_center = (other_bbox[0][1] + other_bbox[2][1]) / 2  # 其他文本框的y轴中心

        if (other_left > current_right and 
            abs(other_y_center - current_y_center) <= margin):
            return True
    return False

def should_skip_merge(bbox, all_bboxes, text):
    """检查是否应该跳过合并"""
    return is_pure_number(text) and not has_text_box_on_right(bbox, all_bboxes)

def merge_line_texts(results, image_height, image_width):
    """使用水平投影的方法合并同一行的文本"""
    # 过滤掉短英文文本框
    filtered_results = []
    for result in results:
        bbox, text, prob = result
        if is_short_english(text):
            continue
        
        # 清理文本中的点
        cleaned_text = clean_text(text)
        filtered_results.append((bbox, cleaned_text, prob))
    
    # 创建投影数组
    projection = np.zeros(image_height, dtype=np.int32)
    
    # 获取所有文本框
    all_bboxes = [result[0] for result in filtered_results]
    
    # 分离需要合并的文本框和独立的数字文本框
    merge_candidates = []
    independent_numbers = []
    
    for result in filtered_results:
        bbox, text, prob = result
        if should_skip_merge(bbox, all_bboxes, text):
            independent_numbers.append(result)
        else:
            merge_candidates.append(result)
            y_min, y_max = calculate_reduced_height_box(bbox)
            y_min = max(0, int(y_min))
            y_max = min(image_height - 1, int(y_max))
            projection[y_min:y_max + 1] += 1
    
    # 找出投影值为0或1的位置，作为分割线
    split_positions = np.where((projection == 0))[0]
    
    if len(split_positions) == 0 | split_positions[0] != 0:
        split_positions = np.concatenate(([0], split_positions))
    
    if split_positions[-1] != image_height - 1:
        split_positions = np.concatenate((split_positions, [image_height - 1]))
    
    # 寻找连续的分割位置的起始和结束点
    line_boundaries = []
    start_idx = 0
    for i in range(1, len(split_positions)):
        if split_positions[i] != split_positions[i-1] + 1:
            line_boundaries.append((split_positions[start_idx], split_positions[i-1]))
            start_idx = i
    if start_idx < len(split_positions):
        line_boundaries.append((split_positions[start_idx], split_positions[-1]))
    
    # 找出分割线之间的非分割区域（即文本行所在区域）
    text_regions = []
    for i in range(len(line_boundaries)-1):
        current_end = line_boundaries[i][1]
        next_start = line_boundaries[i+1][0]
        if next_start - current_end > 1:
            text_regions.append((current_end + 1, next_start - 1))
    
    # 根据文本区域分组
    merged_results = []
    for region_start, region_end in text_regions:
        line_texts = []
        for result in merge_candidates:
            bbox = np.array(result[0], dtype=np.int32)
            text_center_y = (bbox[:, 1].min() + bbox[:, 1].max()) / 2
            
            if region_start <= text_center_y <= region_end:
                line_texts.append(result)
        
        if line_texts:
            line_texts.sort(key=lambda x: x[0][0][0])
            
            merged_text = ""
            merged_bbox = []
            merged_prob = 0
            
            for i, (box, txt, p) in enumerate(line_texts):
                merged_text += txt
                if i == 0:
                    merged_bbox.extend([box[0], box[1]])
                if i == len(line_texts) - 1:
                    merged_bbox.extend([box[2], box[3]])
                merged_prob += p
            
            merged_prob /= len(line_texts)
            merged_results.append((np.array(merged_bbox), merged_text, merged_prob))
    
    final_results = merged_results + independent_numbers
    final_results.sort(key=lambda x: x[0][0][1])
    
    return final_results, projection

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

def resize_image_if_needed(image):
    """检查并在需要时调整图片尺寸"""
    height, width = image.shape[:2]
    max_size = 8150
    target_size = 8000
    
    if width > max_size or height > max_size:
        if width > height:
            if width > max_size:
                ratio = target_size / width
                new_width = target_size
                new_height = int(height * ratio)
        else:
            if height > max_size:
                ratio = target_size / height
                new_height = target_size
                new_width = int(width * ratio)
        
        resized_image = cv2.resize(image, (new_width, new_height), 
                                 interpolation=cv2.INTER_LANCZOS4)
        return resized_image
    
    return image

def should_skip_merge(bbox, all_bboxes, text):
    """检查是否应该跳过合并"""
    # 如果是纯数字且右侧没有其他文本框，则跳过合并
    return is_pure_number(text) and not has_text_box_on_right(bbox, all_bboxes)

def merge_line_texts(results, image_height, image_width):
    """使用水平投影的方法合并同一行的文本"""
    # 过滤掉短英文文本框并清理文本中的点
    filtered_results = []
    for result in results:
        bbox, text, prob = result
        # 过滤短英文
        if is_short_english(text):
            continue
        
        # 清理文本中的点
        cleaned_text = clean_text(text)
        filtered_results.append((bbox, cleaned_text, prob))
    
    # 创建投影数组
    projection = np.zeros(image_height, dtype=np.int32)
    
    # 获取所有文本框
    all_bboxes = [result[0] for result in filtered_results]
    
    # 分离需要合并的文本框和独立的数字文本框
    merge_candidates = []
    independent_numbers = []
    
    for result in filtered_results:
        bbox, text, prob = result
        if should_skip_merge(bbox, all_bboxes, text):
            independent_numbers.append(result)
        else:
            merge_candidates.append(result)
            y_min, y_max = calculate_reduced_height_box(bbox)
            y_min = max(0, int(y_min))
            y_max = min(image_height - 1, int(y_max))
            projection[y_min:y_max + 1] += 1
    
    # 找出投影值为0或1的位置，作为分割线
    split_positions = np.where((projection == 0))[0]
    
    if len(split_positions) == 0 | split_positions[0] != 0:
        split_positions = np.concatenate(([0], split_positions))
    
    if split_positions[-1] != image_height - 1:
        split_positions = np.concatenate((split_positions, [image_height - 1]))
    
    # 寻找连续的分割位置的起始和结束点
    line_boundaries = []
    start_idx = 0
    for i in range(1, len(split_positions)):
        if split_positions[i] != split_positions[i-1] + 1:
            line_boundaries.append((split_positions[start_idx], split_positions[i-1]))
            start_idx = i
    if start_idx < len(split_positions):
        line_boundaries.append((split_positions[start_idx], split_positions[-1]))
    
    # 找出分割线之间的非分割区域（即文本行所在区域）
    text_regions = []
    for i in range(len(line_boundaries)-1):
        current_end = line_boundaries[i][1]
        next_start = line_boundaries[i+1][0]
        if next_start - current_end > 1:
            text_regions.append((current_end + 1, next_start - 1))
    
    # 根据文本区域分组
    merged_results = []
    for region_start, region_end in text_regions:
        line_texts = []
        for result in merge_candidates:
            bbox = np.array(result[0], dtype=np.int32)
            text_center_y = (bbox[:, 1].min() + bbox[:, 1].max()) / 2
            
            if region_start <= text_center_y <= region_end:
                line_texts.append(result)
        
        if line_texts:
            line_texts.sort(key=lambda x: x[0][0][0])
            
            merged_text = ""
            merged_bbox = []
            merged_prob = 0
            
            for i, (box, txt, p) in enumerate(line_texts):
                merged_text += txt
                if i == 0:
                    merged_bbox.extend([box[0], box[1]])
                if i == len(line_texts) - 1:
                    merged_bbox.extend([box[2], box[3]])
                merged_prob += p
            
            merged_prob /= len(line_texts)
            merged_results.append((np.array(merged_bbox), merged_text, merged_prob))
    
    final_results = merged_results + independent_numbers
    final_results.sort(key=lambda x: x[0][0][1])
    
    return final_results, projection

def draw_ocr_results(image, results, projection):
    """在图片上绘制OCR结果并添加投影曲线图"""
    # 转换为PIL Image以便使用中文字体
    image_pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image_pil)
    
    # macOS的系统字体路径
    font_paths = [
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc"
    ]
    
    # 尝试加载字体
    font = None
    for font_path in font_paths:
        try:
            font = ImageFont.truetype(font_path, 45)
            break
        except:
            continue
    
    # 如果所有字体都失败，使用默认字体
    if font is None:
        font = ImageFont.load_default()
    
    # 绘制OCR结果
    for (bbox, text, prob) in results:
        bbox = np.array(bbox, dtype=np.int32)
        draw.line([tuple(bbox[0]), tuple(bbox[1]), tuple(bbox[2]), tuple(bbox[3]), tuple(bbox[0])],
                 fill=(0, 255, 0), width=6)
        
        x = bbox[0][0]
        y = bbox[0][1] - 10
        
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        
        draw.rectangle(
            [x, y - text_height - 4, x + text_width, y + 4],
            fill=(255, 255, 255)
        )
        
        draw.text((x, y - text_height), text, font=font, fill=(0, 0, 0))
    
    # 创建投影曲线图
    plot_width = 300  # 曲线图宽度
    plot_height = image.shape[0]  # 与原图等高
    plot_img = np.ones((plot_height, plot_width, 3), dtype=np.uint8) * 255  # 白色背景
    
    # 计算投影值的最大值用于归一化
    max_proj = np.max(projection) if np.max(projection) > 0 else 1
    
    # 绘制网格线
    grid_color = (200, 200, 200)
    for i in range(0, plot_width, 50):
        cv2.line(plot_img, (i, 0), (i, plot_height), grid_color, 1)
    for i in range(0, plot_height, 50):
        cv2.line(plot_img, (0, i), (plot_width, i), grid_color, 1)
    
    # 绘制投影曲线
    for y in range(plot_height):
        if y < len(projection):
            x = int((projection[y] / max_proj) * (plot_width - 20))  # 留出右边距
            cv2.line(plot_img, (0, y), (x, y), (255, 0, 0), 1)
    
    # 绘制刻度和数值
    font_scale = 0.5
    font_thickness = 1
    # Y轴刻度（每100像素一个刻度）
    for y in range(0, plot_height, 100):
        cv2.putText(plot_img, f"{y}", (5, y), cv2.FONT_HERSHEY_SIMPLEX, 
                   font_scale, (0, 0, 0), font_thickness)
    
    # X轴刻度（投影值）
    for i in range(0, 6):
        x = int((plot_width - 20) * i / 5)
        value = int((max_proj * i / 5))
        cv2.putText(plot_img, f"{value}", (x, plot_height - 10), 
                   cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), font_thickness)
    
    # 将OCR结果图和投影曲线图横向拼接
    ocr_img = cv2.cvtColor(np.array(image_pil), cv2.COLOR_RGB2BGR)
    combined_img = np.hstack((ocr_img, plot_img))
    
    return combined_img

def calculate_reduced_height_box(bbox, reduction_percent=0.2):
    """计算缩减高度后的文本框范围"""
    # 将bbox转换为numpy数组以便计算
    bbox = np.array(bbox)
    
    # 计算当前文本框的上下边界和中心位置
    y_min = bbox[:, 1].min()
    y_max = bbox[:, 1].max()
    height = y_max - y_min
    center_y = (y_max + y_min) / 2
    
    # 计算缩减后的高度
    reduced_height = height * (1 - reduction_percent)
    
    # 计算新的上下边界
    new_y_min = center_y - (reduced_height / 2)
    new_y_max = center_y + (reduced_height / 2)
    
    return new_y_min, new_y_max

def process_image(img_path, json_dir, output_dir):
    """处理单张图片的OCR并保存结果"""
    # 读取图片
    image = cv2.imread(str(img_path))
    
    # 读取对应的JSON文件
    json_path = Path(json_dir) / f"{img_path.stem}.json"
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            json_results = json.load(f)
    except FileNotFoundError:
        print(f"警告: 未找到图片{img_path.name}对应的JSON文件")
        return

    # 转换JSON结果为程序所需格式
    results = []
    for item in json_results:
        results.append((
            np.array(item['bbox']),
            item['text'],
            1.0  # 使用默认信度值1.0
        ))
    
    # 获取合并结果和投影数组
    merged_results, projection = merge_line_texts(results, image.shape[0], image.shape[1])
    
    # 转换结果为JSON格式
    json_results = []
    for (bbox, text, prob) in merged_results:
        bbox = np.array(bbox).tolist()
        result_dict = {
            'text': text,
            'bbox': bbox
        }
        json_results.append(result_dict)
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 保存合并后的JSON结果
    merged_json_path = Path(output_dir) / f"{img_path.stem}_merged.json"
    with open(merged_json_path, 'w', encoding='utf-8') as f:
        json.dump(json_results, f, ensure_ascii=False, indent=2)
    
    # 在绘制之前检查并调整图片尺寸
    display_image = resize_image_if_needed(image)
    
    # 绘制带标注的图片和投影曲线图
    output_img = draw_ocr_results(display_image, merged_results, projection)
    img_output_path = Path(output_dir) / f"{img_path.stem}_annotated.jpg"
    cv2.imwrite(str(img_output_path), output_img)
    
    print(f"已处理完成: {img_path.name}")

def main():
    # 确保输出目录存在
    output_dir = os.getenv('OCRPROCESS_OUTPUT_1')
    os.makedirs(output_dir, exist_ok=True)
    
    # 遍历图片目录
    input_dir = os.getenv('OCRPROCESS_INPUT_1')
    img_paths = list(Path(input_dir).glob('*.jpg'))
    
    # 使用多线程处理图片
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(
                process_image,
                img_path,
                os.getenv('OCRPROCESS_INPUT_2'),
                output_dir
            ) for img_path in img_paths
        ]
        for future in concurrent.futures.as_completed(futures):
            future.result()

if __name__ == '__main__':
    main()