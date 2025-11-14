import os
import json
from openai import OpenAI
from pathlib import Path
import base64
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import traceback
import sys
import re

# 用户提示词作为全局变量，便于修改
PROMPT_TEXT = """
请分析这张图片，提取其中的目录信息。
对于每个目录项，请提供：标题（t）和页码（n）以及层级（level）。
注意：
1. 只需提取目录内容，不要包含其他文本
2. 你的任务只有一个，就是按照规范提取这个页面上的信息，请不要进行任何添加。例如当一个页面是以4.5.1开头时，你不需要（并且严格禁止）估计第四章的标题和4.5节的标题，而应该直接提取你所见到的全部内容。
3. 严格按照以下JSON格式返回（此处以共2级的目录为例，实际应根据你看到的图片而定），不要包含任何额外文本或说明：
{
  "level_1": [
    {"t": "一级标题1", "n": 1},
    {"t": "一级标题2", "n": 25}
  ],
  "level_2": [
    {"t": "二级标题1", "n": 5},
    {"t": "二级标题2", "n": 8}
  ]
}
4. 不要遗漏任何目录项目，但是需要忽略"前言"或"第x版前言"这种与正文一点关系都没有的条目，有一些条目没有直接显示页码，并不代表它们不是目录条目，请基于具体语义而非是否有规范的格式来判断一个内容是否是目录的一部分
5. 需严格按照原始目录的语言提取，如果出现繁体中文或英文等非简体中文文字，需直接提取原始内容，而不是全部翻译为简体中文
6. 关于目录层级，应严格按照图片呈现出的层级特征（比如颜色、字体、文字大小等）而不是语义来进行判断。
7. 部分目录条目缺失页码，请根据其附近的内容合理估测。例如当第1篇的页码丢失，而第1篇的第1章的页码为2时，那么估算第1篇的页码也是2。
8. 特别注意：关于层级判定的易错点：
    1. 关于篇和章的常见错误：
```json
level_1: [
    {"t": "xx篇", "n": null}, // 错误：没有估算页码
    {"t": "xx章", "n": 1}
    {"t": "xx章", "n": 5} // 错误：如果xx篇为第一层级，那么xx章一定是第二层级；
  ]
```

正确：
```json
level_1: [
    {"t": "xx篇", "n": 1} // 正确：根据其附近的页码进行了合理推算
  ],
level_2: [
    {"t": "xx章", "n": 1},
    {"t": "xx章", "n": 5}
  ]
}

    2. 关于节和子节的常见错误：
```json
  {
    "text": "2.4 典型全控型器件",
    "number": 25,
    "level": 2
  },
  {
    "text": "2.4.1 门极可关断晶闸管",
    "number": 26,
    "level": 2
  }, // 错误：2.4是节，2.4.1是子节，它们不可能具有相同的目录层级，子节的层级必须比节的层级低一级

```
9. 对于如何安排空格：
    1. 纯中文目录，确保目录项的标题和页码之间有1个空格，除此之外不要加入任何空格。
        1. `第1章 自动控制概述`正确；`第 1章 自动控制概述`错误；`第1 章自动控制概述`错误
        2. `第2章 超前滞后校正与PID校正`正确；`第2章 超前滞后校正与 PID校正`错误；`第2章 超前滞后校正与PID 校正`错误
    2. 纯英文目录，按照英语的标准语法处理即可。单词和数字之间应保留空格。
    3. 混合目录，按照上述规则处理中文部分，按照英语的语法处理英文部分。  
"""

# 添加日志记录功能
def write_log(message):
    """写入日志到项目根目录的log.txt"""
    try:
        # 获取项目根目录
        project_root = Path(__file__).parent.parent
        log_file = project_root / "log.txt"
    
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{threading.current_thread().name}] {message}\n")
    except Exception as e:
        print(f"日志写入失败: {e}")

# 加载环境变量
load_dotenv()

# 初始化客户端
try:
    client = OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    write_log("OpenAI客户端初始化成功")
except Exception as e:
    write_log(f"OpenAI客户端初始化失败: {str(e)}")
    write_log(traceback.format_exc())
    raise

# 支持的图像格式
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}

# 线程锁用于进度输出
progress_lock = threading.Lock()

def process_image(image_path: Path, output_path: Path):
    write_log(f"开始处理图像: {image_path}")

    try:
        # 检查文件是否存在
        if not image_path.exists():
            write_log(f"图像文件不存在: {image_path}")
            return None
        
        # 将图像编码为base64
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            image_data_url = f"data:image/jpeg;base64,{base64_image}"
    
        write_log(f"图像编码完成: {image_path.name}")

        for attempt in range(5):
            try:
                write_log(f"第{attempt+1}次尝试调用模型: {image_path.name}")
            
                completion = client.chat.completions.create(
                    model="qwen3-vl-235b-a22b-instruct",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": image_data_url}},
                                {"type": "text", "text": PROMPT_TEXT}  # 使用全局变量
                            ]
                        }
                    ],
                    response_format={"type": "json_object"}  # 强制JSON格式响应
                )

                # 解析响应
                response_content = completion.choices[0].message.content.strip()
            
                write_log(f"模型响应内容长度: {len(response_content)} 字符")

                # 调试输出原始响应内容
                with progress_lock:
                    print(f"[DEBUG] 模型原始响应内容: {response_content}")

                # 如果响应为空，跳过解析
                if not response_content:
                    with progress_lock:
                        print(f"处理 {image_path.name} 第{attempt+1}次尝试失败，模型返回空内容")
                    write_log(f"处理 {image_path.name} 第{attempt+1}次尝试失败，模型返回空内容")
                    continue

                directory_data = json.loads(response_content)
            
                write_log(f"JSON解析成功: {image_path.name}")

                # 验证数据结构并重构
                if isinstance(directory_data, dict):
                    # 创建扁平化的结果列表
                    flattened_data = []
                
                    # 遍历所有level_x的键
                    for level_key, items in directory_data.items():
                        if level_key.startswith("level_") and isinstance(items, list):
                            try:
                                level = int(level_key.split("_")[1])
                                for item in items:
                                    if isinstance(item, dict) and 't' in item:
                                        # 保持原始文本，不再去除空格
                                        text = item["t"]
                                        # 重构为包含level的扁平结构
                                        flattened_item = {
                                            "text": text,
                                            "number": item.get("n", None),
                                            "level": level
                                        }
                                        flattened_data.append(flattened_item)
                            except (ValueError, IndexError):
                                continue  # 跳过无法解析的level键
                
                    if flattened_data:
                        # 过滤掉页码非int类型的条目
                        filtered_data = [item for item in flattened_data if isinstance(item["number"], int)]
                      
                        # 按照number字段排序
                        sorted_data = sorted(filtered_data, key=lambda x: x['number'])
                    
                        # 保存到JSON文件
                        output_file = output_path / (image_path.stem + '_merged.json')
                        with open(output_file, 'w', encoding='utf-8') as f:
                            json.dump(sorted_data, f, ensure_ascii=False, indent=2)
                    
                        write_log(f"结果保存成功: {output_file}")
                    
                        with progress_lock:
                            print(f"已处理: {image_path.name} -> {output_file.name}")
                        return sorted_data  # 成功处理后返回数据
            
                # 如果数据格式不正确，保存错误响应到error目录
                error_dir = output_path / "error"
                error_dir.mkdir(exist_ok=True)
                error_file = error_dir / (image_path.stem + '_error_response.json')
                with open(error_file, 'w', encoding='utf-8') as f:
                    json.dump({"raw_response": response_content}, f, ensure_ascii=False, indent=2)
            
                with progress_lock:
                    print(f"处理 {image_path.name} 第{attempt+1}次尝试失败，数据格式不正确，重新尝试...")
                write_log(f"处理 {image_path.name} 第{attempt+1}次尝试失败，数据格式不正确，重新尝试...")
            
            except json.JSONDecodeError as e:
                # 保存错误响应到error目录
                error_dir = output_path / "error"
                error_dir.mkdir(exist_ok=True)
                error_file = error_dir / (image_path.stem + '_error_response.json')
                with open(error_file, 'w', encoding='utf-8') as f:
                    json.dump({"raw_response": response_content}, f, ensure_ascii=False, indent=2)
            
                with progress_lock:
                    print(f"处理 {image_path.name} 第{attempt+1}次尝试失败，JSON解析错误: {e}")
                write_log(f"处理 {image_path.name} 第{attempt+1}次尝试失败，JSON解析错误: {str(e)}")
                write_log(traceback.format_exc())
            except Exception as e:
                with progress_lock:
                    print(f"处理 {image_path.name} 第{attempt+1}次尝试失败，错误: {e}")
                write_log(f"处理 {image_path.name} 第{attempt+1}次尝试失败，错误: {str(e)}")
                write_log(traceback.format_exc())
    
        with progress_lock:
            print(f"处理 {image_path.name} 失败，已达到最大重试次数")
        write_log(f"处理 {image_path.name} 失败，已达到最大重试次数")
        return None
    
    except Exception as e:
        write_log(f"处理图像时发生异常: {image_path}")
        write_log(f"错误信息: {str(e)}")
        write_log(traceback.format_exc())
        return None

def post_process_levels(output_path: Path):
    """后处理逻辑：调整各页的level值"""
    write_log("开始执行后处理逻辑")
  
    try:
        # 获取所有merged.json文件
        merged_files = list(output_path.glob("*_merged.json"))
        if not merged_files:
            write_log("未找到任何merged.json文件，跳过后处理")
            return
          
        # 提取页码信息并排序
        page_info = []
        for file in merged_files:
            # 使用正则表达式提取页码
            match = re.search(r"page_(\d+)_merged\.json$", file.name)
            if match:
                page_num = int(match.group(1))
                page_info.append((page_num, file))
      
        # 按页码排序
        page_info.sort(key=lambda x: x[0])
      
        if not page_info:
            write_log("未找到符合命名规则的页面文件，跳过后处理")
            return
          
        # 确定首页
        first_page_file = page_info[0][1]
        write_log(f"首页文件: {first_page_file.name}")
      
        # 计算首页的最大level值
        first_page_max_level = 0
        if first_page_file.exists():
            with open(first_page_file, 'r', encoding='utf-8') as f:
                first_page_data = json.load(f)
                if first_page_data:
                    first_page_max_level = max(item.get("level", 0) for item in first_page_data)
        write_log(f"首页最大level值: {first_page_max_level}")
      
        # 处理除首页外的其他页面
        for page_num, file in page_info[1:]:
            write_log(f"处理页面: {file.name}")
          
            if not file.exists():
                write_log(f"文件不存在，跳过: {file.name}")
                continue
              
            # 读取当前页面数据
            with open(file, 'r', encoding='utf-8') as f:
                page_data = json.load(f)
              
            if not page_data:
                write_log(f"页面数据为空，跳过: {file.name}")
                continue
              
            # 计算当前页面的最大level值
            current_max_level = max(item.get("level", 0) for item in page_data)
            write_log(f"页面 {file.name} 最大level值: {current_max_level}")
          
            # 如果当前页面最大level值小于首页最大level值，则需要调整
            if current_max_level < first_page_max_level:
                level_diff = first_page_max_level - current_max_level
                write_log(f"页面 {file.name} 需要调整，level差值: {level_diff}")
              
                # 调整所有level值
                for item in page_data:
                    item["level"] += level_diff
                  
                # 保存更新后的数据
                with open(file, 'w', encoding='utf-8') as f:
                    json.dump(page_data, f, ensure_ascii=False, indent=2)
                  
                write_log(f"页面 {file.name} level值调整完成")
            else:
                write_log(f"页面 {file.name} 无需调整")
              
        write_log("后处理逻辑执行完成")
      
    except Exception as e:
        write_log(f"后处理逻辑执行时发生异常: {str(e)}")
        write_log(traceback.format_exc())

def main():
    write_log("=== qwen_vl_extract.py 开始执行 ===")

    try:
        # 检查BASE_DIR环境变量是否存在
        base_dir = os.getenv("BASE_DIR")
        if base_dir:
            # 使用会话目录路径
            input_path = Path(base_dir) / "mark" / "input_image"
            output_path = Path(base_dir) / "raw_content"
            write_log(f"使用会话目录路径: {base_dir}")
        else:
            # 回退到原来的环境变量
            input_path_str = os.getenv("QWEN_VL_EXTRACT_INPUT")
            output_path_str = os.getenv("QWEN_VL_EXTRACT_OUTPUT")
            write_log(f"环境变量 QWEN_VL_EXTRACT_INPUT: {input_path_str}")
            write_log(f"环境变量 QWEN_VL_EXTRACT_OUTPUT: {output_path_str}")
        
            if not input_path_str or not output_path_str:
                write_log("错误: 未设置必要的环境变量")
                print("错误: 未设置必要的环境变量")
                return
            
            input_path = Path(input_path_str)
            output_path = Path(output_path_str)
    
        write_log(f"输入路径: {input_path}")
        write_log(f"输出路径: {output_path}")
        write_log(f"输入路径是否存在: {input_path.exists()}")
        write_log(f"输出路径是否存在: {output_path.exists()}")
    
        # 确保输出目录存在
        output_path.mkdir(parents=True, exist_ok=True)
        write_log(f"输出目录创建完成: {output_path}")
    
        # 获取所有图像文件
        if not input_path.exists():
            write_log(f"输入路径不存在: {input_path}")
            print(f"输入路径不存在: {input_path}")
            return
        
        image_files = [f for f in input_path.iterdir() 
                       if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
    
        write_log(f"找到 {len(image_files)} 个图像文件")
        print(f"找到 {len(image_files)} 个图像文件，开始处理...")
    
        # 使用线程池并发处理，最大并发度9
        with ThreadPoolExecutor(max_workers=9) as executor:
            # 提交所有任务
            future_to_image = {executor.submit(process_image, image_file, output_path): image_file 
                              for image_file in image_files}
        
            # 收集结果
            results = []
            for future in as_completed(future_to_image):
                image_file = future_to_image[future]
                try:
                    result = future.result()
                    if result is not None:
                        results.append((image_file.stem, result))
                except Exception as e:
                    with progress_lock:
                        print(f"处理 {image_file.name} 时发生异常: {e}")
                    write_log(f"处理 {image_file.name} 时发生异常: {str(e)}")
                    write_log(traceback.format_exc())
    
        write_log(f"处理完成，共处理 {len(results)} 个文件")
        print(f"处理完成，共处理 {len(results)} 个文件")
      
        # 执行后处理逻辑
        post_process_levels(output_path)
    
    except Exception as e:
        write_log(f"主函数执行时发生异常: {str(e)}")
        write_log(traceback.format_exc())
        print(f"主函数执行时发生异常: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()