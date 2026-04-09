import os
import json
import asyncio
import base64
import sys
import re
import csv
from pathlib import Path
from io import BytesIO, StringIO
from PIL import Image
from dotenv import load_dotenv
from openai import AsyncOpenAI, APIError, Timeout

# 配置常量
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}
MAX_IMAGE_DIMENSION = 1500
CONCURRENT_LIMIT = 15
MAX_RETRIES = 5
REQUEST_TIMEOUT = 180  # 秒

# 全局提示词
# 明确要求输出 CSV 格式，并定义列含义
PROMPT_TEXT = """# 任务目标
请分析提供的图片以及对应的目录数据（标题和页码），判断每个目录项所属的层级（level）。

# 输出格式要求
1. **必须且仅输出 CSV 格式数据**，包含表头 `title,page_number,level`。
2. 严禁输出 Markdown 代码块标记（如 ```csv），严禁输出任何解释性文字。
3. CSV 内容示例：
title,page_number,level
第一章 函数极限连续,1,1
第一节 函数,1,2
一、函数的概念,1,3

# 层级判定规则
1. 视觉特征优先：应优先根据图片呈现的视觉特征（如颜色、字体、字号、缩进等）判定目录层级，也需要结合语义进行推断。
2. 除非是第一页目录，否则第一行的标题未必是第一层级的，它可能隶属于上一页的其他章节。
3. 规避层级判定错误：
   - 规避误区：对于形式不同（例如字号不同、字体不同、缩进不同、颜色不同等）的标题，层级一定是不同的。
   - 尊重常识：`篇`和`部分`一般是最高级；其次为`章`；然后是`节`等。
   - 节与子节的层级关系：例如 2.4（节）与 2.4.1（子节）绝对不可处于同一目录层级，子节的层级必须比节低一级。
4. 思考题、练习题等，应该是作为`章`的下一级，而不应该与`章`处于在同一层级。但切记不要直接删掉这些页码为null的标题，这违背了第一条注意事项的要求。

# 注意事项：
- 输出的 CSV 行数应与输入的 CSV 数据的标题数量严格一致，严禁省略。切记不要直接删掉这些页码为null的标题，你应该推断它们，而不是删除它们。
- level 列必须是整数。
- 部分情况下，识别的标题末尾会附带一个页码，如果遇到这种情况，请去掉那个页码。
- 部分情况下页码会出现null，此时请进行简要推断，例如将其与它附近的页码设置为一致。
- 一般来说，前言、推荐序、致谢、参考文献等，应该是第一层级。
"""

LLM_CONFIG = {}
IMAGE_CACHE = {}
client = None

# 用于存储首图的处理结果，作为全局 Few-shot 示例
# 存储格式：{"image_base64": str, "result_csv_str": str}
FIRST_PAGE_EXAMPLE = {
    "image_base64": None,
    "result_csv_str": None
}

def write_log(message):
    try:
        project_root = Path(__file__).parent.parent
        log_file = project_root / "log.txt"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[Determine Level] {message}\n")
    except Exception as e:
        print(f"日志写入失败：{e}")

def load_llm_config() -> dict:
    project_root = Path(__file__).parent.parent
    config_path = project_root / "static" / "llm_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件未找到：{config_path}")
        
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    def resolve_value(val):
        if isinstance(val, str) and val.startswith('$') and val.endswith('$'):
            env_val = os.getenv(val[1:-1])
            if env_val is None:
                raise ValueError(f"环境变量 {val[1:-1]} 未设置")
            return env_val
        return val
    
    return {
        "api_key": resolve_value(config.get("api_key")),
        "base_url": resolve_value(config.get("base_url")),
        "model": resolve_value(config.get("model"))
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

def validate_and_fix_csv_content(content: str) -> str:
    """
    验证并修复 CSV 内容（目标为 3 列：title, page_number, level）。
    1. 若列数少于 3，尝试从右向左将全角逗号替换为半角逗号（最多替换两次）。
    2. 若解析为 4 列以上，说明标题中包含了半角逗号，将前 n-2 列合并为 title。
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
            
        # 1. 如果列数少于3，尝试将全角逗号替换为半角逗号
        # 因为目标是3列，最多需要2个分隔符，所以尝试从右向左替换两次
        for _ in range(2):
            if len(row) < 3:
                last_fullwidth_idx = line.rfind('，')
                if last_fullwidth_idx != -1:
                    line = line[:last_fullwidth_idx] + ',' + line[last_fullwidth_idx+1:]
                    try:
                        row = next(csv.reader(StringIO(line)))
                    except Exception:
                        pass
                else:
                    break # 没有全角逗号可替换了
                    
        # 2. 根据最终的 row 长度进行处理并重新生成标准 CSV 行
        if len(row) > 3:
            # 超过3列：合并前 n-2 列作为 title
            title = ",".join(row[:-2])
            page = row[-2]
            level = row[-1]
            buffer = StringIO()
            writer = csv.writer(buffer)
            writer.writerow([title, page, level])
            fixed_lines.append(buffer.getvalue().strip())
        elif len(row) == 3:
            # 正常3列：使用 csv.writer 重新写入，确保格式绝对标准
            buffer = StringIO()
            writer = csv.writer(buffer)
            writer.writerow(row)
            fixed_lines.append(buffer.getvalue().strip())
        else:
            # 仍然无法修复为至少3列，原样保留，后续校验会失败或跳过
            fixed_lines.append(line)
            
    return '\n'.join(fixed_lines)

def parse_csv_response(csv_text: str, source_file: str) -> list:
    """
    将模型返回的 CSV 文本解析为目标 JSON 结构。
    目标结构：[{"text": "...", "number": int, "level": int}, ...]
    """
    cleaned_text = csv_text.strip()
    # 移除可能的 markdown 代码块标记
    if cleaned_text.startswith("```csv"):
        cleaned_text = cleaned_text[6:]
    if cleaned_text.startswith("```"):
        cleaned_text = cleaned_text[3:]
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3]
    cleaned_text = cleaned_text.strip()

    # 注入防全角逗号与列数修复逻辑
    cleaned_text = validate_and_fix_csv_content(cleaned_text)

    result_data = []
    try:
        reader = csv.DictReader(StringIO(cleaned_text))
        # 检查必要的列
        if not {'title', 'page_number', 'level'}.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"CSV 缺少必要列 (title, page_number, level)。实际列：{reader.fieldnames}")
            
        for row in reader:
            try:
                title = row['title'].strip()
                if not title:
                    continue
                
                # 尝试转换页码
                page_num_str = row['page_number'].strip()
                page_num = int(page_num_str) if page_num_str else None
                
                # 尝试转换层级
                level_str = row['level'].strip()
                level = int(level_str) if level_str else None
                
                if page_num is None or level is None:
                    write_log(f"警告：跳过无效行 (页码或层级非整数)：{row} in {source_file}")
                    continue

                result_data.append({
                    "text": title,
                    "number": page_num,
                    "level": level
                })
            except (ValueError, KeyError) as e:
                write_log(f"解析单行失败：{row}, 错误：{e}")
                continue
                
    except Exception as e:
        write_log(f"CSV 整体解析失败 {source_file}: {str(e)}")
        raise e
        
    return result_data

async def process_first_page(img_file: Path, csv_file: Path, output_path: Path) -> bool:
    """
    专门处理第一张图片，获取 CSV 格式的响应，并缓存为 Few-shot 示例。
    """
    write_log(f"正在处理首图作为示例：{img_file.name}")
    
    if not csv_file.exists():
        write_log(f"缺少对应的 CSV 文件，跳过首图处理：{img_file.name}")
        return False

    csv_content = csv_file.read_text(encoding='utf-8')
    
    content_list = [
        {"type": "text", "text": "当前页图片（需处理，作为后续页面的参考示例）："},
        {"type": "text", "text": f"{PROMPT_TEXT}\n\n当前页提取的原始 CSV 数据如下：\n{csv_content}"},
        {"type": "image_url", "image_url": {"url": get_encoded_image(img_file)}}
    ]

    messages = [{"role": "user", "content": content_list}]

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.chat.completions.create(
                model=LLM_CONFIG["model"],
                messages=messages,
                extra_body={"enable_thinking": False},
                timeout=REQUEST_TIMEOUT,
                temperature=0,
            )
            
            content = response.choices[0].message.content.strip()
            
            # 本地解析 CSV 转为 JSON 保存
            try:
                parsed_data = parse_csv_response(content, img_file.name)
            except Exception as parse_err:
                write_log(f"首图 CSV 解析失败：{parse_err}")
                if attempt == MAX_RETRIES - 1:
                    return False
                await asyncio.sleep(2 ** attempt)
                continue

            if parsed_data:
                # 排序
                sorted_data = sorted(parsed_data, key=lambda x: x['number'])
                
                # 保存首图结果文件
                output_file = output_path / f"{img_file.stem}_merged.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(sorted_data, f, ensure_ascii=False, indent=2)
                
                # 存入全局变量作为 Few-shot 示例 (存储原始 CSV 字符串)
                FIRST_PAGE_EXAMPLE["image_base64"] = get_encoded_image(img_file)
                FIRST_PAGE_EXAMPLE["result_csv_str"] = content
                
                print(f"首图处理完成并已缓存为示例：{img_file.name}")
                return True
            else:
                write_log(f"首图解析结果为空：{img_file.name}")
                if attempt == MAX_RETRIES - 1:
                    return False
                await asyncio.sleep(2 ** attempt)

        except (APIError, Timeout) as e:
            write_log(f"首图第 {attempt+1} 次 API 请求失败 ({type(e).__name__}): {str(e)}")
            if attempt == MAX_RETRIES - 1:
                return False
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            write_log(f"首图处理异常 {img_file.name}: {str(e)}")
            if attempt == MAX_RETRIES - 1:
                return False
            await asyncio.sleep(2 ** attempt)
    
    return False

async def process_level_async(semaphore: asyncio.Semaphore, img_file: Path, csv_file: Path, output_path: Path):
    """
    处理除第一张以外的其他图片，使用首图的 CSV 结果作为 Few-shot 上下文。
    """
    async with semaphore:
        output_file = output_path / f"{img_file.stem}_merged.json"
        if output_file.exists():
            write_log(f"跳过已处理文件：{img_file.name}")
            return None

        if not csv_file.exists():
            write_log(f"缺少对应的 CSV 文件，跳过：{img_file.name}")
            return False

        csv_content = csv_file.read_text(encoding='utf-8')
        content_list = []
        
        # 构建 Few-shot 上下文：首图 + 首图结果 (CSV 格式)
        if FIRST_PAGE_EXAMPLE["image_base64"] and FIRST_PAGE_EXAMPLE["result_csv_str"]:
            content_list.extend([
                {"type": "text", "text": "参考示例（第一页图片及其正确的 CSV 格式层级分析结果）："},
                {"type": "image_url", "image_url": {"url": FIRST_PAGE_EXAMPLE["image_base64"]}},
                {"type": "text", "text": f"参考结果 (CSV 格式):\n{FIRST_PAGE_EXAMPLE['result_csv_str']}"},
                {"type": "text", "text": "---\n请严格参照上述示例的 CSV 格式和层级判断标准，分析以下当前页图片："}
            ])
        else:
            write_log(f"警告：未找到首图示例，将无参考处理 {img_file.name}")
        
        # 添加当前页图片和提示词
        content_list.extend([
            {"type": "image_url", "image_url": {"url": get_encoded_image(img_file)}},
            {"type": "text", "text": f"{PROMPT_TEXT}\n\n当前页提取的原始 CSV 数据如下：\n{csv_content}"}
        ])

        messages = [{"role": "user", "content": content_list}]

        for attempt in range(MAX_RETRIES):
            try:
                response = await client.chat.completions.create(
                    model=LLM_CONFIG["model"],
                    messages=messages,
                    extra_body={"enable_thinking": False},
                    timeout=REQUEST_TIMEOUT,
                    temperature=0,
                )
                
                content = response.choices[0].message.content.strip()
                
                # 本地解析 CSV 转为 JSON
                try:
                    parsed_data = parse_csv_response(content, img_file.name)
                except Exception as parse_err:
                    write_log(f"第 {attempt+1} 次尝试解析 CSV 失败：{parse_err}")
                    if attempt == MAX_RETRIES - 1:
                        return False
                    await asyncio.sleep(2 ** attempt)
                    continue

                if parsed_data:
                    sorted_data = sorted(parsed_data, key=lambda x: x['number'])
                    
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(sorted_data, f, ensure_ascii=False, indent=2)
                    
                    print(f"已判断层级：{img_file.name}")
                    return True
                else:
                    write_log(f"解析结果为空：{img_file.name}")
                    if attempt == MAX_RETRIES - 1:
                        return False
                    await asyncio.sleep(2 ** attempt)

            except (APIError, Timeout) as e:
                write_log(f"第 {attempt+1} 次 API 请求失败 ({type(e).__name__}): {str(e)}")
                if attempt == MAX_RETRIES - 1:
                    return False
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                write_log(f"处理异常 {img_file.name}: {str(e)}")
                if attempt == MAX_RETRIES - 1:
                    return False
                await asyncio.sleep(2 ** attempt)
                
        return False

def post_process_levels(output_path: Path):
    write_log("开始执行后处理逻辑")
    try:
        merged_files = sorted(list(output_path.glob("*_merged.json")), key=lambda x: natural_sort_key(x.name))
        if not merged_files: 
            write_log("未找到任何合并后的 JSON 文件，跳过后处理")
            return
        
        first_page_file = merged_files[0]
        first_page_max_level = 0
        with open(first_page_file, 'r', encoding='utf-8') as f:
            first_page_data = json.load(f)
            if first_page_data:
                first_page_max_level = max(item.get("level", 0) for item in first_page_data)
        
        write_log(f"首页最大层级检测到：{first_page_max_level}")

        for file in merged_files[1:]:
            with open(file, 'r', encoding='utf-8') as f:
                page_data = json.load(f)
            if not page_data: continue
            
            current_max_level = max(item.get("level", 0) for item in page_data)
            if current_max_level < first_page_max_level:
                level_diff = first_page_max_level - current_max_level
                write_log(f"修正文件 {file.name}: 层级提升 {level_diff}")
                for item in page_data:
                    item["level"] += level_diff
                with open(file, 'w', encoding='utf-8') as f:
                    json.dump(page_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        write_log(f"后处理异常：{str(e)}")

async def run_batch_processing(image_files: list, output_path: Path):
    if not image_files:
        return

    write_log(f"正在预处理并缓存 {len(image_files)} 张图片...")
    for img in image_files:
        get_encoded_image(img)
        
    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    
    # 1. 串行处理第一张图片
    first_img = image_files[0]
    first_csv = output_path / f"{first_img.stem}.csv"
    
    write_log("阶段 1: 处理首图以生成 Few-shot 示例 (CSV 格式)")
    success = await process_first_page(first_img, first_csv, output_path)
    
    if not success:
        write_log("严重错误：首图处理失败，无法生成参考示例，终止后续并发处理。")
        print("首图处理失败，脚本停止。请检查日志。")
        return

    # 2. 并发处理剩余图片
    if len(image_files) > 1:
        write_log("阶段 2: 基于首图示例并发处理剩余图片")
        tasks = []
        for img_file in image_files[1:]:
            csv_file = output_path / f"{img_file.stem}.csv"
            tasks.append(process_level_async(semaphore, img_file, csv_file, output_path))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success_count = sum(1 for r in results if r is True)
        fail_count = sum(1 for r in results if r is False)
        exception_count = sum(1 for r in results if isinstance(r, Exception))
        
        print(f"并发处理完成。成功：{success_count}, 失败/空结果：{fail_count}, 异常：{exception_count}")
    else:
        print("仅有一张图片，处理完毕。")

async def main_async():
    load_dotenv()
    
    global LLM_CONFIG, client
    try:
        LLM_CONFIG = load_llm_config()
    except Exception as e:
        print(f"加载 LLM 配置失败：{e}")
        sys.exit(1)
    
    # 初始化 OpenAI 客户端
    client = AsyncOpenAI(
        api_key=LLM_CONFIG["api_key"],
        base_url=LLM_CONFIG["base_url"],
        timeout=REQUEST_TIMEOUT,
        max_retries=2
    )
    
    base_dir = os.getenv("BASE_DIR")
    if base_dir:
        input_path = Path(base_dir) / "mark" / "input_image"
        output_path = Path(base_dir) / "raw_content"
    else:
        input_path_str = os.getenv("QWEN_VL_EXTRACT_INPUT")
        output_path_str = os.getenv("QWEN_VL_EXTRACT_OUTPUT")
        
        if not input_path_str or not output_path_str:
            print("错误：未设置必要的环境变量 QWEN_VL_EXTRACT_INPUT 或 QWEN_VL_EXTRACT_OUTPUT，且未设置 BASE_DIR")
            sys.exit(1)
            
        input_path = Path(input_path_str)
        output_path = Path(output_path_str)
    
    if not input_path.exists():
        print(f"错误：输入路径不存在 {input_path}")
        sys.exit(1)
        
    if not output_path.exists():
        output_path.mkdir(parents=True, exist_ok=True)
        
    image_files = sorted([f for f in input_path.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS], key=lambda x: natural_sort_key(x.name))
    
    if image_files:
        await run_batch_processing(image_files, output_path)
        post_process_levels(output_path)
    else:
        print("未找到需要处理的图片。")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main_async())