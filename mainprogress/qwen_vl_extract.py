import os
import asyncio
import base64
import traceback
import sys
import re
import csv
from pathlib import Path
from io import BytesIO, StringIO
from PIL import Image
from dotenv import load_dotenv
from openai import AsyncOpenAI, APIError

# 配置常量
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}
MAX_IMAGE_DIMENSION = 1500
CONCURRENT_LIMIT = 15
MAX_RETRIES = 5  # API 请求最大重试次数
POST_PROCESS_RETRIES = 2  # 后处理失败后的额外重试次数

# 全局提示词
PROMPT_TEXT = """# 任务目标
分析提供的图片并提取目录信息。提取目标为每个目录项的标题和页码。

# 输出格式要求
1. 数据格式：仅输出CSV格式数据，禁止包含任何其他文本、代码解释或说明。
2. 表头设置：必须包含表头 title,page_number。第一列为标题，第二列为页码。
3. 分隔符：严格使用半角逗号 `,` 作为列分隔符，禁止使用全角逗号 `，`。

# 内容提取规则
1. 完整性与筛选：提取所有目录项目，不遗漏任何带有页码的条目。
2. 无页码条目判定：针对无页码条目需依据语义判断。若为篇、章级别的大标题，需推算并填补实际页码；若存在大量无页码的节、子节等次级标题，则直接忽略。
3. 所见即所得：提取页面真实存在的信息，禁止自行推测或补充未显示的层级标题。例如页面以 4.5.1 开头，绝对禁止自行补充第四章及4.5节的标题，仅提取当前可见的内容。
4. 忠于原文：严格保留原始标题的文字、数字形式及前缀，禁止增添、删减或修改。
   * 示例：图上为 `第7章 总结`，则提取为 `第7章 总结`。
   * 示例：图上为 `7章 不良案例`，则提取为 `7章 不良案例`，禁止修改为 `第7章 不良案例` 或 `7 不良案例`。
   * 示例：图上为 `01 花草篇`，则提取为 `01 花草篇`，禁止修改为 `花草篇`。

5. 语言保留：严格保留原始文字（包括繁体中文、英文等），禁止进行翻译。
6. 符号替换：将带圈数字替换为常规阿拉伯数字。例如将 ① 替换为 1。
7. 标题页码分割：准确区分紧跟在标题后的页码，避免将页码提取为标题的一部分。
   * 示例：`1 绪论` 和 `第一章 绪论` 为合理标题。若出现 `第一章 绪论 / 1` 或 `第一章 绪论 1`，末尾的 `1` 应当作为页码提取，标题仅为 `第一章 绪论`。
8. 标点符号规范：包含中文的标题统一使用全角标点符号（如 `：` 和 `，`）。纯英文标题使用半角标点。
9. 剔除连接符：去除标题与页码之间或标题内部用于排版的引导点 `·` 或类似连接符。仅保留语义上确实作为省略号存在的符号。
   * 正确示例：`Part25 写给想成为动画作者的人,122`
   * 错误示例：`Part 25……写给想成为动画作者的人,122`
10. 标题完整性：保持章节编号与标题内容的完整关联，禁止因排版结构将其拆分为独立的两行。
    * 正确示例：`第1章 基本知识,1`
    * 错误示例：`第1章,null` 换行 `基本知识,1`
11. 排除页眉页脚：忽略分布在页面边缘的书籍名称、页眉或章节导航等非目录主体内容。
12. 页面上出现xx篇、xx章时，尽管它们没有页码，但仍然应提取，它们必然是目录的一部分。

# 页码处理规则
1. 缺失页码推算：若篇、章等高级别条目缺失页码，需根据其下级首个条目的页码或相邻条目进行合理推算并填补。禁止出现null的结果。
   * 示例：第1篇的页码丢失，但第1篇第1章的页码为2，则推测第1篇的页码为2。

# 空格与排版规则
1. 纯中文目录：章节编号与具体标题之间仅保留1个半角空格。禁止在中文词组内部、数字与中文字符之间添加多余空格。
   * 正确示例：`第1章 自动控制概述`；`第2章 超前滞后校正与PID校正`
   * 错误示例：`第 1章 自动控制概述`；`第1 章自动控制概述`；`第2章 超前滞后校正与 PID校正`；`第2章 超前滞后校正与PID 校正`；`第 1 章 自动控制概述`
2. 纯英文目录：遵循标准英语语法，单词、数字与符号之间保留常规空格。
3. 混合目录：中文部分执行中文空格规则，英文部分执行英文空格规则。"""

IMPORTANT_NOTE = """
1. 忠于原文。图上为 `01 花草篇`，则提取为 `01 花草篇`，禁止修改为 `花草篇`。
2. 页面上出现xx篇、xx章时，尽管它们没有页码，但仍然应提取，它们必然是目录的一部分。
"""

LLM_CONFIG = {}
IMAGE_CACHE = {}
client = None

def write_log(message):
    try:
        project_root = Path(__file__).parent.parent
        log_file = project_root / "log.txt"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[Extract CSV] {message}\n")
    except Exception as e:
        print(f"日志写入失败：{e}")

def load_llm_config() -> dict:
    import json
    project_root = Path(__file__).parent.parent
    config_path = project_root / "static" / "llm_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"LLM 配置文件不存在：{config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    def resolve_value(val):
        if isinstance(val, str) and val.startswith('$') and val.endswith('$'):
            return os.getenv(val[1:-1])
        return val

    api_key = resolve_value(config.get("api_key"))
    base_url = resolve_value(config.get("base_url"))
    model = resolve_value(config.get("model"))

    if not api_key:
        raise ValueError("API Key 不能为空")
    
    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model
    }

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]

def resize_and_encode_image(image_path: Path) -> str:
    with Image.open(image_path) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        width, height = img.size
        max_dim = max(width, height)
        if max_dim > MAX_IMAGE_DIMENSION:
            ratio = MAX_IMAGE_DIMENSION / max_dim
            img = img.resize((int(width * ratio), int(height * ratio)), Image.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85, optimize=True)
        return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"

def get_encoded_image(image_path: Path) -> str:
    if image_path not in IMAGE_CACHE:
        IMAGE_CACHE[image_path] = resize_and_encode_image(image_path)
    return IMAGE_CACHE[image_path]

def validate_and_fix_csv_content(content: str):
    """
    验证 CSV 内容是否合法（2 列）。
    若不合法，尝试修复：
    1. 将每行最后一个全角逗号替换为半角逗号。
    2. 若解析为 3 列以上，说明半角逗号没有被恰当处理，将前 n-1 列合并并用双引号包裹。
    返回：(is_valid, fixed_content)
    """
    lines = content.splitlines()
    fixed_lines = []
    
    for line in lines:
        if not line.strip():
            continue
            
        # 尝试解析当前行
        try:
            reader = csv.reader(StringIO(line))
            row = next(reader)
        except Exception:
            row = []
            
        # 1. 如果列数少于2，尝试将最后一个全角逗号替换为半角逗号
        if len(row) < 2:
            last_fullwidth_idx = line.rfind('，')
            if last_fullwidth_idx != -1:
                line_fixed = line[:last_fullwidth_idx] + ',' + line[last_fullwidth_idx+1:]
                try:
                    row = next(csv.reader(StringIO(line_fixed)))
                except Exception:
                    pass
                    
        # 2. 根据最终的 row 长度进行处理并重新生成标准 CSV 行
        if len(row) > 2:
            # 超过2列：合并前 n-1 列
            title = ",".join(row[:-1])
            page = row[-1]
            buffer = StringIO()
            writer = csv.writer(buffer)
            writer.writerow([title, page])
            fixed_lines.append(buffer.getvalue().strip())
        elif len(row) == 2:
            # 正常2列（或经过全角修复后变为2列）：使用 csv.writer 重新写入，确保格式绝对标准
            buffer = StringIO()
            writer = csv.writer(buffer)
            writer.writerow(row)
            fixed_lines.append(buffer.getvalue().strip())
        else:
            # 仍然无法修复为至少2列，原样保留，后续校验会失败
            fixed_lines.append(line)
            
    fixed_content = '\n'.join(fixed_lines)
    
    # 最终检查所有行是否都严格为 2 列
    try:
        reader = csv.reader(StringIO(fixed_content))
        rows = list(reader)
        if not rows:
            return False, content
        for row in rows:
            if len(row) != 2:
                return False, content
        return True, fixed_content
    except Exception:
        return False, content

def fix_null_page_numbers(csv_content: str) -> str:
    """
    处理页码为 null 的情况：
    1. 若某标题页码为 null，则向下寻找第一个非 null 项填充。
    2. 若下方全是 null，则向上寻找最近的非 null 项填充。
    """
    lines = csv_content.strip().splitlines()
    if not lines:
        return csv_content
    
    # 解析为列表以便修改
    # 假设第一行是 header，不参与逻辑判断，但需要保留
    header = lines[0]
    data_lines = lines[1:]
    
    parsed_data = []
    for line in data_lines:
        # 简单分割，假设标题内不包含逗号（根据 prompt 要求已去除干扰）
        # 为了安全起见，使用 csv 模块解析单行
        try:
            reader = csv.reader(StringIO(line))
            row = next(reader)
            if len(row) >= 2:
                title = row[0]
                page = row[1].strip()
                parsed_data.append({'title': title, 'page': page, 'original_line': line})
            else:
                # 格式错误的行，原样保留
                parsed_data.append({'title': '', 'page': '', 'original_line': line, 'invalid': True})
        except Exception:
            parsed_data.append({'title': '', 'page': '', 'original_line': line, 'invalid': True})

    n = len(parsed_data)
    
    # 辅助函数：判断页码是否有效
    def is_valid_page(p):
        if p is None:
            return False
        p_str = str(p).strip().lower()
        return p_str != '' and p_str != 'null' and p_str != 'none'

    # 第一遍：向下查找填充
    for i in range(n):
        if parsed_data[i].get('invalid'):
            continue
            
        current_page = parsed_data[i]['page']
        if not is_valid_page(current_page):
            # 向下找
            found = False
            for j in range(i + 1, n):
                if parsed_data[j].get('invalid'):
                    continue
                if is_valid_page(parsed_data[j]['page']):
                    parsed_data[i]['page'] = parsed_data[j]['page']
                    found = True
                    break
            # 如果向下没找到，标记需要向上找（稍后处理或立即处理）
            # 这里采用立即向上查找的策略，因为向下已经确定没有了
            if not found:
                # 向上找
                for k in range(i - 1, -1, -1):
                    if parsed_data[k].get('invalid'):
                        continue
                    if is_valid_page(parsed_data[k]['page']):
                        parsed_data[i]['page'] = parsed_data[k]['page']
                        break
                # 如果上下都没找到，保持原样（可能是整个文件都没页码）

    # 重建 CSV 内容
    output_lines = [header]
    for item in parsed_data:
        if item.get('invalid'):
            output_lines.append(item['original_line'])
        else:
            # 重新组合，确保格式正确
            # 注意：如果原标题包含逗号，这里可能需要更复杂的转义，但根据 prompt 规则标题应较干净
            # 使用 csv 模块写入以确保安全
            buffer = StringIO()
            writer = csv.writer(buffer)
            writer.writerow([item['title'], item['page']])
            output_lines.append(buffer.getvalue().strip())
            
    return '\n'.join(output_lines)

async def process_image_async(semaphore: asyncio.Semaphore, img_file: Path, output_path: Path):
    """
    使用 OpenAI SDK 发送请求，并包含后处理逻辑
    修改点：增加对解析错误的详细日志记录，包含原始响应
    """
    async with semaphore:
        output_file = output_path / f"{img_file.stem}.csv"
        if output_file.exists():
            write_log(f"跳过已处理文件：{img_file.name}")
            return None

        write_log(f"开始处理图像：{img_file.name}")
        
        last_raw_response = None
        last_error_msg = None
        
        try:
            image_data_url = get_encoded_image(img_file)
            
            # 构建消息内容
            content_list = [
                {"type": "text", "text": "当前页图片（需处理）："},
                {"type": "text", "text": PROMPT_TEXT},
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": PROMPT_TEXT},
                {"type": "text", "text": IMPORTANT_NOTE}
            ]

            # 外层循环控制总重试次数 (初始 1 次 + 后处理失败后的额外重试)
            total_attempts = 1 + POST_PROCESS_RETRIES
            
            final_content = None
            
            for attempt in range(total_attempts):
                try:
                    # 调用 SDK
                    response = await client.chat.completions.create(
                        model=LLM_CONFIG["model"],
                        messages=[{"role": "user", "content": content_list}],
                        temperature=0,
                        extra_body={"enable_thinking": False}
                    )
                    
                    # 保存原始响应内容用于潜在的错误日志
                    last_raw_response = response.choices[0].message.content
                    
                    content = last_raw_response.strip()
                    
                    # 清理 Markdown 代码块标记
                    if content.startswith("```csv"): 
                        content = content[6:]
                    elif content.startswith("```"): 
                        content = content[3:]
                    if content.endswith("```"): 
                        content = content[:-3]
                    content = content.strip()

                    if not content:
                        write_log(f"模型返回空内容 (尝试 {attempt+1}/{total_attempts})")
                        if attempt == total_attempts - 1:
                            raise Exception("模型持续返回空内容")
                        continue

                    # 后处理验证与修复
                    is_valid, processed_content = validate_and_fix_csv_content(content)
                    
                    if is_valid:
                        final_content = processed_content
                        if attempt > 0:
                            write_log(f"第 {attempt+1} 次尝试成功 (经过后处理修复)")
                        break
                    else:
                        # 记录验证失败的原始内容
                        last_error_msg = f"CSV 格式验证失败：行数或列数不符合 2 列要求。原始内容片段：{content[:200]}..."
                        write_log(f"CSV 解析失败且修复无效 (尝试 {attempt+1}/{total_attempts})")
                        if attempt == total_attempts - 1:
                            raise Exception(last_error_msg)
                        # 继续下一次重试循环，重新请求 LLM
                        
                except APIError as e:
                    # 捕获 API 错误，尝试提取响应体
                    error_body = getattr(e, 'body', None) or str(e)
                    last_raw_response = f"API Error Body: {error_body}"
                    last_error_msg = f"API 错误：{str(e)}"
                    write_log(f"API 错误 (尝试 {attempt+1}/{total_attempts}): {last_error_msg}")
                    if attempt == total_attempts - 1:
                        raise e
                    # 短暂等待后重试
                    await asyncio.sleep(2 ** attempt) 
                except Exception as e:
                    last_error_msg = f"处理逻辑错误：{str(e)}"
                    write_log(f"处理逻辑错误 (尝试 {attempt+1}/{total_attempts}): {last_error_msg}")
                    if attempt == total_attempts - 1:
                        raise e
            
            if final_content:
                # === 新增逻辑：页码 Null 填充 ===
                try:
                    fixed_content = fix_null_page_numbers(final_content)
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(fixed_content)
                    write_log(f"结果保存并修正页码成功：{output_file.name}")
                except Exception as post_err:
                    write_log(f"页码修正过程出错，保存原始内容：{str(post_err)}")
                    # 如果修正失败，至少保存原始验证通过的内容
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(final_content)
                
                print(f"已提取 CSV：{img_file.name}")
                return True
            else:
                # 理论上不会到达这里，因为上面已经抛出异常或 break
                print(f"处理 {img_file.name} 失败，未达到有效内容标准")
                return False
            
        except Exception as e:
            # === 核心修改：记录详细错误日志和原始响应 ===
            error_details = {
                "file": img_file.name,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "raw_response": last_raw_response if last_raw_response else "No response received",
                "last_error_context": last_error_msg if last_error_msg else "Unknown context"
            }
            
            log_entry = (
                f"=== CSV 解析失败报告 ===\n"
                f"文件：{error_details['file']}\n"
                f"错误类型：{error_details['error_type']}\n"
                f"错误信息：{error_details['error_message']}\n"
                f"上下文：{error_details['last_error_context']}\n"
                f"原始响应内容:\n{error_details['raw_response']}\n"
                f"========================\n"
            )
            
            write_log(log_entry)
            traceback.print_exc()
            return False

async def run_batch_processing(image_files: list, output_path: Path):
    write_log("正在预处理并缓存图片...")
    # 预加载图片到内存，避免在处理时频繁读取磁盘
    for img in image_files:
        get_encoded_image(img)
    
    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    
    tasks = []
    for img_file in image_files:
        tasks.append(process_image_async(semaphore, img_file, output_path))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    success_count = sum(1 for r in results if r is True)
    print(f"CSV 提取完成，成功：{success_count}/{len(image_files)}")

async def main_async():
    global client, LLM_CONFIG
    
    load_dotenv()
    LLM_CONFIG = load_llm_config()
    
    # 初始化 OpenAI 客户端 (兼容模式)
    client = AsyncOpenAI(
        api_key=LLM_CONFIG["api_key"],
        base_url=LLM_CONFIG["base_url"]
    )
    
    base_dir = os.getenv("BASE_DIR")
    if base_dir:
        input_path = Path(base_dir) / "mark" / "input_image"
        output_path = Path(base_dir) / "raw_content"
    else:
        input_path_str = os.getenv("QWEN_VL_EXTRACT_INPUT")
        output_path_str = os.getenv("QWEN_VL_EXTRACT_OUTPUT")
        
        if not input_path_str or not output_path_str:
            print("错误：未设置必要的环境变量 QWEN_VL_EXTRACT_INPUT 或 QWEN_VL_EXTRACT_OUTPUT")
            sys.exit(1)
            
        input_path = Path(input_path_str)
        output_path = Path(output_path_str)
    
    if not input_path.exists():
        print(f"错误：输入路径不存在 {input_path}")
        sys.exit(1)
        
    output_path.mkdir(parents=True, exist_ok=True)
    image_files = sorted([f for f in input_path.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS], key=lambda x: natural_sort_key(x.name))
    
    if image_files:
        await run_batch_processing(image_files, output_path)
    else:
        print("未找到需要处理的图片。")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main_async())