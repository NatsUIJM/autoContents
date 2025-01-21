import os
import json
from pathlib import Path
import easyocr
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

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

def main():
    # 初始化OCR reader (只需运行一次)
    reader = easyocr.Reader(['ch_sim','en'])
    
    # 创建输出目录
    output_dir = Path('3_OCRInfo')
    output_dir.mkdir(exist_ok=True)
    
    # 遍历图片目录
    input_dir = Path('2_outputPic')
    for img_path in input_dir.glob('*.jpg'):
        # 读取图片
        image = cv2.imread(str(img_path))
        height, width = image.shape[:2]
        
        # 执行OCR
        results = reader.readtext(image)
        
        # 合并同一行的文本
        merged_results = merge_line_texts(results, height, width)
        
        # 转换结果为JSON格式
        json_results = []
        for (bbox, text, prob) in merged_results:
            # 将numpy数组转换为普通list以便JSON序列化
            bbox = np.array(bbox).tolist()
            
            result_dict = {
                'text': text,
                'confidence': float(prob),
                'bbox': bbox
            }
            json_results.append(result_dict)
            
        # 保存JSON结果
        json_path = output_dir / f"{img_path.stem}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_results, f, ensure_ascii=False, indent=2)
        
        # 绘制并保存带标注的图片
        output_img = draw_ocr_results(image, merged_results)
        img_output_path = output_dir / f"{img_path.stem}_annotated.jpg"
        cv2.imwrite(str(img_output_path), output_img)
            
        print(f"Processed {img_path.name}")

if __name__ == '__main__':
    main()