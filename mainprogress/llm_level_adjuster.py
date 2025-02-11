"""
文件名: llm_level_adjuster.py
功能: 使用DeepSeek模型调整目录层级结构，通过正则表达式识别层级特征
"""
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

from dotenv import load_dotenv
load_dotenv()

def fix_backslashes(patterns_json: str) -> str:
    """修复模型输出中未正确转义的反斜杠，处理更多的特殊情况"""
    # 分步骤处理不同情况的反斜杠修复
    
    # 1. 修复未转义的反斜杠（标准正则特殊字符）
    special_chars = 'sSwWdDbB'
    for char in special_chars:
        patterns_json = re.sub(
            f'(?<!\\\\)\\(?!\\\\)(?={char})', 
            r'\\\\', 
            patterns_json
        )
    
    # 2. 修复空白字符的反斜杠
    patterns_json = re.sub(
        r'(?<!\\)\\(?!\\)(?=s\s)', 
        r'\\\\', 
        patterns_json
    )
    
    # 3. 修复点号前的反斜杠
    patterns_json = re.sub(
        r'(?<!\\)\\(?!\\)(?=\.)', 
        r'\\\\', 
        patterns_json
    )
    
    # 4. 确保所有剩余的单反斜杠被正确转义
    patterns_json = re.sub(
        r'(?<!\\)\\(?![\\/"bfnrt])', 
        r'\\\\', 
        patterns_json
    )
    
    return patterns_json

def clean_model_response(response: str) -> str:
    """清理模型响应中的代码块标记并进行初步格式修复"""
    # 移除代码块标记
    response = re.sub(r'^```\s*json\s*\n', '', response)
    response = re.sub(r'\n```\s*$', '', response)
    response = response.strip()
    
    # 尝试修复常见的JSON格式错误
    # 1. 修复缺失的引号
    response = re.sub(r'(\w+):', r'"\1":', response)
    
    # 2. 修复错误的空格
    response = re.sub(r'\s+,', ',', response)
    response = re.sub(r',\s+', ', ', response)
    
    # 3. 移除注释行
    response = re.sub(r'\s*//.*$', '', response, flags=re.MULTILINE)
    
    return response

class PatternMatcher:
    def __init__(self, patterns: Dict[int, List[str]]):
        self.patterns = {
            level: [re.compile(pattern) for pattern in pattern_list]
            for level, pattern_list in patterns.items()
        }
    
    def match_level(self, text: str) -> int:
        for level, pattern_list in self.patterns.items():
            for pattern in pattern_list:
                if pattern.match(text):
                    return level
        return 0

def validate_patterns(patterns_json: str) -> Dict[int, List[str]]:
    """验证并解析模型返回的模式，包含更多的错误处理"""
    try:
        # 首先尝试修复反斜杠
        fixed_json = fix_backslashes(patterns_json)
        
        try:
            patterns = json.loads(fixed_json)
        except json.JSONDecodeError as e:
            # 如果仍然失败，尝试进一步清理和修复
            cleaned_json = clean_model_response(fixed_json)
            fixed_cleaned_json = fix_backslashes(cleaned_json)
            patterns = json.loads(fixed_cleaned_json)
        
        if not isinstance(patterns, dict):
            raise ValueError("Patterns must be a dictionary")
        
        validated_patterns = {}
        for level, pattern_list in patterns.items():
            level_num = int(level)
            if level_num not in [1, 2, 3]:
                print(f"Skipping invalid level: {level}")
                continue
                
            if not isinstance(pattern_list, list):
                print(f"Skipping invalid pattern list for level {level}")
                continue
                
            valid_patterns = []
            for pattern in pattern_list:
                try:
                    # 尝试编译正则表达式
                    re.compile(pattern)
                    valid_patterns.append(pattern)
                except re.error as e:
                    print(f"Invalid regex pattern for level {level}: {pattern}")
                    print(f"Error: {str(e)}")
                    # 尝试修复pattern并重试
                    try:
                        fixed_pattern = fix_backslashes(pattern)
                        re.compile(fixed_pattern)
                        valid_patterns.append(fixed_pattern)
                        print(f"Successfully fixed pattern: {fixed_pattern}")
                    except re.error:
                        continue
                    
            if valid_patterns:
                validated_patterns[level_num] = valid_patterns
        
        if not validated_patterns:
            raise ValueError("No valid patterns found after processing")
            
        if 1 not in validated_patterns or 2 not in validated_patterns:
            raise ValueError("Must have patterns for both level 1 and 2")
            
        return validated_patterns
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {str(e)}")
        raise ValueError(f"Invalid JSON format for patterns: {str(e)}")
    except Exception as e:
        print(f"Unexpected error during pattern validation: {str(e)}")
        raise

#MODIFIED: 修改返回值类型，增加未匹配标题列表
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

#MODIFIED: 修改保存响应的函数，增加迭代轮次参数
def save_response(content: str, input_filename: str, iteration: int, cache_dir: Path) -> Path:
    """保存响应到缓存目录"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"response_{input_filename}_iteration_{iteration}_{timestamp}.json"
    filepath = cache_dir / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return filepath

#MODIFIED: 新增函数，构建第二次及后续迭代的输入
def prepare_iteration_input(original_json: str, current_patterns: dict, unmatched_titles: List[str]) -> str:
    return json.dumps({
        "original_structure": json.loads(original_json),  # 原始JSON结构
        "current_patterns": current_patterns,            # 当前使用的正则表达式
        "unmatched_titles": unmatched_titles            # 未匹配的标题列表
    }, ensure_ascii=False, indent=2)

async def process_file(client, file_path: Path, output_dir: Path, cache_dir: Path):
    try:
        print(f"Processing file: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            original_data = json.load(f)
        
        model_input_data = prepare_data_for_model(original_data)
        model_input_json = json.dumps(model_input_data, ensure_ascii=False, indent=2)
        
        #MODIFIED: 保持原有的第一次系统提示词
        system_prompt = """请分析这份目录文件中各级标题的结构特征，并给出该目录特定的正则表达式模式。注意：只需识别当前目录的结构特征，不要试图覆盖其他可能的目录形式。

请分析输入的目录结构，识别该目录特有的层级特征，给出准确的正则表达式模式。注意：
1. 只关注输入目录的具体结构特征
2. 正则表达式要准确匹配当前目录的各级标题格式
3. 不要试图兼容其他可能的目录形式
4. 本章总结、思考题等不应单独形成一个层级，它们应该和节同一级别，这点还请万分注意

============示例目录============
- 第一篇 基础理论
  - 第一章 概述
    - 1.1 基本概念
    - 1.2 发展历程
    - 本章总结
    - 思考题
  - 第二章 核心理论
    - 2.1 基本原理
    - 2.2 应用方法
    - 本章总结
    - 思考题
- 第二篇 实践应用
  - 第三章 应用实例
    - 3.1 案例分析
    - *3.2 效果评估
    - 本章总结
    - 思考题
- 参考文献
- 附录A 补充材料
  - A.1 详细推导
  - A.2 数据表格

============分析逻辑============

1. 这篇目录有正文部分和非正文部分。
2. 正文部分用的是`篇-章-节`结构，非正文部分包括参考文献和附录，附录用的是两级结构。
3. 对于正文部分，篇是第一级，章是第二级，节是第三级。由于每章包含一个`本章总结`和`思考题`，所以它们应该是`章`的下一级。
4. 对于非正文部分，参考文献一定是第一级，附录的最高级一定是第一级。

============正确输出示例============
```json
{
    "1": ["^第[一二三四五六七八九十百千万]+篇\\s.*", "^参考文献$", "^附录[A-Z]\\s.*"],
    "2": ["^第[一二三四五六七八九十百千万]+章\\s.*", "^[A-Z]\\.[0-9]+\\s.*"],
    "3": ["^[0-9]+\\.[0-9]+\\s.*", "^本章总结$", "^思考题$"]
}
```
============错误原因警示============
```json
{
    "1": ["^第[一二三四五六七八九十]+篇\\s.*", "^参考文献$", "^附录[A-Z]\\s.*"],  // 错误：如果遇到中文数字，即便原文不长，也要匹配全部。这里少了`百千万`。
    "2": ["^第[一二三四五六七八九十百千万]+章\\s.*", "^[A-Z]\\.[0-9]\\s.*"],  // 错误：如果遇到阿拉伯数字，即使原文不长，也要匹配全部。这里的`[0-9]`应改为`[0-9]+`。
    "3": ["^[0-9]+\\.[0-9]+\s.*"],  // 错误：转义字符缺失。此处的`\s`应改为`\\s`。
    "4": ["^本章总结$", "^思考题$"]  // 错误：本章总结、思考题等不应单独形成一个层级，它们应该和节同一级别
}
```
只输出JSON格式的结果，不要包含其他说明。"""

        #MODIFIED: 第二次迭代的系统提示词预留位置
        iteration_system_prompt = """
请分析这份目录文件中各级标题的结构特征，然后分析当前的正则表达式为何会导致匹配遗漏，给出修正后的正则表达式。
只输出JSON格式的结果，不要包含其他说明。
本章总结、思考题等不应单独形成一个层级，它们应该和节同一级别，这点还请万分注意。

============示例目录============
- 第一篇 基础理论
  - 第一章 概述
    - 1.1 基本概念
    - 1.2 发展历程
    - 本章总结
    - 思考题
  - 第二章 核心理论
    - 2.1 基本原理
    - 2.2 应用方法
    - 本章总结
    - 思考题
- 第二篇 实践应用
  - 第三章 应用实例
    - 3.1 案例分析
    - *3.2 效果评估
    - 本章总结
    - 思考题
- 参考文献
- 附录A 补充材料
  - A.1 详细推导
  - A.2 数据表格

============正确输出示例============

```json
{
    "1": ["^第[一二三四五六七八九十百千万]+篇\\s.*", "^参考文献$", "^附录[A-Z]\\s.*"],
    "2": ["^第[一二三四五六七八九十百千万]+章\\s.*", "^[A-Z]\\.[0-9]+\\s.*"],
    "3": ["^[0-9]+\\.[0-9]+\\s.*", "^本章总结$", "^思考题$"]
}
```

============错误原因警示============
```json
{
    "1": ["^第[一二三四五六七八九十]+篇\\s.*", "^参考文献$", "^附录[A-Z]\\s.*"],  // 错误：如果遇到中文数字，即便原文不长，也要匹配全部。这里少了`百千万`。
    "2": ["^第[一二三四五六七八九十百千万]+章\\s.*", "^[A-Z]\\.[0-9]\\s.*"],  // 错误：如果遇到阿拉伯数字，即使原文不长，也要匹配全部。这里的`[0-9]`应改为`[0-9]+`。
    "3": ["^[0-9]+\\.[0-9]+\\s.*"],  // 错误：本章总结、思考题等不应单独形成一个层级，它们应该和节同一级别
    "4": ["^本章总结$", "^思考题$"]  // 错误：本章总结、思考题等不应单独形成一个层级，它们应该和节同一级别
}
```

"""

        print("Starting first iteration...")
        
        current_patterns = None
        best_patterns = None
        unmatched_titles = []
        
        for iteration in range(1, 5):
            print(f"\nIteration {iteration}:")
            
            if iteration == 1:
                stream = await client.chat.completions.create(
                    model="deepseek-v3",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": model_input_json}
                    ],
                    response_format={"type": "json_object"},
                    stream=True
                )
            else:
                iteration_input = prepare_iteration_input(
                    model_input_json,
                    current_patterns,
                    unmatched_titles
                )
                stream = await client.chat.completions.create(
                    model="qwen-max",
                    messages=[
                        {"role": "system", "content": iteration_system_prompt},
                        {"role": "user", "content": iteration_input}
                    ],
                    response_format={"type": "json_object"},
                    stream=True
                )

            print("Receiving response...")
            accumulated_response = ""
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    accumulated_response += content
                    print(content, end='', flush=True)

            # 清理并保存响应
            cleaned_response = clean_model_response(accumulated_response)
            cache_file = save_response(
                cleaned_response,
                file_path.stem,
                iteration,
                cache_dir
            )
            print(f"\nResponse saved to: {cache_file}")

            try:
                current_patterns = validate_patterns(cleaned_response)
                if not current_patterns:
                    raise ValueError("No valid patterns found in model response")
                
                pattern_matcher = PatternMatcher(current_patterns)
                
                # 应用模式进行匹配
                processed_items, new_unmatched = apply_patterns_to_items(
                    original_data['items'].copy(),  # 使用副本避免修改原数据
                    pattern_matcher
                )
                
                # 保存第二次迭代的结果作为最佳结果
                if iteration == 3:
                    best_patterns = current_patterns
                
                # 检查是否还有未匹配的标题
                if not new_unmatched:
                    print("All titles matched successfully!")
                    best_patterns = current_patterns  # 更新最佳结果
                    break
                
                unmatched_titles = new_unmatched
                print(f"\nUnmatched titles count: {len(unmatched_titles)}")
                
                if iteration >= 4:  # 第四次迭代后使用第二次的结果
                    print("\nMaximum iterations reached. Using results from second iteration.")
                    current_patterns = best_patterns
                    break
                
            except Exception as e:
                print(f"\nError processing patterns: {str(e)}")
                if iteration == 1:
                    raise  # 第一次迭代失败时直接退出
                break  # 后续迭代失败时使用之前的结果
        
        # 使用最终的模式处理数据
        final_pattern_matcher = PatternMatcher(best_patterns or current_patterns)
        original_data['items'], _ = apply_patterns_to_items(
            original_data['items'],
            final_pattern_matcher
        )
        
        # 保存结果
        output_file = output_dir / file_path.name
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(original_data, f, ensure_ascii=False, indent=2)
        print(f"\nProcessing complete. Final output saved to: {output_file}")
            
    except Exception as e:
        print(f"\nError processing {file_path.name}:")
        print(f"Type: {type(e).__name__}")
        print(f"Message: {str(e)}")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()

async def main():
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

if __name__ == "__main__":
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())