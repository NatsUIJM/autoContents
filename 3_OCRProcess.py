import os
import json
from pathlib import Path
import easyocr
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

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
    
    # 遍历图片目录，支持常见图片格式
    input_dir = Path('2_outputPic')
    supported_formats = ('*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff')
    for format in supported_formats:
        for img_path in input_dir.glob(format):
            # 读取图片
            image = cv2.imread(str(img_path))
            
            # 执行OCR
            results = reader.readtext(image)
            
            # 转换结果为JSON格式
            json_results = []
            for (bbox, text, prob) in results:
                # 将numpy数组转换为普通list以便JSON序列化
                bbox = np.array(bbox).tolist()
                
                result_dict = {
                    'text': text,
                    'confidence': float(prob),
                    'bbox': bbox  # bbox格式: [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                }
                json_results.append(result_dict)
                
            # 保存JSON结果
            json_path = output_dir / f"{img_path.stem}.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_results, f, ensure_ascii=False, indent=2)
            
            # 绘制并保存带标注的图片
            output_img = draw_ocr_results(image, results)
            img_output_path = output_dir / f"{img_path.stem}_annotated.jpg"
            cv2.imwrite(str(img_output_path), output_img)
                
            print(f"Processed {img_path.name}")

if __name__ == '__main__':
    main()