import os
import json
import fitz  # PyMuPDF
import dotenv

# 加载环境变量
dotenv.load_dotenv()

def convert_pdf_to_jpg():
    output_dir = os.getenv('PDF2JPG_OUTPUT')
    if not output_dir:
        print("错误：未找到环境变量 PDF2JPG_OUTPUT")
        return
    os.makedirs(output_dir, exist_ok=True)
    
    input_dir = os.getenv('PDF2JPG_INPUT')
    if not input_dir:
        print("错误：未找到环境变量 PDF2JPG_INPUT")
        return

    if not os.path.exists(input_dir):
        print(f"错误：输入目录不存在：{input_dir}")
        print(f"当前工作目录：{os.getcwd()}")
        return

    pdf_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        print(f"在目录 {input_dir} 中未找到任何 PDF 文件。")
        return

    print(f"发现 {len(pdf_files)} 个 PDF 文件待处理。")

    # 配置项
    TARGET_LONG_EDGE = 1500  # 目标长边像素
    # 建议：对于小尺寸PDF，1500像素可能仍然不够清晰，通常建议至少 200-300 DPI
    # 72 DPI -> 1500px 意味着放大倍数约为 1500/355 ≈ 4.2倍
    
    processed_count = 0

    for pdf_file in pdf_files:
        pdf_path = os.path.join(input_dir, pdf_file)
        pdf_name = os.path.splitext(pdf_file)[0]
        json_path = os.path.join(input_dir, f"{pdf_name}.json")
        
        print(f"\n--- 开始处理：{pdf_file} ---")
        
        # 验证 JSON 文件
        if not os.path.exists(json_path):
            print(f"  [跳过] 未找到对应的 JSON 文件：{json_path}")
            continue
            
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
                
            toc_start = json_data.get('toc_start')
            toc_end = json_data.get('toc_end')
            
            if toc_start is None or toc_end is None:
                raise KeyError("缺少 'toc_start' 或 'toc_end' 字段")
                
            print(f"  [配置] 目标页码范围：[{toc_start}, {toc_end}]")
            
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  [错误] JSON 解析失败 ({json_path}): {e}")
            continue

        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            print(f"  [信息] PDF 总页数：{total_pages}")
            
            # 校验逻辑诊断
            if toc_start < 1:
                print(f"  [跳过] 起始页码 {toc_start} 小于 1。")
                doc.close()
                continue
            if toc_end > total_pages:
                print(f"  [跳过] 结束页码 {toc_end} 超出总页数 {total_pages}。")
                doc.close()
                continue
            if toc_start > toc_end:
                print(f"  [跳过] 起始页码 {toc_start} 大于结束页码 {toc_end}。")
                doc.close()
                continue

            saved_images = []
            range_count = toc_end - toc_start + 1
            print(f"  [计划] 即将转换 {range_count} 页...")

            # 遍历指定页码范围
            for page_num in range(toc_start, toc_end + 1):
                page_index = page_num - 1
                
                # 二次防御性检查
                if page_index < 0 or page_index >= total_pages:
                    print(f"  [警告] 内部循环检测到页码 {page_num} 越界，跳过。")
                    continue

                page = doc[page_index]
                
                # 1. 获取页面原始尺寸 (Points, 1/72 inch)
                rect = page.rect
                original_width = rect.width
                original_height = rect.height
                
                if original_width == 0 or original_height == 0:
                    print(f"  [警告] 第 {page_num} 页尺寸为 0，跳过。")
                    continue
                
                # 2. 计算缩放比例 (修正逻辑)
                # 目标：让长边等于 TARGET_LONG_EDGE
                current_long_edge = max(original_width, original_height)
                
                # 始终计算缩放因子，即使原图很小也要放大
                zoom = TARGET_LONG_EDGE / current_long_edge
                
                # 可选：设置最小缩放倍数，防止极度微小的页面被放大到失真
                # if zoom < 1.0: zoom = 1.0  # 如果希望只放大不缩小，取消注释此行
                
                # 构建渲染矩阵
                mat = fitz.Matrix(zoom, zoom)
                
                # 3. 执行渲染
                # alpha=False 生成 JPG 所需的不透明图像
                pix = page.get_pixmap(matrix=mat, alpha=False)
                
                output_path = os.path.join(
                    output_dir,
                    f"{pdf_name}_page_{page_num}.jpg"
                )
                
                # 4. 保存图片
                # dpi 参数仅用于元数据，不影响实际像素大小，实际大小由 matrix 决定
                pix.save(output_path)
                
                # 计算等效 DPI 用于日志展示，方便调试
                # 原始尺寸是 72 DPI，放大 zoom 倍后，等效 DPI = 72 * zoom
                effective_dpi = 72 * zoom
                
                print(f"  [完成] 第 {page_num} 页 -> {pix.width}x{pix.height} | Zoom: {zoom:.2f}x | Eff. DPI: {effective_dpi:.0f}")
                
                saved_images.append(output_path)
                
                # 显式释放资源
                del pix
                del page
                
                # 进度反馈
                if range_count <= 10 or (page_num - toc_start + 1) % 10 == 0:
                    print(f"  [进度] 批次内已处理 {page_num - toc_start + 1}/{range_count} 页")

            doc.close()
            print(f"  [完成] 本文件共保存 {len(saved_images)} 张图片。")
            processed_count += len(saved_images)

        except Exception as e:
            print(f"  [严重错误] 处理文件 {pdf_file} 时异常：{e}")
            import traceback
            traceback.print_exc()
            try:
                doc.close()
            except:
                pass
            continue

    print(f"\n=== 全部任务结束 ===")
    print(f"总计生成图片数量：{processed_count}")

if __name__ == "__main__":
    try:
        convert_pdf_to_jpg()
    except Exception as e:
        print(f"程序主入口出错：{e}")
        import traceback
        traceback.print_exc()