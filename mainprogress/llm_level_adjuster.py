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

#MODIFIED: 修改返回值类型，增加未匹配标题列表
def apply_patterns_to_items(items: List[dict], pattern_matcher: PatternMatcher) -> Tuple[List[dict], List[str]]:
    """使用模式匹配器为每个项目设置层级，返回处理后的项目和未匹配标题列表"""
    unmatched_titles = []
    # 用一个集合来跟踪本次匹配中已经被匹配的标题
    matched_texts = set()
    
    # 第一遍：尝试匹配所有标题
    for item in items:
        if item['text'] not in matched_texts:  # 只处理未匹配的标题
            level = pattern_matcher.match_level(item['text'])
            if level > 0:
                item['level'] = level
                matched_texts.add(item['text'])
            else:
                unmatched_titles.append(item['text'])
    
    # 对于未匹配的标题，保持原有的level值（通常是1）
    
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

错误输出示例3：
{
    "1": ["^第[一二三四五六七八九十百千万]+章.*", "^参考文献$", "^附录[A-Z].*", "习题$", "小结$", "思考题$"],  // 错误：习题、小结、思考题等应与节（即章的下一级）处于同一层级，而不能与篇、章处于同一层级，也不能属于第一层级
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
5. 小结、习题等一般是章的下一级，具体要看它与什么级别的标题出现频率相近，但绝对不可能是第一级

只输出JSON格式的结果，不要包含其他说明。"""

        #MODIFIED: 第二次迭代的系统提示词预留位置
        iteration_system_prompt = """
请分析这份目录文件中各级标题的结构特征，然后分析当前的正则表达式为何会导致匹配遗漏，给出修正后的正则表达式。
只输出JSON格式的结果，不要包含其他说明。

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
```json
{
    "1": ["^第[一二三四五六七八九十百千万]+篇.*", "^参考文献$", "^附录[A-Z].*"],
    "2": ["^第[一二三四五六七八九十百千万]+章.*", "^[A-Z]\\.[0-9]+.*"],
    "3": ["^[一二三四五六七八九十百千万]+、.*"]
}
```
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
```json
{
    "1": ["^第[一二三四五六七八九十百千万]+章.*", "^附录$"],
    "2": ["^\\**[0-9]+\\.[0-9]+.*", "^(本章总结|思考题)$", "^附录[A-Z].*"]
}
```

错误示例：
```json
{ // 多了一层花括号
  "revised_patterns": { // 不要有"revised_patterns"
    "1": [
      "^第[0-9]+篇.*",
      "^参考文献$"
    ],
    "2": [
      "^第[0-9]+章.*"
    ],
    "3": [
      "^[0-9]+\\.[0-9]+.*",
      "^(习题)$",
      "^\\*[0-9]+\\.[0-9]+.*"
    ]
  }
}
```
错误原因：未按照“对应的模式输出：”中的结构进行输出
"""

        print("Starting first iteration...")
        
        # First iteration
        current_patterns = None
        best_patterns = None
        unmatched_titles = []
        
        for iteration in range(1, 5):  # 最多4次尝试
            print(f"\nIteration {iteration}:")
            
            if iteration == 1:
                # First iteration uses original input and prompt
                stream = await client.chat.completions.create(
                    model="qwen-max-latest",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": model_input_json}
                    ],
                    response_format={"type": "json_object"},
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

            # 保存响应
            cache_file = save_response(
                accumulated_response,
                file_path.stem,
                iteration,
                cache_dir
            )
            print(f"\nResponse saved to: {cache_file}")

            try:
                current_patterns = validate_patterns(accumulated_response)
                if not current_patterns:
                    raise ValueError("No valid patterns found in model response")
                
                pattern_matcher = PatternMatcher(current_patterns)
                
                # 应用模式进行匹配
                processed_items, new_unmatched = apply_patterns_to_items(
                    original_data['items'].copy(),  # 使用副本避免修改原数据
                    pattern_matcher
                )
                
                # 保存第二次迭代的结果作为最佳结果
                if iteration == 2:
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