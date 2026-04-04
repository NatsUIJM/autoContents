import os
import sys
import io
import json
import base64
import re
import random
import asyncio
import logging
import threading
import traceback
from collections import Counter
from pathlib import Path
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
from openai import AsyncOpenAI
import dotenv

dotenv.load_dotenv()

# 动态获取项目根目录，确保在 subprocess 中路径解析绝对正确
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.append(PROJECT_ROOT)

def write_log(message):
    """写入日志到项目根目录的 log.txt (复用 llm_level_adjuster.py 逻辑)"""
    try:
        log_file = Path(PROJECT_ROOT) / "log.txt"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{threading.current_thread().name}] {message}\n")
    except Exception as e:
        print(f"日志写入失败：{e}")

# 配置日志输出到标准输出，确保 subprocess 能完整捕获
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

def get_api_key(raw_key: str) -> str:
    """解析 API Key，支持环境变量提取"""
    if raw_key.startswith("$") and raw_key.endswith("$"):
        env_var_name = raw_key[1:-1]
        return os.environ.get(env_var_name, "")
    return raw_key

def create_concat_image_b64(doc: fitz.Document, start_p: int, end_p: int, save_path: str = None) -> str:
    """将指定范围的 PDF 页面转换为横向拼接的 JPG，并在底部追加页码。"""
    images = []
    page_nums = []
    
    for p in range(start_p - 1, end_p):
        if p >= len(doc): 
            break
        page = doc[p]
        rect = page.rect
        max_dim = max(rect.width, rect.height)
        zoom = 1500.0 / max_dim if max_dim > 1500 else 1.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)
        page_nums.append(p + 1)

    if not images:
        return None

    max_h = max(img.height for img in images)
    total_w = sum(img.width for img in images)
    new_h = int(max_h * 1.2)

    combined = Image.new("RGB", (total_w, new_h), "white")
    draw = ImageDraw.Draw(combined)

    try:
        font_size = max(40, int(max_h * 0.05))
        font = ImageFont.load_default(size=font_size)
    except TypeError:
        font = ImageFont.load_default()

    current_x = 0
    for img, p_num in zip(images, page_nums):
        combined.paste(img, (current_x, 0))
        text = f"Page {p_num}"
        
        if hasattr(font, 'getbbox'):
            bbox = font.getbbox(text)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
        else:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

        text_x = current_x + (img.width - text_w) // 2
        text_y = max_h + (new_h - max_h) // 2 - text_h // 2
        
        draw.text((text_x, text_y), text, fill="black", font=font)
        current_x += img.width

    if save_path:
        combined.save(save_path, format="JPEG", quality=85)
        logger.debug(f"拼接图片已保存至：{save_path}")
        write_log(f"拼接图片已保存至：{save_path}")

    buffered = io.BytesIO()
    combined.save(buffered, format="JPEG", quality=85)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

async def fetch_toc_from_image(client: AsyncOpenAI, model: str, b64_img: str, start_p: int, end_p: int, raw_save_path: str = None) -> str:
    """调用 LLM 识别拼接图片中的目录范围，并保存原始响应"""
    prompt = f"""这是一张由 5 个连续的 PDF 页面横向拼接而成的图片。每张图片下方标注了它的物理页码（例如 Page {start_p}）。
请找出这几页中，属于目录的起始页码和结束页码。

【目录的严格定义】：一页中必须存在多个“标题 - 页码”对。如果某一页没有这个特征（例如纯文本正文、封面、版权页、序言），则它绝对不是目录。

【输出要求】：
1. 仅输出 JSON 格式，不要包含任何 markdown 标记（如 ```json ）、解释或额外文本。
2. 如果这几页中存在目录，输出格式为：{{"toc_start": 起始页码，"toc_end": 结束页码}}
3. 如果这几页中没有任何一页是目录，输出格式为：{{"toc_start": null, "toc_end": null}}"""

    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}},
                        {"type": "text", "text": prompt}
                    ]
                }
            ],
            extra_body={"enable_thinking": False}
        )
        raw_content = completion.choices[0].message.content.strip()
        
        if raw_save_path:
            response_data = {
                "page_range": f"{start_p}-{end_p}",
                "raw_response": raw_content,
                "model": model
            }
            with open(raw_save_path, 'w', encoding='utf-8') as f:
                json.dump(response_data, f, ensure_ascii=False, indent=2)
            logger.debug(f"原始响应已保存至：{raw_save_path}")
            write_log(f"原始响应已保存至：{raw_save_path}")
            
        return raw_content
    except Exception as e:
        error_msg = f"获取目录范围失败 ({start_p}-{end_p}): {e}"
        logger.error(error_msg)
        write_log(error_msg)
        if raw_save_path:
            with open(raw_save_path, 'w', encoding='utf-8') as f:
                json.dump({"error": str(e), "page_range": f"{start_p}-{end_p}"}, f, ensure_ascii=False, indent=2)
        return ""

def parse_toc_json(text: str) -> tuple:
    """安全解析 LLM 输出的 JSON，剥离 Markdown 标记"""
    if not text:
        return None, None
    try:
        clean_text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
        clean_text = re.sub(r'\s*```$', '', clean_text, flags=re.MULTILINE)
        data = json.loads(clean_text)
        return data.get("toc_start"), data.get("toc_end")
    except Exception as e:
        error_msg = f"解析目录 JSON 失败：{e}, 原始文本：{text}"
        logger.error(error_msg)
        write_log(error_msg)
        return None, None

async def extract_toc_info(pdf_path: str, client: AsyncOpenAI, model: str, initial_data_dir: str) -> tuple:
    """分批次提取目录起始和结束页"""
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    
    global_toc_start = None
    global_toc_end = None
    
    write_log(f"开始提取目录信息，总页数：{total_pages}")
    
    for batch_start in range(1, 61, 20):
        batch_end = min(batch_start + 19, total_pages)
        if batch_start > total_pages:
            break
            
        info_msg = f"正在分析目录范围：第 {batch_start} 到 {batch_end} 页"
        print(f"[INFO] {info_msg}")
        write_log(info_msg)
        
        tasks = []
        
        for i in range(4):
            sub_start = batch_start + i * 5
            sub_end = min(sub_start + 4, batch_end)
            if sub_start > batch_end:
                break
                
            img_filename = f"concat_pages_{sub_start}_{sub_end}.jpg"
            img_save_path = os.path.join(initial_data_dir, img_filename)
            
            raw_filename = f"toc_response_{sub_start}_{sub_end}.json"
            raw_save_path = os.path.join(initial_data_dir, raw_filename)
            
            b64_img = create_concat_image_b64(doc, sub_start, sub_end, save_path=img_save_path)
            if b64_img:
                tasks.append(fetch_toc_from_image(client, model, b64_img, sub_start, sub_end, raw_save_path=raw_save_path))
                
        if not tasks:
            break
            
        results = await asyncio.gather(*tasks)
        
        batch_toc_pages = []
        for res in results:
            start, end = parse_toc_json(res)
            if isinstance(start, int) and isinstance(end, int):
                batch_toc_pages.extend([start, end])
                
        if batch_toc_pages:
            current_batch_min = min(batch_toc_pages)
            current_batch_max = max(batch_toc_pages)
            
            if global_toc_start is None:
                global_toc_start = current_batch_min
            global_toc_end = current_batch_max
            
            if global_toc_end == batch_end and batch_end < 60 and batch_end < total_pages:
                continue
            else:
                break
        else:
            if global_toc_start is not None:
                break

    doc.close()

    if global_toc_end == 60:
        warn_msg = "目录识别达到 60 页上限，触发熔断，强制设置为 1 和 2"
        print(f"[WARNING] {warn_msg}")
        write_log(warn_msg)
        return 1, 2

    return global_toc_start, global_toc_end

async def extract_book_name(pdf_path: str, original_filename: str, client: AsyncOpenAI, model: str) -> str:
    """提取 PDF 第一页并调用 LLM 识别书名"""
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]
        rect = page.rect
        max_dim = max(rect.width, rect.height)
        zoom = 1000.0 / max_dim if max_dim > 1000 else 1.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("jpeg")
        doc.close()
        
        base64_image = base64.b64encode(img_data).decode('utf-8')
        image_data_url = f"data:image/jpeg;base64,{base64_image}"
        
        prompt = f"这是 PDF 文件的第一页。该文件的原始文件名为：{original_filename}。请结合图片内容和原始文件名，识别并输出这本书的书名。只需输出书名文本，不要包含任何其他说明、标点或多余内容。"
        
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                        {"type": "text", "text": prompt}
                    ]
                }
            ],
            extra_body={"enable_thinking": False}
        )
        
        book_name = completion.choices[0].message.content.strip()
        book_name = re.sub(r'[\\/:*?"<>|]', '_', book_name)
        return book_name
    except Exception as e:
        error_msg = f"识别书名失败：{str(e)}"
        logger.error(error_msg)
        write_log(error_msg)
        return ""

async def fetch_single_offset(client: AsyncOpenAI, model: str, page_num: int, b64_img: str) -> str:
    """调用 LLM 识别单页的页码偏移量"""
    prompt = f"""你是一个专业的文档页码识别专家。你的任务是识别图片中页面底部或顶部标注的实际印刷页码，并计算正文偏移量。
计算公式：正文偏移量 = PDF 物理页码 - 印刷页码。

当前图片的 PDF 物理页码是：{page_num}

【示例 1】
物理页码：25
图片中底部写着："10"
输出：15

【示例 2】
物理页码：12
图片中顶部写着："- 2 -"
输出：10

【示例 3】
物理页码：100
图片中没有明确的阿拉伯数字页码
输出：Error

请仔细观察图片，找到印刷页码，并严格按照上述格式，仅输出计算后的正文偏移量数字。不要输出任何解释。"""
    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}},
                        {"type": "text", "text": prompt}
                    ]
                }
            ],
            extra_body={"enable_thinking": False}
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        error_msg = f"获取第 {page_num} 页偏移量失败：{e}"
        logger.error(error_msg)
        write_log(error_msg)
        return "Error"

async def calculate_offset(pdf_path: str, client: AsyncOpenAI, model: str) -> int:
    """自动计算正文偏移量"""
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        start_idx = int(total_pages * 0.2)
        end_idx = int(total_pages * 0.8)
        if end_idx <= start_idx:
            end_idx = total_pages - 1
            start_idx = 0
            
        pool = list(range(start_idx, end_idx + 1))
        selected_pages = random.sample(pool, min(5, len(pool)))
        
        images_data = []
        for p in selected_pages:
            page = doc[p]
            rect = page.rect
            max_dim = max(rect.width, rect.height)
            zoom = 1500.0 / max_dim if max_dim > 1500 else 2.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("jpeg")
            base64_image = base64.b64encode(img_data).decode('utf-8')
            images_data.append((p + 1, base64_image))
        doc.close()
        
        tasks = [fetch_single_offset(client, model, p_num, b64) for p_num, b64 in images_data]
        results = await asyncio.gather(*tasks)
        
        offsets = []
        for res in results:
            if res.isdigit() or (res.startswith('-') and res[1:].isdigit()):
                offsets.append(int(res))
                
        if offsets:
            most_common_offset = Counter(offsets).most_common(1)[0][0]
            info_msg = f"自动计算偏移量成功：{most_common_offset}"
            print(f"[INFO] {info_msg}")
            write_log(info_msg)
            return most_common_offset
        else:
            warn_msg = "未能自动计算出有效的偏移量"
            print(f"[WARNING] {warn_msg}")
            write_log(warn_msg)
            return None
            
    except Exception as e:
        error_msg = f"自动计算偏移量过程发生异常：{str(e)}"
        logger.error(error_msg)
        write_log(error_msg)
        return None

async def main():
    write_log("=== pdf_metadata_extractor.py 开始执行 ===")
    
    # 移除 load_dotenv()，完全依赖 Flask 注入的环境变量，避免冲突
    input_dir = os.getenv("PDF_METADATA_EXTRACTOR_INPUT")
    output_dir = os.getenv("PDF_METADATA_EXTRACTOR_OUTPUT")
    
    if not input_dir or not output_dir:
        error_msg = "环境变量 PDF_METADATA_EXTRACTOR_INPUT 或 PDF_METADATA_EXTRACTOR_OUTPUT 未设置"
        print(f"错误：{error_msg}")
        write_log(error_msg)
        sys.exit(1)

    input_dir = os.path.abspath(input_dir)
    output_dir = os.path.abspath(output_dir)

    if not os.path.exists(input_dir):
        error_msg = f"输入目录未找到，当前查找目录：{input_dir}"
        print(f"错误：{error_msg}")
        write_log(error_msg)
        sys.exit(1)
        
    pdf_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.pdf')]
    if len(pdf_files) != 1:
        error_msg = f"输入目录中必须仅包含 1 个 PDF 文件，当前找到 {len(pdf_files)} 个。查找目录：{input_dir}"
        print(f"错误：{error_msg}")
        write_log(error_msg)
        sys.exit(1)
    
    pdf_filename = pdf_files[0]
    pdf_path = os.path.join(input_dir, pdf_filename)
    
    json_filename = os.path.splitext(pdf_filename)[0] + ".json"
    json_path = os.path.join(output_dir, json_filename)
    if not os.path.exists(json_path):
        error_msg = f"目标 JSON 文件未找到，当前查找目录：{json_path}"
        print(f"错误：{error_msg}")
        write_log(error_msg)
        sys.exit(1)

    initial_data_dir = os.path.join(output_dir, "initial_data")
    os.makedirs(initial_data_dir, exist_ok=True)
    info_msg = f"中间数据将保存至：{initial_data_dir}"
    print(f"[INFO] {info_msg}")
    write_log(info_msg)

    # 修复：使用动态计算的 PROJECT_ROOT 解析配置文件路径
    config_path = os.path.join(PROJECT_ROOT, "static", "llm_config.json")
    if not os.path.exists(config_path):
        error_msg = f"LLM 配置文件未找到，当前查找目录：{config_path}"
        print(f"错误：{error_msg}")
        write_log(error_msg)
        sys.exit(1)
        
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
        
    api_key = get_api_key(config.get("api_key", ""))
    base_url = config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    model = config.get("model", "qwen-vl-max")
    
    if not api_key:
        error_msg = "API Key 解析失败或为空，请检查 llm_config.json 或环境变量配置。"
        print(f"错误：{error_msg}")
        write_log(error_msg)
        sys.exit(1)

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    info_msg = f"开始处理 PDF: {pdf_filename}"
    print(f"[INFO] {info_msg}")
    write_log(info_msg)
    
    book_name_task = extract_book_name(pdf_path, pdf_filename, client, model)
    offset_task = calculate_offset(pdf_path, client, model)
    toc_task = extract_toc_info(pdf_path, client, model, initial_data_dir)
    
    book_name, content_start, (toc_start, toc_end) = await asyncio.gather(
        book_name_task, offset_task, toc_task
    )

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
            
        updated = False
        if book_name:
            json_data["book_name"] = book_name
            updated = True
        if content_start is not None:
            json_data["content_start"] = content_start
            updated = True
        if toc_start is not None and toc_end is not None:
            json_data["toc_start"] = toc_start
            json_data["toc_end"] = toc_end
            updated = True
            
        if updated:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)
            success_msg = f"成功更新 JSON 文件：{json_path}"
            result_msg = f"提取结果 -> 书名：{book_name}, 偏移量：{content_start}, 目录：{toc_start}-{toc_end}"
            print(f"[SUCCESS] {success_msg}")
            print(f"[RESULT] {result_msg}")
            write_log(success_msg)
            write_log(result_msg)
        else:
            warn_msg = "未提取到有效数据，JSON 文件未更新。"
            print(f"[WARNING] {warn_msg}")
            write_log(warn_msg)
            
    except Exception as e:
        error_msg = f"读写 JSON 文件时发生错误：{str(e)}"
        print(f"[ERROR] {error_msg}")
        write_log(error_msg)
        write_log("完整错误追踪:\n" + traceback.format_exc())
        sys.exit(1)
    
    write_log("=== pdf_metadata_extractor.py 执行完成 ===")

if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n[INFO] pdf_metadata_extractor 执行完成!")
    except Exception as e:
        error_msg = f"程序执行出错：{e}"
        print(f"\n[ERROR] {error_msg}")
        write_log(f"主程序未捕获的异常：{error_msg}")
        write_log("完整错误追踪:\n" + traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)