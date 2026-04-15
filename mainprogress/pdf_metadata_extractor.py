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
    """写入日志到项目根目录的 log.txt"""
    try:
        log_file = Path(PROJECT_ROOT) / "log.txt"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{threading.current_thread().name}] {message}\n")
    except Exception as e:
        print(f"日志写入失败：{e}")

# 配置日志输出到标准输出
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
    
    # 定义目标长边像素，确保小页面也能被放大到清晰程度
    TARGET_LONG_EDGE = 1500
    
    for p in range(start_p - 1, end_p):
        if p >= len(doc): 
            break
        page = doc[p]
        rect = page.rect
        max_dim = max(rect.width, rect.height)
        
        # 修正逻辑：始终计算缩放比例，不再判断是否大于目标值
        # 如果 max_dim 为 0，跳过该页以防出错
        if max_dim == 0:
            continue
            
        zoom = TARGET_LONG_EDGE / max_dim
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
        text = f"PDFNumber {p_num}"
        
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
    prompt = f"""这是一张由几个连续的 PDF 页面横向拼接而成的图片。每张图片下方标注了它的物理页码（例如 PDFNumber {start_p}）。
请找出这几页中，属于目录的起始页码和结束页码。

【目录的严格定义】：一页中必须存在多个“标题 - 页码”对。如果某一页没有这个特征（例如纯文本正文、封面、版权页、序言），则它绝对不是目录。只要不存在页码，那这页绝对不是目录。相对应地，如果一页有这个特征，那么它必然是目录。

【注意】：应以下方的 PDFNumber 作为页码。例如 PDFNumber 为 2-3 的图片是目录，那么起始页码就是 2，结束页码就是 3。

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
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}},
                        {"type": "text", "text": prompt},
                    ]
                }
            ],
            extra_body={"enable_thinking": False},
            temperature=0,
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

def merge_continuous_ranges(page_list: list) -> tuple:
    """
    将分散的页码列表合并为最大的连续区间。
    逻辑：排序后，如果相邻页码差值 <= 1，视为连续。
    返回最大连续区间的 (start, end)。
    """
    if not page_list:
        return None, None
    
    sorted_pages = sorted(list(set(page_list)))
    if len(sorted_pages) == 1:
        return sorted_pages[0], sorted_pages[0]
    
    best_start = sorted_pages[0]
    best_end = sorted_pages[0]
    max_len = 1
    
    current_start = sorted_pages[0]
    current_end = sorted_pages[0]
    
    for i in range(1, len(sorted_pages)):
        prev = sorted_pages[i-1]
        curr = sorted_pages[i]
        
        if curr - prev <= 1:
            current_end = curr
        else:
            current_len = current_end - current_start + 1
            if current_len > max_len:
                max_len = current_len
                best_start = current_start
                best_end = current_end
            current_start = curr
            current_end = curr
            
    current_len = current_end - current_start + 1
    if current_len > max_len:
        best_start = current_start
        best_end = current_end
        
    return best_start, best_end

async def extract_toc_info(pdf_path: str, client: AsyncOpenAI, model: str, initial_data_dir: str) -> tuple:
    """使用滑动窗口提取目录，并对冲突页进行单页投票"""
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    
    write_log(f"开始提取目录信息，总页数：{total_pages}")
    
    # 控制并发度为 8
    semaphore = asyncio.Semaphore(8)
    # 记录每一页被判定为目录和非目录的次数
    page_votes = {i: {"is_toc": 0, "not_toc": 0} for i in range(1, total_pages + 1)}
    
    async def process_window(start_p, end_p):
        async with semaphore:
            img_filename = f"concat_pages_{start_p}_{end_p}.jpg"
            img_save_path = os.path.join(initial_data_dir, img_filename)
            raw_filename = f"toc_response_{start_p}_{end_p}.json"
            raw_save_path = os.path.join(initial_data_dir, raw_filename)
            
            b64_img = create_concat_image_b64(doc, start_p, end_p, save_path=img_save_path)
            if not b64_img:
                return start_p, end_p, None, None, None
                
            raw_res = await fetch_toc_from_image(client, model, b64_img, start_p, end_p, raw_save_path)
            toc_start, toc_end = parse_toc_json(raw_res)
            
            # 需求 1: 将图片和原始结果也输出到 initial_data 中的详细记录文件
            detail_filename = f"toc_detail_{start_p}_{end_p}.json"
            detail_save_path = os.path.join(initial_data_dir, detail_filename)
            detail_data = {
                "page_range": f"{start_p}-{end_p}",
                "parsed_result": {"toc_start": toc_start, "toc_end": toc_end},
                "raw_response": raw_res,
                "image_saved_as": img_filename
                # 注意：b64_img 数据量大，不直接存入 JSON，而是引用保存的图片文件
            }
            with open(detail_save_path, 'w', encoding='utf-8') as f:
                json.dump(detail_data, f, ensure_ascii=False, indent=2)
                
            return start_p, end_p, toc_start, toc_end, raw_res

    async def run_batch(start_page, end_page_limit):
        """执行一个批次的滑动窗口扫描"""
        windows = []
        # 步长为 2，窗口大小为 4
        for i in range(start_page, end_page_limit, 2):
            if i > total_pages:
                break
            windows.append((i, min(i + 3, total_pages)))
            
        if not windows:
            return
            
        tasks = [process_window(s, e) for s, e in windows]
        results = await asyncio.gather(*tasks)
        
        for s, e, t_start, t_end, _ in results:
            if t_start is None: continue
            for p in range(s, e + 1):
                if t_start <= p <= t_end:
                    page_votes[p]["is_toc"] += 1
                else:
                    page_votes[p]["not_toc"] += 1

    # 第一阶段：初始扫描 1-20 页
    current_limit = min(20, total_pages)
    info_msg = f"正在分析目录范围：第 1 到 {current_limit} 页 (滑动窗口)"
    print(f"[INFO] {info_msg}")
    write_log(info_msg)
    await run_batch(1, current_limit + 1)
    
    # 第二阶段：动态拓展逻辑
    while current_limit < 60 and current_limit < total_pages:
        p1 = current_limit - 1
        p2 = current_limit
        
        is_p1_toc = page_votes.get(p1, {}).get("is_toc", 0) > 0
        is_p2_toc = page_votes.get(p2, {}).get("is_toc", 0) > 0
        
        if not (is_p1_toc and is_p2_toc):
            break
            
        current_limit = min(current_limit + 10, 60)
        if current_limit > total_pages:
            current_limit = total_pages
            
        info_msg = f"第 {p1}-{p2} 页确认为目录，拓展扫描范围至第 {current_limit} 页"
        print(f"[INFO] {info_msg}")
        write_log(info_msg)
        
        await run_batch(current_limit - 9, current_limit + 1)

    # 冲突检测与单页投票
    conflict_pages = []
    final_toc_pages = []
    
    for p, votes in page_votes.items():
        if votes["is_toc"] > 0 and votes["not_toc"] > 0:
            conflict_pages.append(p)
        elif votes["is_toc"] > 0:
            final_toc_pages.append(p)
            
    if conflict_pages:
        info_msg = f"发现冲突页，进行单页投票：{conflict_pages}"
        print(f"[INFO] {info_msg}")
        write_log(info_msg)
        
        async def resolve_conflict(p):
            async with semaphore:
                img_filename = f"single_page_{p}.jpg"
                img_save_path = os.path.join(initial_data_dir, img_filename)
                raw_filename = f"single_toc_response_{p}.json"
                raw_save_path = os.path.join(initial_data_dir, raw_filename)
                
                b64_img = create_concat_image_b64(doc, p, p, save_path=img_save_path)
                if not b64_img:
                    return p, False, None
                    
                prompt = f"""这是一张 PDF 页面的图片，物理页码为 {p}。
请判断这一页是否是目录。目录的严格定义为：这张图中是否能提取出多个标题 - 页码对。
【输出要求】：
1. 仅输出 JSON 格式，不要包含任何 markdown 标记。
2. 如果是目录，输出：{{"is_toc": true}}
3. 如果不是目录，输出：{{"is_toc": false}}"""

                try:
                    completion = await client.chat.completions.create(
                        model=model,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}},
                                ]
                            }
                        ],
                        extra_body={"enable_thinking": False},
                        temperature=0,
                    )
                    raw_content = completion.choices[0].message.content.strip()
                    
                    # 保存原始响应
                    with open(raw_save_path, 'w', encoding='utf-8') as f:
                        json.dump({"page": p, "raw_response": raw_content}, f, ensure_ascii=False, indent=2)
                        
                    clean_text = re.sub(r'^```(?:json)?\s*', '', raw_content, flags=re.MULTILINE)
                    clean_text = re.sub(r'\s*```$', '', clean_text, flags=re.MULTILINE)
                    data = json.loads(clean_text)
                    is_toc = data.get("is_toc", False)
                    
                    # 需求 1: 保存单页投票的详细记录
                    detail_filename = f"single_vote_detail_{p}.json"
                    detail_save_path = os.path.join(initial_data_dir, detail_filename)
                    detail_data = {
                        "page": p,
                        "parsed_result": {"is_toc": is_toc},
                        "raw_response": raw_content,
                        "image_saved_as": img_filename
                    }
                    with open(detail_save_path, 'w', encoding='utf-8') as f:
                        json.dump(detail_data, f, ensure_ascii=False, indent=2)
                        
                    return p, is_toc, raw_content
                except Exception as e:
                    logger.error(f"单页投票失败 (页码 {p}): {e}")
                    return p, False, None

        conflict_tasks = [resolve_conflict(p) for p in conflict_pages]
        conflict_results = await asyncio.gather(*conflict_tasks)
        
        for p, is_toc, _ in conflict_results:
            if is_toc:
                final_toc_pages.append(p)

    doc.close()

    if not final_toc_pages:
        warn_msg = "未识别到任何目录页"
        print(f"[WARNING] {warn_msg}")
        write_log(warn_msg)
        return None, None

    global_toc_start, global_toc_end = merge_continuous_ranges(final_toc_pages)
    
    if global_toc_start is None:
        return None, None

    if global_toc_end >= 60:
        warn_msg = "目录识别达到或超过 60 页上限，触发熔断，强制设置为 1 和 2"
        print(f"[WARNING] {warn_msg}")
        write_log(warn_msg)
        return 1, 2

    info_msg = f"目录页码合并完成：{global_toc_start}-{global_toc_end} (最终识别页码数：{len(final_toc_pages)})"
    print(f"[INFO] {info_msg}")
    write_log(info_msg)

    return global_toc_start, global_toc_end

async def extract_book_name(pdf_path: str, original_filename: str, client: AsyncOpenAI, model: str) -> str:
    """提取 PDF 第一页并调用 LLM 识别书名"""
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]
        rect = page.rect
        max_dim = max(rect.width, rect.height)
        
        # 修正逻辑：始终计算缩放比例，确保小封面也能清晰识别
        TARGET_LONG_EDGE = 1000
        if max_dim == 0:
            doc.close()
            return ""
            
        zoom = TARGET_LONG_EDGE / max_dim
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
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ]
                }
            ],
            extra_body={"enable_thinking": False},
            temperature=0,
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
计算：25 - 10 = 15
输出：15

【示例 2】
物理页码：12
图片中顶部写着："- 2 -"
计算：12 - 2 = 10
输出：10

【示例 3】
物理页码：100
图片中没有明确的阿拉伯数字页码
输出：Error

【错误示例】
物理页码：25
图片中顶部写着："20"
计算：25 - 20 = -5
输出：-5

请仔细观察图片，找到印刷页码，并严格按照上述格式，仅输出计算后的正文偏移量数字。不要输出任何解释。"""
    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}},
                    ]
                }
            ],
            extra_body={"enable_thinking": False},
            temperature=0,
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        error_msg = f"获取第 {page_num} 页偏移量失败：{e}"
        logger.error(error_msg)
        write_log(error_msg)
        return "Error"

async def calculate_offset(pdf_path: str, client: AsyncOpenAI, model: str, initial_data_dir: str) -> int:
    """
    自动计算正文偏移量。
    逻辑优化：
    1. 先随机取 5 页。
    2. 统计众数，若众数数量 < 4，则再随机取 5 页（不重复），共 10 页一起统计。
    3. 将所有过程的图片、原始响应、解析结果保存到 initial_data/offset_log.json。
    """
    log_entries = []
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        start_idx = int(total_pages * 0.2)
        end_idx = int(total_pages * 0.8)
        if end_idx <= start_idx:
            end_idx = total_pages - 1
            start_idx = 0
            
        pool = list(range(start_idx, end_idx + 1))
        if len(pool) < 5:
            doc.close()
            return None

        # 第一轮：取 5 页
        selected_pages_1 = random.sample(pool, 5)
        remaining_pool = [p for p in pool if p not in selected_pages_1]
        
        all_selected_indices = selected_pages_1[:]
        
        # 如果需要第二轮
        need_second_round = False
        
        # 临时存储第一轮结果用于判断
        first_round_results = []
        
        # 定义目标长边像素
        TARGET_LONG_EDGE = 1500

        for p in selected_pages_1:
            page = doc[p]
            rect = page.rect
            max_dim = max(rect.width, rect.height)
            
            # 修正逻辑：始终计算缩放比例
            if max_dim == 0:
                continue
            zoom = TARGET_LONG_EDGE / max_dim
            
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("jpeg")
            base64_image = base64.b64encode(img_data).decode('utf-8')
            
            raw_res = await fetch_single_offset(client, model, p + 1, base64_image)
            
            # 记录日志数据
            entry = {
                "physical_page": p + 1,
                "raw_response": raw_res,
                "parsed_offset": None,
                "image_base64_preview": base64_image[:100] + "..." # 仅存预览，避免 JSON 过大，实际图片可单独存如需
            }
            
            if raw_res.isdigit() or (raw_res.startswith('-') and raw_res[1:].isdigit()):
                val = int(raw_res)
                entry["parsed_offset"] = val
                first_round_results.append(val)
            else:
                entry["parsed_offset"] = "Error"
            
            log_entries.append(entry)

        # 检查众数逻辑
        if first_round_results:
            counter = Counter(first_round_results)
            most_common_val, count = counter.most_common(1)[0]
            if count < 4 and len(remaining_pool) >= 5:
                need_second_round = True
                write_log(f"第一轮众数数量为 {count} (<4)，启动第二轮采样。")
        
        if need_second_round:
            selected_pages_2 = random.sample(remaining_pool, 5)
            all_selected_indices.extend(selected_pages_2)
            
            for p in selected_pages_2:
                page = doc[p]
                rect = page.rect
                max_dim = max(rect.width, rect.height)
                
                # 修正逻辑：始终计算缩放比例
                if max_dim == 0:
                    continue
                zoom = TARGET_LONG_EDGE / max_dim
                
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                img_data = pix.tobytes("jpeg")
                base64_image = base64.b64encode(img_data).decode('utf-8')
                
                raw_res = await fetch_single_offset(client, model, p + 1, base64_image)
                
                entry = {
                    "physical_page": p + 1,
                    "raw_response": raw_res,
                    "parsed_offset": None,
                    "round": 2
                }
                
                if raw_res.isdigit() or (raw_res.startswith('-') and raw_res[1:].isdigit()):
                    val = int(raw_res)
                    entry["parsed_offset"] = val
                    # 加入总结果列表用于最终计算（这里不需要显式列表，直接用 log_entries 过滤即可）
                else:
                    entry["parsed_offset"] = "Error"
                
                log_entries.append(entry)

        doc.close()
        
        # 收集所有有效偏移量
        all_offsets = [entry["parsed_offset"] for entry in log_entries if isinstance(entry["parsed_offset"], int)]
        
        # 保存详细日志到 initial_data
        offset_log_path = os.path.join(initial_data_dir, "offset_calculation_log.json")
        summary = {
            "total_samples": len(log_entries),
            "valid_samples": len(all_offsets),
            "details": log_entries
        }
        with open(offset_log_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        write_log(f"偏移量计算详细日志已保存至：{offset_log_path}")

        if all_offsets:
            most_common_offset = Counter(all_offsets).most_common(1)[0][0]
            info_msg = f"自动计算偏移量成功：{most_common_offset} (基于 {len(all_offsets)} 个有效样本)"
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
    
    # 传递 initial_data_dir 给 calculate_offset
    book_name_task = extract_book_name(pdf_path, pdf_filename, client, model)
    offset_task = calculate_offset(pdf_path, client, model, initial_data_dir)
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