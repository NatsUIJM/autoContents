import os
import sys
import json
import fitz  # PyMuPDF

import dotenv

# 加载环境变量
dotenv.load_dotenv()

def save_and_resize_image(pixmap, output_path, max_dimension=2000):
    """
    将 pixmap 保存为图片，并在必要时调整长边尺寸。
    逻辑：先保存原始渲染图，若尺寸超标则读取、缩放并覆盖保存。
    """
    # 1. 先保存原始渲染结果
    pixmap.save(output_path)
    
    # 2. 检查尺寸是否需要调整
    # 注意：pixmap.width 和 pixmap.height 是渲染后的实际像素
    if max(pixmap.width, pixmap.height) > max_dimension:
        # 计算缩放比例
        if pixmap.width > pixmap.height:
            scale = max_dimension / pixmap.width
        else:
            scale = max_dimension / pixmap.height
            
        new_width = int(pixmap.width * scale)
        new_height = int(pixmap.height * scale)
        
        # 使用 PyMuPDF 内置方法进行高效重采样
        # 创建一个新的缩小版的 pixmap
        resized_pixmap = pixmap.copy()
        # 这里的 resize 方法需要传入新的宽高，它会自动进行重采样
        # 注意：较新版本的 PyMuPDF 支持 pixmap.resize((w, h))
        try:
            resized_pixmap = pixmap.resize((new_width, new_height))
            resized_pixmap.save(output_path, jpg=True, jpg_quality=95)
            print(f"已调整图片尺寸：{output_path} -> {new_width}x{new_height}")
        except AttributeError:
            # 兼容旧版本：如果不存在 resize 方法，回退到 PIL 处理（需额外导入）
            # 但为了保持纯 PyMuPDF 依赖，建议升级库。此处假设环境较新。
            # 若必须兼容极旧版本，需引入 PIL，这里按标准新版处理。
            print(f"警告：当前 PyMuPDF 版本不支持直接 resize，跳过二次缩放，保留原渲染尺寸。")
            return

def convert_pdf_to_jpg():
    # 确保输出目录存在
    output_dir = os.getenv('PDF2JPG_OUTPUT')
    if not output_dir:
        print("错误：未找到环境变量 PDF2JPG_OUTPUT")
        return
    os.makedirs(output_dir, exist_ok=True)
    
    # 获取输入目录
    input_dir = os.getenv('PDF2JPG_INPUT')
    if not input_dir:
        print("错误：未找到环境变量 PDF2JPG_INPUT")
        return

    if not os.path.exists(input_dir):
        print(f"错误：输入目录不存在：{input_dir}")
        return

    pdf_files = [f for f in os.listdir(input_dir) 
                 if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        print(f"在目录 {input_dir} 中未找到任何 PDF 文件。")
        return

    # 目标 DPI 设置
    target_dpi = 300
    # PyMuPDF 默认基准约为 72 DPI，计算缩放倍数
    zoom = target_dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    for pdf_file in pdf_files:
        pdf_path = os.path.join(input_dir, pdf_file)
        pdf_name = os.path.splitext(pdf_file)[0]
        json_path = os.path.join(input_dir, f"{pdf_name}.json")
        
        print(f"\n处理文件：{pdf_file}")
        
        # 验证 JSON 文件
        if not os.path.exists(json_path):
            print(f"未找到对应的 JSON 文件：{json_path}，跳过此文件。")
            continue
            
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
                
            toc_start = json_data['toc_start']
            toc_end = json_data['toc_end']
            
        except (json.JSONDecodeError, KeyError) as e:
            print(f"JSON 文件读取或解析错误 ({json_path}): {e}")
            continue

        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            
            # 校验页码范围 (用户页码通常从 1 开始，PyMuPDF 从 0 开始)
            if toc_start < 1 or toc_end > total_pages or toc_start > toc_end:
                print(f"页码范围无效 [{toc_start}-{toc_end}]，文件总页数：{total_pages}。跳过。")
                doc.close()
                continue

            saved_images = []

            # 遍历指定页码范围
            for page_num in range(toc_start, toc_end + 1):
                # 转换为 0-based index
                page_index = page_num - 1
                
                if page_index < 0 or page_index >= total_pages:
                    print(f"警告：页码 {page_num} 超出范围，跳过。")
                    continue

                page = doc[page_index]
                
                # 生成图像
                pix = page.get_pixmap(matrix=mat, alpha=False)
                
                output_path = os.path.join(
                    output_dir,
                    f"{pdf_name}_page_{page_num}.jpg"
                )
                
                # 保存并处理尺寸
                save_and_resize_image(pix, output_path, max_dimension=2000)
                saved_images.append(output_path)
                
                # 释放当前页面资源，避免内存堆积
                del pix
                del page

            doc.close()
            print(f"完成处理：{len(saved_images)} 张图片已保存至 {output_dir}")

        except Exception as e:
            print(f"处理文件 {pdf_file} 时发生严重错误：{e}")
            # 尝试关闭文档以防资源泄露
            try:
                doc.close()
            except:
                pass
            continue

if __name__ == "__main__":
    try:
        convert_pdf_to_jpg()
        print("\n所有文件处理完成!")
    except Exception as e:
        print(f"程序执行出错：{e}")