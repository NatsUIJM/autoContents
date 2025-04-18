"""
文件名: mark_color.py (原名: 1_分颜色标记.py)
功能: 对OCR结果进行颜色标记，识别特殊文本框并标记为红色
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont
import numpy as np

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import json
import cv2
import re
import traceback

import dotenv
try:
    dotenv.load_dotenv()
except Exception as e:
    print(f"加载环境变量失败: {e}")

# 尝试加载jieba
try:
    import jieba
    jieba_available = True
except ImportError:
    print("未能导入jieba分词模块，相关功能将被跳过")
    jieba_available = False

def get_average_height(lines):
    """
    计算所有文本框的平均高度
    """
    try:
        heights = []
        for line in lines:
            coords = line.get('polygon', [])
            if len(coords) == 8:
                y1 = min(coords[1], coords[3], coords[5], coords[7])
                y2 = max(coords[1], coords[3], coords[5], coords[7])
                heights.append(y2 - y1)
        return sum(heights) / len(heights) if heights else 0
    except Exception as e:
        print(f"计算平均高度时出错: {e}")
        return 0

def clean_text(text: str) -> str:
    """
    清理文本，只保留中文字符、英文字符和数字
    """
    try:
        # 替换特殊的罗马数字字符
        roman_number_map = {
            'Ⅰ': 'I', 'Ⅱ': 'II', 'Ⅲ': 'III', 'Ⅳ': 'IV', 'Ⅴ': 'V',
            'Ⅵ': 'VI', 'Ⅶ': 'VII', 'Ⅷ': 'VIII', 'Ⅸ': 'IX', 'Ⅹ': 'X',
            '=': 'II',  # 将等号视为罗马数字II
            '貝': 'XII',  # 将貝字视为罗马数字XII
            'Ị': 'I'  # 将Ị视为罗马数字I
        }
        
        for k, v in roman_number_map.items():
            text = text.replace(k, v)
        
        # 删除所有非中文、非英文、非数字字符
        text = ''.join(char for char in text if '\u4e00' <= char <= '\u9fff' or  # 中文字符
                                              char.isalnum())  # 英文和数字
        text = text.replace('.', '').replace('·', '')  # 删除逗号和句号
        return text
    except Exception as e:
        print(f"清理文本时出错: {e}")
        return text

def is_pure_number(text: str) -> bool:
    """
    判断文本是否仅包含数字
    """
    try:
        return text.isdigit()
    except Exception as e:
        print(f"判断纯数字时出错: {e}")
        return False

def is_roman_number(text: str) -> bool:
    """
    判断文本是否是罗马数字
    """
    try:
        roman_pattern = r'^[IVXLCDMivxlcdm]+$'
        return bool(re.match(roman_pattern, text))
    except Exception as e:
        print(f"判断罗马数字时出错: {e}")
        return False

def check_page_number(text: str, coordinates: list, all_lines: list, red_boxes: list = None) -> dict:
    """
    检查文本框是否是页码
    red_boxes: 已标记为红色的文本框坐标列表
    """
    try:
        # 文本预处理
        cleaned_text = clean_text(text)
        
        result = {
            'text': text,
            'matches_pattern': False,
            'has_text_above': False,    
            'has_text_below': False,    
            'has_text_left': False,     
            'has_text_right': False,    
            'empty_directions': 0,      
            'is_page_num': False
        }
        
        # 判断是否为纯数字或罗马数字
        if not (is_pure_number(cleaned_text) or is_roman_number(cleaned_text)):
            return result
        
        x1 = min(coordinates[0], coordinates[2], coordinates[4], coordinates[6])
        y1 = min(coordinates[1], coordinates[3], coordinates[5], coordinates[7])
        x2 = max(coordinates[0], coordinates[2], coordinates[4], coordinates[6])
        y2 = max(coordinates[1], coordinates[3], coordinates[5], coordinates[7])
        
        result['matches_pattern'] = True
        
        # 页码模式 - 应用于清理后的文本
        page_num_patterns = [
            r'^[IVXLCDMivxlcdm]+$',  # 罗马数字
            r'^\d+$'  # 阿拉伯数字
        ]
        
        # 检查清理后的文本是否匹配页码模式
        result['matches_pattern'] = any(re.match(pattern, cleaned_text) for pattern in page_num_patterns)
        
        if result['matches_pattern']:
            result['empty_directions'] = 4  # 初始化为4个空白方向
            
            for line in all_lines:
                other_coords = line.get('polygon', [])
                
                # 跳过当前文本框自身或无效多边形
                if other_coords == coordinates or len(other_coords) != 8:
                    continue
                
                # 如果提供了红框列表，跳过红框
                if red_boxes and other_coords in red_boxes:
                    continue
                    
                other_x1 = min(other_coords[0], other_coords[2], other_coords[4], other_coords[6])
                other_y1 = min(other_coords[1], other_coords[3], other_coords[5], other_coords[7])
                other_x2 = max(other_coords[0], other_coords[2], other_coords[4], other_coords[6])
                other_y2 = max(other_coords[1], other_coords[3], other_coords[5], other_coords[7])
                
                # 检查四个方向
                if not result['has_text_above'] and other_y2 < y1 and max(other_x1, x1) < min(other_x2, x2):
                    result['has_text_above'] = True
                    result['empty_directions'] -= 1
                
                if not result['has_text_below'] and other_y1 > y2 and max(other_x1, x1) < min(other_x2, x2):
                    result['has_text_below'] = True
                    result['empty_directions'] -= 1
                
                if not result['has_text_left'] and other_x2 < x1 and max(other_y1, y1) < min(other_y2, y2):
                    result['has_text_left'] = True
                    result['empty_directions'] -= 1
                
                if not result['has_text_right'] and other_x1 > x2 and max(other_y1, y1) < min(other_y2, y2):
                    result['has_text_right'] = True
                    result['empty_directions'] -= 1
            
            result['is_page_num'] = (result['empty_directions'] >= 3)  # 至少要有3个方向是空白的
        
        return result
    except Exception as e:
        print(f"检查页码时出错: {e}")
        return {
            'text': text,
            'matches_pattern': False,
            'has_text_above': False,    
            'has_text_below': False,    
            'has_text_left': False,     
            'has_text_right': False,    
            'empty_directions': 0,      
            'is_page_num': False
        }

def get_original_filename():
    """
    从MARK_COLOR_INPUT_DATA目录中读取JSON文件获取原始文件名
    """
    try:
        input_data_dir = os.getenv('MARK_COLOR_INPUT_DATA')
        if not input_data_dir or not os.path.exists(input_data_dir):
            return None
        
        # 获取目录中的第一个JSON文件
        json_files = [f for f in os.listdir(input_data_dir) if f.endswith('.json')]
        if not json_files:
            return None
        
        json_path = os.path.join(input_data_dir, json_files[0])
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                original_filename = data.get('original_filename', '')
                if original_filename.endswith('.pdf'):
                    return original_filename[:-4]  # Remove .pdf extension
                return original_filename
        except Exception as e:
            print(f"读取JSON文件出错: {e}")
            return None
    except Exception as e:
        print(f"获取原始文件名时出错: {e}")
        return None
    
def check_rules(text, coordinates, page_info, image_name, all_lines):
    """
    检查文本框符合哪些规则
    返回一个字典，包含每个规则的检查结果
    """
    try:
        # 获取原始文件名
        pdf_name = get_original_filename() or image_name.split('.pdf_page_')[0]
        
        def clean_for_rules(text: str) -> str:
            """
            清理文本，删除特殊字符并进行标准化处理
            """
            try:
                # 替换特殊的罗马数字字符
                roman_number_map = {
                    'Ⅰ': 'I', 'Ⅱ': 'II', 'Ⅲ': 'III', 'Ⅳ': 'IV', 'Ⅴ': 'V',
                    'Ⅵ': 'VI', 'Ⅶ': 'VII', 'Ⅷ': 'VIII', 'Ⅸ': 'IX', 'Ⅹ': 'X',
                    '=': 'II',  # 将等号视为罗马数字II
                    '貝': 'II',  # 将貝字视为罗马数字II
                    'N': 'IV'  
                }
                
                for k, v in roman_number_map.items():
                    text = text.replace(k, v)
                
                # 移除标点符号和特殊字符
                text = re.sub(r'[^\u4e00-\u9fff\w]', '', text)
                
                # 移除括号及其内容
                text = re.sub(r'[\(（].*?[\)）]', '', text)
                text = re.sub(r'[\[【［].*?[\]】］]', '', text)
                
                # 移除版本信息
                text = re.sub(r'第[一二三四五六七八九十\d]+版', '', text)
                
                # 统一全角字符为半角
                text = ''.join([chr(ord(c) - 0xfee0) if 0xff01 <= ord(c) <= 0xff5e else c for c in text])
                
                # 转换为小写
                text = text.lower()
                
                return text
            except Exception as e:
                print(f"清理规则文本时出错: {e}")
                return text
        
        # 文本预处理
        text = text.replace(' ', '').replace('\n', '').replace('\r', '')
        
        # 获取页面尺寸
        page_width = page_info.get('width', 1000)
        page_height = page_info.get('height', 1000)
        
        # 获取边界框坐标
        if len(coordinates) != 8:
            return {
                'text': text,
                'coordinates': str(coordinates),
                'is_catalog': False,
                'is_preface': False,
                'is_page_num': False,
                'is_pdf_name': False,
                'is_planning': False,
                'empty_directions': 0,
                'near_border': False,
                'is_large_text': False
            }
        
        x1 = min(coordinates[0], coordinates[2], coordinates[4], coordinates[6])
        y1 = min(coordinates[1], coordinates[3], coordinates[5], coordinates[7])
        x2 = max(coordinates[0], coordinates[2], coordinates[4], coordinates[6])
        y2 = max(coordinates[1], coordinates[3], coordinates[5], coordinates[7])
        
        # 计算当前文本框高度和平均高度
        current_height = y2 - y1
        avg_height = get_average_height(all_lines)
        
        results = {
            'text': text,
            'coordinates': str(coordinates),
            'is_catalog': False,
            'is_preface': False,
            'is_page_num': False,
            'is_pdf_name': False,
            'is_planning': False,
            'empty_directions': 0,
            'near_border': False,
            'is_large_text': False
        }
        
        # 检查文本框高度
        if avg_height > 0 and current_height > (avg_height * 3):
            results['is_large_text'] = True
        
        # 模式定义
        catalog_patterns = [
            r'^国$', r'^目$', r'^录$', r'^目录$', 
            r'^contents$', r'^CONTENTS$',
            r'^mulu$', r'^MULU$'
        ]

        is_catalog_match = any(re.match(pattern, text, re.IGNORECASE) for pattern in catalog_patterns)
        results['is_catalog'] = is_catalog_match

        # 如果文本是单独的"目"或"录"字，尝试寻找配对的文字
        if not is_catalog_match and text in ['目', '录']:
            # 获取当前文本框的中心坐标
            current_center_x = (x1 + x2) / 2
            current_center_y = (y1 + y2) / 2
            
            # 寻找可能的配对文字
            potential_pairs = []
            for line in all_lines:
                other_text = line.get('content', '').strip()
                other_coords = line.get('polygon', [])
                
                # 跳过自身、无效多边形和非单字文本
                if (other_coords == coordinates or 
                    len(other_coords) != 8 or 
                    len(other_text) != 1 or 
                    not '\u4e00' <= other_text <= '\u9fff'):
                    continue
                
                # 计算另一个文本框的中心坐标
                other_x1 = min(other_coords[0], other_coords[2], other_coords[4], other_coords[6])
                other_y1 = min(other_coords[1], other_coords[3], other_coords[5], other_coords[7])
                other_x2 = max(other_coords[0], other_coords[2], other_coords[4], other_coords[6])
                other_y2 = max(other_coords[1], other_coords[3], other_coords[5], other_coords[7])
                other_center_x = (other_x1 + other_x2) / 2
                other_center_y = (other_y1 + other_y2) / 2
                
                # 判断是否在同一行（y坐标在20%误差范围内）
                height = y2 - y1
                if height > 0:  # 防止除零
                    y_diff_ratio = abs(current_center_y - other_center_y) / height
                    
                    # 检查相对位置
                    if y_diff_ratio <= 0.2:  # 20%误差范围
                        if text == '目' and other_text == '录' and other_center_x > current_center_x:
                            potential_pairs.append(other_coords)
                        elif text == '录' and other_text == '目' and other_center_x < current_center_x:
                            potential_pairs.append(other_coords)
            
            # 如果只找到一个匹配对象，则将当前文本框标记为目录
            if len(potential_pairs) == 1:
                results['is_catalog'] = True
                # 这里可以添加一个新的字段来标记配对的文本框，供后续处理使用
                results['catalog_pair'] = potential_pairs[0]

        preface_patterns = [
            r'^前言$', 
            r'^\（.+\）前言$', 
            r'^【.+】前言$', 
            r'^［.+］前言$', 
            r'^.+前言$', 
            r'^[.+]前言$'
        ]

        # 检查前言
        results['is_preface'] = any(re.match(pattern, text) for pattern in preface_patterns)

        # 检查页码
        page_number_result = check_page_number(text, coordinates, all_lines)
        results['is_page_num'] = page_number_result['is_page_num']
        results['empty_directions'] = page_number_result['empty_directions']

        # 检查是否靠近边界
        results['near_border'] = y1 < page_height * 0.25 or y2 > page_height * 0.85

        # 新的PDF名称检查逻辑
        if results['near_border'] and jieba_available:
            try:
                # 清理并预处理文本
                cleaned_text = clean_for_rules(text)
                cleaned_pdf_name = clean_for_rules(pdf_name)
                
                # 对清理后的文本进行分词
                text_tokens = set(jieba.cut(cleaned_text))
                text_tokens = {token for token in text_tokens if token.strip()}
                
                # 对清理后的PDF文件名进行分词
                pdf_tokens = set(jieba.cut(cleaned_pdf_name))
                pdf_tokens = {token for token in pdf_tokens if token.strip()}
                
                # 计算匹配的token数量
                matched_tokens = text_tokens.intersection(pdf_tokens)
                
                # 计算匹配率（相对于文本框中的token总量）
                if text_tokens:  # 防止除零
                    match_rate = len(matched_tokens) / len(text_tokens)
                    results['is_pdf_name'] = match_rate >= 0.7
            except Exception as e:
                print(f"PDF名称匹配检查时出错: {e}")

        # 检查规划教材标识
        planning_keywords = ['普通', '高等', '教育', '国家', '规划', '教材']
        match_count = sum(1 for keyword in planning_keywords if keyword in text)
        if planning_keywords:  # 防止除零
            results['is_planning'] = (match_count / len(planning_keywords) >= 0.8)

        return results
    except Exception as e:
        print(f"检查规则时出错: {e}")
        traceback.print_exc()
        # 返回默认值
        return {
            'text': text,
            'coordinates': str(coordinates) if coordinates else [],
            'is_catalog': False,
            'is_preface': False,
            'is_page_num': False,
            'is_pdf_name': False,
            'is_planning': False,
            'empty_directions': 0,
            'near_border': False,
            'is_large_text': False
        }

def put_chinese_text(img, text, position, color):
    """
    在图片上绘制中文文字，如果失败则跳过文字绘制
    """
    try:
        img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img_pil)
        
        # 尝试加载中文字体
        fontsize = 20
        fonts = [
            'C:\\Windows\\Fonts\\simhei.ttf',  # Windows
            'C:\\Windows\\Fonts\\simsun.ttc',  # Windows
            '/usr/share/fonts/truetype/arphic/uming.ttc',  # Ubuntu
            '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',  # Ubuntu
            '/System/Library/Fonts/PingFang.ttc',  # macOS
            '/System/Library/Fonts/STHeiti Light.ttc',  # macOS
        ]
        
        font = None
        for font_path in fonts:
            try:
                font = ImageFont.truetype(font_path, fontsize)
                break
            except:
                continue
        
        if font is None:
            print("未能加载任何中文字体，跳过文字绘制")
            return img  # 如果没有找到合适的字体，返回原图
        
        draw.text(position, text, font=font, fill=color[::-1])  # RGB转BGR
        img_opencv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        return img_opencv
    except Exception as e:
        print(f"文字绘制失败: {e}")
        return img  # 出错时返回原图

def draw_boxes(image_path, json_path, output_image_path, output_json_path):
    """
    在图像上绘制文本框并输出对应的JSON文件
    """
    try:
        # 读取图像
        image = None
        try:
            image = cv2.imread(image_path)
        except Exception as e:
            print(f"无法读取图像: {image_path}, 错误: {e}")
        
        # 读取JSON文件
        data = None
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"无法读取JSON文件: {json_path}, 错误: {e}")
            data = {'pages': [{'lines': []}]}  # 创建空数据结构
        
        # 获取页面信息和文本框信息
        page_info = data.get('pages', [{}])[0]
        lines = page_info.get('lines', [])
        image_name = os.path.basename(image_path) if image_path else "unknown"
        
        red_boxes = []
        output_data = []
        catalog_pairs = []
        
        # 第一次遍历：执行所有规则检查并标记红框
        for line in lines:
            text = line.get('content', '')
            polygon = line.get('polygon', [])
            
            if len(polygon) != 8:
                continue
            
            # 检查所有规则
            results = check_rules(text, polygon, page_info, image_name, lines)
            
            # 如果是目录文本框，且有配对项
            if results.get('is_catalog') and 'catalog_pair' in results:
                catalog_pairs.append(results['catalog_pair'])
            
            # 如果满足任何红框条件，添加到红框列表
            if any([
                results.get('is_catalog', False), 
                results.get('is_preface', False), 
                results.get('is_page_num', False), 
                results.get('is_pdf_name', False), 
                results.get('is_planning', False),
                results.get('is_large_text', False)
            ]):
                red_boxes.append(polygon)
        
        # 将配对的目录文本框添加到红框列表
        for pair in catalog_pairs:
            if pair not in red_boxes:
                red_boxes.append(pair)
        
        # 第二次遍历：对empty_directions >= 2的文本框重新检查
        for line in lines:
            text = line.get('content', '')
            polygon = line.get('polygon', [])
            
            if len(polygon) != 8:
                continue
                
            results = check_rules(text, polygon, page_info, image_name, lines)
            
            # 重新检查页码（排除红框的影响）
            if results.get('empty_directions', 0) >= 2 and polygon not in red_boxes:
                page_number_result = check_page_number(text, polygon, lines, red_boxes)
                if page_number_result.get('is_page_num', False):
                    if polygon not in red_boxes:
                        red_boxes.append(polygon)
        
        # 如果图像加载成功，处理图像
        if image is not None:
            # 绘制文本框和文字
            for line in lines:
                polygon = line.get('polygon', [])
                text = line.get('content', '')
                
                if len(polygon) != 8:
                    continue
                
                try:
                    points = np.array(polygon).reshape((-1, 2)).astype(np.int32)
                    is_red = polygon in red_boxes
                    color = (0, 0, 255) if is_red else (0, 255, 0)  # BGR格式
                    
                    # 绘制文本框
                    cv2.polylines(image, [points], True, color, 2)
                    
                    # 绘制中文文字 - 如果失败不会影响后续流程
                    x, y = points[0]
                    image = put_chinese_text(image, text, (x, y-25), color)
                except Exception as e:
                    print(f"绘制文本框失败: {e}")
            
            # 保存图像
            try:
                cv2.imwrite(output_image_path, image)
                print(f"已保存图像: {output_image_path}")
            except Exception as e:
                print(f"保存图像失败: {output_image_path}, 错误: {e}")
        else:
            print("图像处理已跳过，只生成JSON输出")
        
        # 收集JSON数据
        for line in lines:
            polygon = line.get('polygon', [])
            if len(polygon) != 8:
                continue
                
            is_red = polygon in red_boxes
            box_data = {
                "coordinates": polygon,
                "color": "red" if is_red else "green"
            }
            output_data.append(box_data)
        
        # 保存JSON
        try:
            with open(output_json_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            print(f"已保存JSON: {output_json_path}")
        except Exception as e:
            print(f"保存JSON失败: {output_json_path}, 错误: {e}")
            
    except Exception as e:
        print(f"处理失败: {e}")
        traceback.print_exc()
        
        # 即使完全失败，仍然尝试输出一个空的JSON
        try:
            with open(output_json_path, 'w', encoding='utf-8') as f:
                json.dump([], f)
            print(f"已保存空JSON: {output_json_path}")
        except:
            print(f"保存空JSON也失败了")

def process_directory(input_dir, input_image_dir, output_dir):
    """
    处理输入目录中的所有文件
    input_dir: JSON文件所在目录
    input_image_dir: JPG图像文件所在目录
    output_dir: 输出目录
    """
    try:
        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)
        
        # 遍历输入目录中的所有文件
        if not os.path.exists(input_dir):
            print(f"输入目录不存在: {input_dir}")
            return
            
        for filename in os.listdir(input_dir):
            if filename.endswith('_raw_response.json'):
                try:
                    # 获取对应的图像文件名和输出JSON文件名
                    base_name = filename.replace('_raw_response.json', '')
                    
                    # 尝试多种可能的图像扩展名
                    image_extensions = ['.jpg', '.jpeg', '.png']
                    image_path = None
                    for ext in image_extensions:
                        potential_path = os.path.join(input_image_dir, base_name + ext)
                        if os.path.exists(potential_path):
                            image_path = potential_path
                            break
                    
                    if not image_path:
                        print(f"找不到对应的图像文件: {base_name}.*")
                        # 尝试查找PDF页面格式
                        for f in os.listdir(input_image_dir):
                            if f.startswith(base_name) and any(f.endswith(ext) for ext in image_extensions):
                                image_path = os.path.join(input_image_dir, f)
                                break
                    
                    output_json_filename = base_name + '_boxes.json'
                    
                    # 构建完整的文件路径
                    json_path = os.path.join(input_dir, filename)
                    output_json_path = os.path.join(output_dir, output_json_filename)
                    
                    # 如果找到了图像文件，也生成对应的输出图像路径
                    output_image_path = ""
                    if image_path:
                        image_extension = os.path.splitext(image_path)[1]
                        output_image_path = os.path.join(output_dir, base_name + image_extension)
                    else:
                        # 如果找不到图像文件，创建一个占位路径以便函数可以继续
                        output_image_path = os.path.join(output_dir, base_name + ".jpg")
                    
                    # 处理文件
                    print(f"处理文件: {filename}")
                    draw_boxes(image_path, json_path, output_image_path, output_json_path)
                    
                except Exception as e:
                    print(f"处理文件 {filename} 时出错: {e}")
                    traceback.print_exc()
    except Exception as e:
        print(f"处理目录时出错: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    try:
        input_dir = os.getenv('MARK_COLOR_INPUT')
        input_image_dir = os.getenv('MARK_COLOR_INPUT_IMAGE')
        output_dir = os.getenv('MARK_COLOR_OUTPUT')
        input_data_dir = os.getenv('MARK_COLOR_INPUT_DATA')
        
        # 检查环境变量是否存在
        if not input_dir:
            print("环境变量 MARK_COLOR_INPUT 未设置")
            sys.exit(1)
        if not input_image_dir:
            print("环境变量 MARK_COLOR_INPUT_IMAGE 未设置")
            sys.exit(1)
        if not output_dir:
            print("环境变量 MARK_COLOR_OUTPUT 未设置")
            sys.exit(1)
            
        process_directory(input_dir, input_image_dir, output_dir)
    except Exception as e:
        print(f"执行脚本时出错: {e}")
        traceback.print_exc()