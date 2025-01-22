import os
import json
from pathlib import Path
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
import concurrent.futures

def is_pure_number(text):
    """检查文本是否为纯数字"""
    return text.replace('.', '').isdigit()

def should_skip_merge(bbox, image_width, text):
    """检查是否应该跳过合并"""
    # 获取文本框左端的x坐标
    left_x = bbox[0][0]
    # 如果文本框在图片右侧60%区域内且内容为纯数字，则跳过合并
    return left_x > (image_width * 0.6) and is_pure_number(text)

def merge_line_texts(results, image_height, image_width):
    """使用水平投影的方法合并同一行的文本"""
    # 创建投影数组
    projection = np.zeros(image_height, dtype=np.int32)
    
    # 分离需要合并的文本框和独立的数字文本框
    merge_candidates = []
    independent_numbers = []
    
    for result in results:
        bbox, text, prob = result
        if should_skip_merge(bbox, image_width, text):
            independent_numbers.append(result)
        else:
            merge_candidates.append(result)
            # 只对需要合并的文本框进行投影
            bbox = np.array(bbox, dtype=np.int32)
            y_min = max(0, bbox[:, 1].min())
            y_max = min(image_height - 1, bbox[:, 1].max())
            projection[y_min:y_max + 1] += 1
    
    # 找出投影为0的位置，即行间距
    zero_positions = np.where(projection == 0)[0]
    
    # 如果开头不是0，添加0位置
    if len(zero_positions) == 0 or zero_positions[0] != 0:
        zero_positions = np.concatenate(([0], zero_positions))
    
    # 如果结尾不是0，添加最后一个位置
    if zero_positions[-1] != image_height - 1:
        zero_positions = np.concatenate((zero_positions, [image_height - 1]))
    
    # 根据零位置分组
    merged_results = []
    for i in range(len(zero_positions) - 1):
        line_start = zero_positions[i]
        line_end = zero_positions[i + 1]
        
        # 找出属于这一行的文本框
        line_texts = []
        for result in merge_candidates:
            bbox = np.array(result[0], dtype=np.int32)
            text_center_y = (bbox[:, 1].min() + bbox[:, 1].max()) / 2
            
            if line_start <= text_center_y <= line_end:
                line_texts.append(result)
        
        if line_texts:
            # 按x坐标排序
            line_texts.sort(key=lambda x: x[0][0][0])
            
            # 合并文本和边界框
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
    
    # 将合并结果和独立的数字文本框合并到最终结果中
    final_results = merged_results + independent_numbers
    
    # 按y坐标排序最终结果
    final_results.sort(key=lambda x: x[0][0][1])
    
    return final_results

def draw_ocr_results(image, results):
    """在图片上绘制OCR结果"""
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
    
    for (bbox, text, prob) in results:
        # 将bbox转换为整数坐标
        bbox = np.array(bbox, dtype=np.int32)
        
        # 绘制矩形框 (加粗到6像素)
        draw.line([tuple(bbox[0]), tuple(bbox[1]), tuple(bbox[2]), tuple(bbox[3]), tuple(bbox[0])],
                 fill=(0, 255, 0), width=6)
        
        # 在框上方添加文本
        x = bbox[0][0]
        y = bbox[0][1] - 50  # 增加文本与框的距离
        
        # 获取文本大小
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        
        # 绘制白色背景
        draw.rectangle(
            [x, y - text_height - 4, x + text_width, y + 4],
            fill=(255, 255, 255)
        )
        
        # 绘制文本
        draw.text((x, y - text_height), text, font=font, fill=(0, 0, 0))
    
    # 转换回OpenCV格式
    output_img = cv2.cvtColor(np.array(image_pil), cv2.COLOR_RGB2BGR)
    return output_img

def process_image(img_path, json_dir, output_dir):
    """处理单张图片的OCR并保存结果"""
    # 读取图片
    image = cv2.imread(str(img_path))
    height, width = image.shape[:2]
    
    # 读取对应的JSON文件
    json_path = json_dir / f"{img_path.stem}.json"
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            json_results = json.load(f)
    except FileNotFoundError:
        print(f"Warning: JSON file not found for {img_path.name}")
        return
    
    # 转换JSON结果为程序所需格式
    results = []
    for item in json_results:
        results.append((
            np.array(item['bbox']),
            item['text'],
            1.0  # 使用默认信度值1.0
        ))
    
    # 合并同一行的文本
    merged_results = merge_line_texts(results, height, width)
    
    # 绘制并保存带标注的图片
    output_img = draw_ocr_results(image, merged_results)
    img_output_path = output_dir / f"{img_path.stem}_annotated.jpg"
    cv2.imwrite(str(img_output_path), output_img)
        
    print(f"Processed {img_path.name}")

def main():
    # 创建输出目录
    output_dir = Path('3_OCRInfo')
    output_dir.mkdir(exist_ok=True)
    
    # JSON文件目录
    json_dir = Path('3_1_OCRServiceBack')
    
    # 遍历图片目录
    input_dir = Path('2_outputPic')
    img_paths = list(input_dir.glob('*.jpg'))
    
    # 使用多线程处理图片
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_image, img_path, json_dir, output_dir) 
                  for img_path in img_paths]
        for future in concurrent.futures.as_completed(futures):
            future.result()

if __name__ == '__main__':
    main()