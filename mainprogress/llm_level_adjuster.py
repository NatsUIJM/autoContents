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
        return 0  # 返回0表示未匹配任何模式

def validate_patterns(patterns_json: str) -> Dict[int, List[str]]:
    """验证并解析模型返回的模式"""
    try:
        patterns = json.loads(patterns_json)
        if not isinstance(patterns, dict):
            raise ValueError("Patterns must be a dictionary")
        
        # 验证每个级别的模式是否是有效的正则表达式
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
                    re.compile(pattern)
                    valid_patterns.append(pattern)
                except re.error:
                    print(f"Invalid regex pattern for level {level}: {pattern}")
                    continue
                    
            if not valid_patterns:
                raise ValueError(f"No valid patterns for level {level}")
                
            validated_patterns[level_num] = valid_patterns
        
        if not validated_patterns:
            raise ValueError("No valid patterns found")
            
        # 确保至少有第一级和第二级的模式
        if 1 not in validated_patterns or 2 not in validated_patterns:
            raise ValueError("Must have patterns for both level 1 and 2")
            
        return validated_patterns
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON format for patterns")

def apply_patterns_to_items(items: List[dict], pattern_matcher: PatternMatcher) -> List[dict]:
    """使用模式匹配器为每个项目设置层级"""
    for item in items:
        level = pattern_matcher.match_level(item['text'])
        if level > 0:
            item['level'] = level
    return items

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

def save_response(content: str, input_filename: str, attempt: int, cache_dir: Path) -> Path:
    """保存响应到缓存目录"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"response_{input_filename}_attempt_{attempt}_{timestamp}.json"
    filepath = cache_dir / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return filepath

async def process_file(client, file_path: Path, output_dir: Path, cache_dir: Path):
    try:
        print(f"Processing file: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            original_data = json.load(f)
        
        model_input_data = prepare_data_for_model(original_data)
        model_input_json = json.dumps(model_input_data, ensure_ascii=False, indent=2)
        
        system_prompt = """请分析这份目录文件中各级标题的结构特征，并给出该目录特定的正则表达式模式。注意：只需识别当前目录的结构特征，不要试图覆盖其他可能的目录形式。

示例目录1：
- 第一篇 基础理论
  - 第一章 概述
    - 一、基本概念
    - 二、发展历程
  - 第二章 核心理论
    - 三、基本原理
    - 四、应用方法
- 第二篇 实践应用
  - 第三章 应用实例
    - 五、案例分析
    - 六、效果评估
- 参考文献
- 附录A 补充材料
  - A.1 详细推导
  - A.2 数据表格

对应的模式输出：
{
    "1": ["^第[一二三四五六七八九十百千万]+篇.*", "^参考文献$", "^附录[A-Z].*"],
    "2": ["^第[一二三四五六七八九十百千万]+章.*", "^[A-Z]\\.[0-9]+.*"],
    "3": ["^[一二三四五六七八九十百千万]+、.*"]
}

错误输出示例1：
{
    "1": ["^第[一二三四五六七八九十]{1,3}篇.*", "^参考文献$", "^附录[A-Z].*"],  // 错误：匹配过于局限
    "2": ["^第[一二三四五六七八九十]{1,3}章.*", "^[A-Z]\\.[0-9]+.*"],  // 错误：匹配过于局限
    "3": ["^[一二三四五六七八九十]{1,3}、.*"]  // 错误：匹配过于局限
}

错误输出示例2：
{
    "1": ["^第[一二三四五六七八九十百千万]+(?:篇|章).*", "^参考文献$", "^附录[A-Z].*"],  // 错误：篇和章应该分属不同层级
    "2": ["^[A-Z]\\.[0-9]+.*"],
    "3": ["^[一二三四五六七八九十百千万]+、.*"]
}

  示例目录2：
- 第一章 引言
  - 1.1 研究背景
  - *1.2 研究意义
- 第二章 文献综述
  - 2.1 国内研究现状
  - *2.2 国外研究进展
  - 本章总结
  - 思考题
- 附录
  - 附录A 数据集
  - 附录B 算法详解

对应的模式输出：
{
    "1": ["^第[一二三四五六七八九十百千万]+章.*", "^附录$"],
    "2": ["^\\**[0-9]+\\.[0-9]+.*", "^(本章总结|思考题)$", "^附录[A-Z].*"]
}

错误输出示例：
{
    "1": ["^第[一二三四五六七八九十百千万]+章.*", "^附录$"],
    "2": ["^[0-9]+\\.[0-9]+.*", "^(本章总结|思考题)$", "^附录[A-Z].*"] // 错误：未考虑章节标题前的星号
}

请分析输入的目录结构，识别该目录特有的层级特征，给出准确的正则表达式模式。注意：
1. 只关注输入目录的具体结构特征
2. 正则表达式要准确匹配当前目录的各级标题格式
3. 不要试图兼容其他可能的目录形式
4. 篇/部分标题、章/节标题、条/款标题等属于不同层级，切记不要将不同级别的标题视为同一级别

只输出JSON格式的结果，不要包含其他说明。"""
        print("Sending request to API...")
        
        stream = await client.chat.completions.create(
            model="qwen-max",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": model_input_json}
            ],
            response_format={"type": "json_object"},
            stream=True
        )

        print("\nReceiving and processing response:")
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
            1,
            cache_dir
        )
        print(f"\nResponse saved to: {cache_file}")

        try:
            patterns = validate_patterns(accumulated_response)
            if not patterns:
                raise ValueError("No valid patterns found in model response")
            
            pattern_matcher = PatternMatcher(patterns)
            
            # 应用模式进行匹配
            original_data['items'] = apply_patterns_to_items(
                original_data['items'],
                pattern_matcher
            )
            
            # 保存结果
            output_file = output_dir / file_path.name
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(original_data, f, ensure_ascii=False, indent=2)
            print(f"\nProcessing complete. Final output saved to: {output_file}")
            
        except Exception as e:
            print(f"\nError processing patterns: {str(e)}")
            
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