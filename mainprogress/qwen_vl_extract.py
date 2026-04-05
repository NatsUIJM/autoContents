import os
import json
import asyncio
import aiohttp
import base64
import traceback
import sys
import re
from pathlib import Path
from io import BytesIO
from dotenv import load_dotenv

# 图像处理库
from PIL import Image

# 配置常量
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}
MAX_IMAGE_DIMENSION = 1500  # 最长边限制
CONCURRENT_LIMIT = 15       # 最大并发数
MAX_RETRIES = 5             # 单任务最大重试次数

# 全局变量用于存储提示词和配置
PROMPT_TEXT = ""
LLM_CONFIG = {}

def write_log(message):
    """写入日志到项目根目录的 log.txt"""
    try:
        project_root = Path(__file__).parent.parent
        log_file = project_root / "log.txt"
    
        # 异步环境下同步写文件通常是安全的，因为操作很快
        # 如果需要极高频率写入，可考虑异步文件操作，但此处同步足够
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[AsyncIO] {message}\n")
    except Exception as e:
        print(f"日志写入失败：{e}")

def load_llm_config() -> dict:
    """从 static 文件夹加载 LLM 配置，并解析环境变量"""
    project_root = Path(__file__).parent.parent
    config_path = project_root / "static" / "llm_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"LLM 配置文件不存在：{config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
        
    def resolve_value(val):
        if isinstance(val, str) and val.startswith('$') and val.endswith('$'):
            env_var_name = val[1:-1]
            return os.getenv(env_var_name)
        return val

    return {
        "api_key": resolve_value(config.get("api_key")),
        "base_url": resolve_value(config.get("base_url")),
        "model": resolve_value(config.get("model"))
    }

def load_prompt():
    """从 static/extract_prompt.md 加载提示词"""
    try:
        prompt_path = Path(__file__).parent.parent / "static" / "extract_prompt.md"
        if not prompt_path.exists():
            write_log(f"提示词文件不存在：{prompt_path}")
            raise FileNotFoundError(f"提示词文件不存在：{prompt_path}")
        
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_text = f.read()
        
        write_log("成功加载提示词")
        return prompt_text
    except Exception as e:
        write_log(f"加载提示词时发生异常：{str(e)}")
        write_log(traceback.format_exc())
        raise

def resize_and_encode_image(image_path: Path) -> str:
    """
    读取图片，如果最长边超过 MAX_IMAGE_DIMENSION 则缩放，然后转换为 base64 JPEG 格式。
    """
    with Image.open(image_path) as img:
        # 转换模式以确保兼容性 (处理 RGBA 等)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        width, height = img.size
        max_dim = max(width, height)
        
        if max_dim > MAX_IMAGE_DIMENSION:
            ratio = MAX_IMAGE_DIMENSION / max_dim
            new_width = int(width * ratio)
            new_height = int(height * ratio)
            img = img.resize((new_width, new_height), Image.LANCZOS)
            write_log(f"图片 {image_path.name} 已缩放：{width}x{height} -> {new_width}x{new_height}")
        else:
            write_log(f"图片 {image_path.name} 尺寸符合要求：{width}x{height}")
        
        # 保存到内存缓冲区
        buffer = BytesIO()
        # 即使原图是 PNG，也统一压缩为 JPEG 以减小体积发送给模型，除非原图格式必须保留透明通道（但 VL 模型通常不需要）
        # 这里为了通用性和体积优化，强制输出 JPEG
        img.save(buffer, format="JPEG", quality=85, optimize=True)
        
        base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
        return f"data:image/jpeg;base64,{base64_image}"

async def process_image_async(session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, image_path: Path, output_path: Path):
    """
    异步处理单个图像文件
    """
    async with semaphore:
        # 断点续传检查：如果输出文件已存在，直接跳过
        output_file = output_path / (image_path.stem + '_merged.json')
        if output_file.exists():
            write_log(f"跳过已处理文件：{image_path.name}")
            return None

        write_log(f"开始处理图像：{image_path}")
        
        try:
            # 1. 图片预处理（缩放 + 编码）
            try:
                image_data_url = resize_and_encode_image(image_path)
            except Exception as img_err:
                write_log(f"图片预处理失败 {image_path}: {str(img_err)}")
                return None

            # 2. 构建请求 Payload
            payload = {
                "model": LLM_CONFIG["model"],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                            {"type": "text", "text": PROMPT_TEXT}
                        ]
                    }
                ],
                "response_format": {"type": "json_object"},
                "extra_body": {"enable_thinking": False}
            }

            headers = {
                "Authorization": f"Bearer {LLM_CONFIG['api_key']}",
                "Content-Type": "application/json"
            }

            result_data = None
            
            # 3. 重试循环
            for attempt in range(MAX_RETRIES):
                try:
                    write_log(f"第 {attempt+1} 次尝试调用模型：{image_path.name}")
                    
                    async with session.post(LLM_CONFIG["base_url"] + "/chat/completions", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            raise Exception(f"API 返回错误状态码 {response.status}: {error_text}")
                        
                        resp_json = await response.json()
                        
                        # 解析响应内容
                        content = resp_json["choices"][0]["message"]["content"].strip()
                        
                        if not content:
                            write_log(f"模型返回空内容，重试...")
                            continue

                        # 调试输出
                        print(f"[DEBUG] {image_path.name} 模型响应长度：{len(content)}")

                        # 解析 JSON
                        try:
                            directory_data = json.loads(content)
                        except json.JSONDecodeError:
                            write_log(f"JSON 解析失败，原始内容片段：{content[:200]}...")
                            # 保存错误响应
                            error_dir = output_path / "error"
                            error_dir.mkdir(exist_ok=True)
                            error_file = error_dir / (image_path.stem + '_error_response.json')
                            with open(error_file, 'w', encoding='utf-8') as f:
                                json.dump({"raw_response": content}, f, ensure_ascii=False, indent=2)
                            continue # 进入下一次重试

                        # 数据重构逻辑 (保持与原代码一致)
                        flattened_data = []
                        if isinstance(directory_data, dict):
                            for level_key, items in directory_data.items():
                                if level_key.startswith("level_") and isinstance(items, list):
                                    try:
                                        level = int(level_key.split("_")[1])
                                        for item in items:
                                            if isinstance(item, dict) and 't' in item:
                                                text = item["t"]
                                                flattened_item = {
                                                    "text": text,
                                                    "number": item.get("n", None),
                                                    "level": level
                                                }
                                                flattened_data.append(flattened_item)
                                    except (ValueError, IndexError):
                                        continue
                        
                        # 过滤和排序
                        filtered_data = [item for item in flattened_data if isinstance(item["number"], int)]
                        sorted_data = sorted(filtered_data, key=lambda x: x['number'])
                        
                        if sorted_data:
                            # 立即保存结果 (断点续传关键)
                            with open(output_file, 'w', encoding='utf-8') as f:
                                json.dump(sorted_data, f, ensure_ascii=False, indent=2)
                            
                            write_log(f"结果保存成功：{output_file}")
                            print(f"已处理：{image_path.name}")
                            result_data = sorted_data
                            break # 成功，跳出重试循环
                        else:
                            write_log(f"解析后无有效数据，重试...")
                            # 保存原始响应以便调试
                            error_dir = output_path / "error"
                            error_dir.mkdir(exist_ok=True)
                            error_file = error_dir / (image_path.stem + '_empty_result.json')
                            with open(error_file, 'w', encoding='utf-8') as f:
                                json.dump(directory_data, f, ensure_ascii=False, indent=2)
                            continue

                except Exception as e:
                    write_log(f"第 {attempt+1} 次尝试失败：{str(e)}")
                    if attempt == MAX_RETRIES - 1:
                        print(f"处理 {image_path.name} 失败，已达到最大重试次数")
                        write_log(f"处理 {image_path.name} 最终失败")
            
            return result_data

        except Exception as e:
            write_log(f"处理图像时发生未捕获异常：{image_path}")
            write_log(f"错误信息：{str(e)}")
            write_log(traceback.format_exc())
            return None

async def run_batch_processing(image_files: list, output_path: Path):
    """
    主异步入口：创建会话并并发执行任务
    """
    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    
    # 配置 aiohttp Connector 以支持高并发
    connector = aiohttp.TCPConnector(limit=CONCURRENT_LIMIT, limit_per_host=CONCURRENT_LIMIT)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            process_image_async(session, semaphore, img_file, output_path)
            for img_file in image_files
        ]
        
        # 使用 gather 并发执行，返回结果列表
        # return_exceptions=True 防止单个任务崩溃导致整个程序退出
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if r is not None and not isinstance(r, Exception))
        write_log(f"批量处理完成，成功：{success_count}, 总数：{len(image_files)}")
        print(f"处理完成，共成功处理 {success_count} 个文件")

def post_process_levels(output_path: Path):
    """后处理逻辑：调整各页的 level 值 (保持原有同步逻辑，因不涉及网络 IO)"""
    write_log("开始执行后处理逻辑")
  
    try:
        merged_files = list(output_path.glob("*_merged.json"))
        if not merged_files:
            write_log("未找到任何 merged.json 文件，跳过后处理")
            return
          
        page_info = []
        for file in merged_files:
            match = re.search(r"page_(\d+)_merged\.json$", file.name)
            if match:
                page_num = int(match.group(1))
                page_info.append((page_num, file))
      
        page_info.sort(key=lambda x: x[0])
      
        if not page_info:
            write_log("未找到符合命名规则的页面文件，跳过后处理")
            return
          
        first_page_file = page_info[0][1]
        write_log(f"首页文件：{first_page_file.name}")
      
        first_page_max_level = 0
        if first_page_file.exists():
            with open(first_page_file, 'r', encoding='utf-8') as f:
                first_page_data = json.load(f)
                if first_page_data:
                    first_page_max_level = max(item.get("level", 0) for item in first_page_data)
        write_log(f"首页最大 level 值：{first_page_max_level}")
      
        for page_num, file in page_info[1:]:
            write_log(f"处理页面：{file.name}")
          
            if not file.exists():
                continue
              
            with open(file, 'r', encoding='utf-8') as f:
                page_data = json.load(f)
              
            if not page_data:
                continue
              
            current_max_level = max(item.get("level", 0) for item in page_data)
            write_log(f"页面 {file.name} 最大 level 值：{current_max_level}")
          
            if current_max_level < first_page_max_level:
                level_diff = first_page_max_level - current_max_level
                write_log(f"页面 {file.name} 需要调整，level 差值：{level_diff}")
              
                for item in page_data:
                    item["level"] += level_diff
                  
                with open(file, 'w', encoding='utf-8') as f:
                    json.dump(page_data, f, ensure_ascii=False, indent=2)
                  
                write_log(f"页面 {file.name} level 值调整完成")
            else:
                write_log(f"页面 {file.name} 无需调整")
              
        write_log("后处理逻辑执行完成")
      
    except Exception as e:
        write_log(f"后处理逻辑执行时发生异常：{str(e)}")
        write_log(traceback.format_exc())

async def main_async():
    write_log("=== qwen_vl_extract.py (Async Version) 开始执行 ===")

    try:
        # 1. 加载配置
        global LLM_CONFIG, PROMPT_TEXT
        try:
            LLM_CONFIG = load_llm_config()
            if not LLM_CONFIG.get("api_key"):
                raise ValueError("API Key 不能为空")
            write_log("LLM 配置加载成功")
        except Exception as e:
            write_log(f"配置加载失败：{str(e)}")
            print(f"配置加载失败：{e}")
            sys.exit(1)

        try:
            PROMPT_TEXT = load_prompt()
        except Exception as e:
            write_log(f"无法加载提示词，程序退出：{str(e)}")
            sys.exit(1)

        # 2. 确定路径
        base_dir = os.getenv("BASE_DIR")
        if base_dir:
            input_path = Path(base_dir) / "mark" / "input_image"
            output_path = Path(base_dir) / "raw_content"
            write_log(f"使用会话目录路径：{base_dir}")
        else:
            input_path_str = os.getenv("QWEN_VL_EXTRACT_INPUT")
            output_path_str = os.getenv("QWEN_VL_EXTRACT_OUTPUT")
            
            if not input_path_str or not output_path_str:
                write_log("错误：未设置必要的环境变量")
                print("错误：未设置必要的环境变量")
                sys.exit(1)
            
            input_path = Path(input_path_str)
            output_path = Path(output_path_str)
    
        write_log(f"输入路径：{input_path}")
        write_log(f"输出路径：{output_path}")
    
        # 3. 准备文件列表
        if not input_path.exists():
            write_log(f"输入路径不存在：{input_path}")
            print(f"输入路径不存在：{input_path}")
            sys.exit(1)
        
        image_files = [f for f in input_path.iterdir() 
                       if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
    
        write_log(f"找到 {len(image_files)} 个图像文件")
        print(f"找到 {len(image_files)} 个图像文件，开始异步处理...")
    
        if not image_files:
            print("没有发现需要处理的图片文件。")
            return

        # 4. 确保输出目录存在
        output_path.mkdir(parents=True, exist_ok=True)
    
        # 5. 运行异步批处理
        await run_batch_processing(image_files, output_path)
      
        # 6. 执行后处理
        post_process_levels(output_path)
    
    except Exception as e:
        write_log(f"主函数执行时发生异常：{str(e)}")
        write_log(traceback.format_exc())
        print(f"主函数执行时发生异常：{e}")
        traceback.print_exc()
        sys.exit(1)

def main():
    """入口函数，启动 asyncio 事件循环"""
    # 兼容不同平台的启动策略
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(main_async())

if __name__ == "__main__":
    main()