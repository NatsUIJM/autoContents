import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import json
import re
import asyncio
import platform
from pathlib import Path
from openai import AsyncOpenAI
from datetime import datetime
from typing import Dict, List, Tuple
import threading
import traceback

from dotenv import load_dotenv
load_dotenv()

def write_log(message):
    """写入日志到项目根目录的log.txt"""
    try:
        log_file = Path(project_root) / "log.txt"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{threading.current_thread().name}] {message}\n")
    except Exception as e:
        print(f"日志写入失败: {e}")

def extract_json_from_response(response: str) -> dict:
    """从响应字符串中提取 JSON"""
    match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)
    if not match:
        raise ValueError("未能在响应中找到 JSON 代码块")
  
    json_str = match.group(1)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败：{e}\n原始内容：{json_str}")

def postprocess_pattern(pattern: str) -> str:
    """替换模式中未加限定符的[0-9]为[0-9]+，但排除已有数量限定的情况"""
    # 不替换已经有数量限定符的情况（比如[0-9]*、[1-9][0-9]*等）
    def should_replace(match):
        pos = match.end()
        # 检查后面是否已经有限定符
        if pos < len(pattern) and pattern[pos] in '+*?{':
            return match.group(0)
        # 检查是否是类似[1-9][0-9]这样的模式的一部分
        if pos < len(pattern) and pattern[pos:].startswith('[0-9]'):
            return match.group(0)
        # 检查前面是否已经有其他数字相关模式
        before = pattern[:match.start()]
        if before.endswith('[1-9]'):
            return match.group(0)
        return '[0-9]+'

    return re.sub(r'\[0-9\]', should_replace, pattern)

class PatternMatcher:
    def __init__(self, patterns: Dict[int, List[str]]):
        self.patterns = {
            level: [re.compile(pattern) for pattern in pattern_list]
            for level, pattern_list in patterns.items()
        }
        # Find the max level for starting point
        self.max_level = max(patterns.keys())

    def match_level(self, text: str) -> int:
        # Start matching from highest level to lowest
        for level in range(self.max_level, 0, -1):
            if level not in self.patterns:
                continue
        
            for pattern in self.patterns[level]:
                if pattern.match(text):
                    return level
        return 0


def validate_patterns(patterns_json: str) -> Dict[int, List[str]]:
    """验证并解析模型返回的模式"""
    try:
        patterns = json.loads(patterns_json)
        if not isinstance(patterns, dict):
            raise ValueError("Patterns must be a dictionary")
    
        validated_patterns = {}
        for level, pattern_list in patterns.items():
            level_num = int(level)
            if level_num not in [1, 2, 3]:
                continue
            
            if not isinstance(pattern_list, list):
                raise ValueError(f"Patterns for level {level} must be a list")
            
            valid_patterns = []
            for pattern in pattern_list:
                try:
                    # 对pattern进行后处理
                    processed_pattern = postprocess_pattern(pattern)
                    re.compile(processed_pattern)
                    valid_patterns.append(processed_pattern)
                except re.error:
                    print(f"Invalid regex pattern for level {level}: {pattern}")
                    continue
                
            if not valid_patterns:
                raise ValueError(f"No valid patterns for level {level}")
            
            validated_patterns[level_num] = valid_patterns
    
        if not validated_patterns:
            raise ValueError("No valid patterns found")
        
        return validated_patterns
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON format for patterns")

# MODIFIED: 修改返回值类型，增加未匹配标题列表
def apply_patterns_to_items(items: List[dict], pattern_matcher: PatternMatcher) -> Tuple[List[dict], List[str]]:
    """使用模式匹配器为每个项目设置层级，返回处理后的项目和未匹配标题列表"""
    unmatched_titles = []

    for item in items:
        level = pattern_matcher.match_level(item['text'])
        if level > 0:
            item['level'] = level
        else:
            unmatched_titles.append(item['text'])

    return items, unmatched_titles


def prepare_data_for_model(data):
    """移除number、confirmed和level字段"""
    if isinstance(data, dict):
        return {
            key: prepare_data_for_model(value)
            for key, value in data.items()
            if key not in ['number', 'confirmed', 'level']
        }
    elif isinstance(data, list):
        return [prepare_data_for_model(item) for item in data]
    return data

# MODIFIED: 修改保存响应的函数，增加迭代轮次参数
def save_response(content: str, input_filename: str, iteration: int, cache_dir: Path) -> Path:
    """保存响应到缓存目录"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"response_{input_filename}_iteration_{iteration}_{timestamp}.json"
    filepath = cache_dir / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return filepath

# MODIFIED: 新增函数，构建第二次及后续迭代的输入
def prepare_iteration_input(original_json: str, current_patterns: dict, unmatched_titles: List[str]) -> str:
    return json.dumps({
        "original_structure": json.loads(original_json),  # 原始JSON结构
        "current_patterns": current_patterns,            # 当前使用的正则表达式
        "unmatched_titles": unmatched_titles            # 未匹配的标题列表
    }, ensure_ascii=False, indent=2)

async def is_suitable_for_regex(client, items: List[dict]) -> bool:
    """调用LLM判断目录是否适合使用正则表达式处理"""
    # 提取所有标题文本
    titles = [item['text'] for item in items]
    titles_text = "\n".join([f"- {title}" for title in titles])
    
    # 读取路由提示词 - 使用与 qwen_vl_extract.py 相同的路径查找逻辑
    route_prompt_path = Path(project_root) / "static" / "adjuster_prompt_route.md"
    if not route_prompt_path.exists():
        write_log(f"路由提示词文件不存在: {route_prompt_path}")
        raise FileNotFoundError(f"Route prompt file not found: {route_prompt_path}")
    
    with open(route_prompt_path, 'r', encoding='utf-8') as f:
        route_prompt = f.read()
  
    # 将提示词放在system prompt中，目录内容放在user prompt中
    try:
        completion = await client.chat.completions.create(
            model="qwen3-235b-a22b-instruct-2507",
            messages=[
                {"role": "system", "content": route_prompt},
                {"role": "user", "content": f"目录标题如下：\n{titles_text}"}
            ],
            extra_body={"enable_thinking": False},
        )
      
        response = completion.choices[0].message.content.strip()
        return response.lower() == "是"
    except Exception as e:
        write_log(f"调用LLM检查适用性时出错: {e}")
        print(f"Error calling LLM for suitability check: {e}")
        # 出错时默认认为适合处理，避免跳过可能有效的目录
        return True

async def process_file(client, file_path: Path, output_dir: Path, cache_dir: Path):
    try:
        write_log(f"开始处理文件: {file_path}")
        print(f"Processing file: {file_path}")
    
        with open(file_path, 'r', encoding='utf-8') as f:
            original_data = json.load(f)
    
        # 保存原始数据的副本，用于不适合正则处理的情况
        original_data_copy = json.loads(json.dumps(original_data))
    
        # 检查是否适合使用正则表达式处理
        if not await is_suitable_for_regex(client, original_data):
            write_log("目录结构不适合正则表达式处理，直接复制文件")
            print("Directory structure not suitable for regex processing. Copying file directly.")
            output_file = output_dir / file_path.name
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(original_data_copy, f, ensure_ascii=False, indent=2)
            print(f"File copied to: {output_file}")
            write_log(f"文件已复制到: {output_file}")
            return
    
        model_input_data = prepare_data_for_model(original_data)
        model_input_json = json.dumps(model_input_data, ensure_ascii=False, indent=2)
    
        # 读取主提示词 - 使用与 qwen_vl_extract.py 相同的路径查找逻辑
        main_prompt_path = Path(project_root) / "static" / "adjuster_prompt.md"
        if not main_prompt_path.exists():
            write_log(f"主提示词文件不存在: {main_prompt_path}")
            raise FileNotFoundError(f"Main prompt file not found: {main_prompt_path}")
        
        with open(main_prompt_path, 'r', encoding='utf-8') as f:
            system_prompt = f.read()

        # 迭代专用提示词前缀（硬编码）
        iteration_prefix = "请分析这份目录文件中各级标题的结构特征，然后分析当前的正则表达式为何会导致匹配遗漏，给出修正后的正则表达式。\n"

        write_log("开始第一次迭代")
        print("Starting first iteration...")
    
        # First iteration
        current_patterns = None
        best_patterns = None
        unmatched_titles = []
    
        for iteration in range(1, 5):  # 最多4次尝试
            write_log(f"开始第 {iteration} 次迭代")
            print(f"\nIteration {iteration}:")
        
            if iteration == 1:
                # First iteration uses original input and prompt
                stream = await client.chat.completions.create(
                    model="qwen-max",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": model_input_json}
                    ],
                    extra_body={"enable_thinking": True},  # 可选：是否需要思考过程
                    stream=True
                )
            else:
                # Subsequent iterations use iteration input and prompt
                iteration_input = prepare_iteration_input(
                    model_input_json,           # 原始JSON
                    current_patterns,           # 当前正则表达式
                    unmatched_titles           # 未匹配标题
                )
                stream = await client.chat.completions.create(

                    model="qwen-max",  # 修改为 qwen3-235b-a22b
                    messages=[
                        {"role": "system", "content": iteration_prefix + system_prompt},
                        {"role": "user", "content": iteration_input}
                    ],
                    response_format={"type": "json_object"},
                    stream=True
                )

            write_log("正在接收模型响应...")
            print("Receiving response...")
            accumulated_response = ""
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    accumulated_response += content
                    print(content, end='', flush=True)

            # 保存响应
            cache_file = save_response(
                accumulated_response,
                file_path.stem,
                iteration,
                cache_dir
            )
            write_log(f"响应已保存到: {cache_file}")
            print(f"\nResponse saved to: {cache_file}")

            try:
                json_content = extract_json_from_response(accumulated_response)
                current_patterns = validate_patterns(json.dumps(json_content))
                if not current_patterns:
                    raise ValueError("No valid patterns found in model response")
            
                pattern_matcher = PatternMatcher(current_patterns)
            
                # 应用模式进行匹配
                processed_items, new_unmatched = apply_patterns_to_items(
                    original_data.copy(),  # 使用副本避免修改原数据
                    pattern_matcher
                )
            
                # 保存第二次迭代的结果作为最佳结果
                if iteration == 2:
                    best_patterns = current_patterns
            
                # 检查是否还有未匹配的标题
                if not new_unmatched:
                    write_log("所有标题都已成功匹配!")
                    print("All titles matched successfully!")
                    best_patterns = current_patterns  # 更新最佳结果
                    break
            
                unmatched_titles = new_unmatched
                write_log(f"未匹配标题数量: {len(unmatched_titles)}")
                print(f"\nUnmatched titles count: {len(unmatched_titles)}")
            
                if iteration >= 4:  # 第四次迭代后使用第二次的结果
                    write_log("已达最大迭代次数，使用第二次迭代的结果")
                    print("\nMaximum iterations reached. Using results from second iteration.")
                    current_patterns = best_patterns
                    break
            
            except Exception as e:
                write_log(f"处理模式时出错: {str(e)}")
                print(f"\nError processing patterns: {str(e)}")
                if iteration == 1:
                    raise  # 第一次迭代失败时直接退出
                break  # 后续迭代失败时使用之前的结果
    
        # 使用最终的模式处理数据
        final_pattern_matcher = PatternMatcher(best_patterns or current_patterns)
        original_data, _ = apply_patterns_to_items(
            original_data,
            final_pattern_matcher
        )
    
        # 保存结果
        output_file = output_dir / file_path.name
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(original_data, f, ensure_ascii=False, indent=2)
        write_log(f"处理完成，最终输出已保存到: {output_file}")
        print(f"\nProcessing complete. Final output saved to: {output_file}")
        
    except Exception as e:
        error_msg = f"处理 {file_path.name} 时出错:\n类型: {type(e).__name__}\n信息: {str(e)}"
        write_log(error_msg)
        print(f"\nError processing {file_path.name}:")
        print(f"Type: {type(e).__name__}")
        print(f"Message: {str(e)}")
        write_log("完整错误追踪:")
        write_log(traceback.format_exc())
        print("\nFull traceback:")
        traceback.print_exc()

async def main():
    write_log("=== llm_level_adjuster.py 开始执行 ===")
    # Setup directories
    input_dir = Path(os.getenv("LEVEL_ADJUSTER_INPUT"))
    output_dir = Path(os.getenv("LEVEL_ADJUSTER_OUTPUT"))
    cache_dir = Path(os.getenv("LEVEL_ADJUSTER_CACHE"))

    for dir_path in [output_dir, cache_dir]:
        os.makedirs(dir_path, exist_ok=True)

    # Initialize client
    client = AsyncOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    # Process all JSON files
    tasks = []
    for file_path in input_dir.glob("*.json"):
        tasks.append(process_file(client, file_path, output_dir, cache_dir))

    await asyncio.gather(*tasks)
    write_log("=== llm_level_adjuster.py 执行完成 ===")

if __name__ == "__main__":
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
