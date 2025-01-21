import os
import json
import asyncio
from openai import AsyncOpenAI
import platform
from pathlib import Path

# 创建异步客户端实例
client = AsyncOpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 提示模板
SYSTEM_PROMPT = """Task: 处理JSON格式的目录数据，修正文本错误并规范化格式。

Request:
1. 文本处理要求：
   - 修正text字段中的OCR识别错误（通常每条数据最多1-2个形近字错误）
   - 在章节序号和标题之间添加一个空格分隔
    
2. 页码处理规则：
对于number字段为null的情况，需处理以下三种场景：
   a. OCR未识别页码（常见于目录开头的个位数页码）：
      - 根据前后文估算合理页码
      - 输出时标记"confirmed": false
   
   b. 标题换行导致分散（常见于较长标题）：
      - 将本行与相邻行合并为完整标题
      - 使用已有的页码
      - 输出时标记"confirmed": true
   
   c. 原书未标注页码（常见于一二级标题）：
      - 使用该部分第一个有页码的子标题页码
      - 输出时标记"confirmed": true

3. 标题合并规则：
   - 遇到含章节号且结尾不完整的条目时，与下一个无章节号的条目合并
   - 合并后使用下一条目的页码
   - 输出的结果中不应包含任何"null"字段，如无法确定页码请标记"confirmed": false

请按照上述规则处理以下内容，并以JSON格式输出。"""

class TokenCounter:
    def __init__(self):
        self.completion_tokens = 0
        self.prompt_tokens = 0
    
    def update(self, completion_tokens, prompt_tokens):
        self.completion_tokens += completion_tokens
        self.prompt_tokens += prompt_tokens

async def process_file(input_file: Path, output_file: Path, token_counter: TokenCounter):
    # 读取输入JSON
    with open(input_file, 'r', encoding='utf-8') as f:
        input_data = json.load(f)
    
    # 创建模型提示
    prompt = f"{SYSTEM_PROMPT}\n\n{json.dumps(input_data, ensure_ascii=False, indent=2)}"
    
    # 使用流式调用模型
    response = await client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        stream=True
    )
    
    full_response = ""
    async for chunk in response:
        if chunk.choices[0].delta.content is not None:
            full_response += chunk.choices[0].delta.content
        # 如果有使用信息，更新令牌计数器
        if hasattr(chunk, 'usage') and chunk.usage:
            token_counter.update(
                chunk.usage.completion_tokens,
                chunk.usage.prompt_tokens
            )
    
    # 解析并保存响应
    try:
        processed_data = json.loads(full_response)
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=2)
        print(f"Processed {input_file.name}")
    except json.JSONDecodeError as e:
        print(f"Error processing {input_file.name}: {e}")

async def main():
    input_dir = Path("4_initialContentInfo")
    output_dir = Path("5_processedContentInfo")
    
    # 如果输出目录不存在，创建它
    os.makedirs(output_dir, exist_ok=True)
    
    # 获取所有JSON文件
    json_files = list(input_dir.glob("*.json"))
    
    # 为每个文件创建令牌计数器
    token_counters = {file: TokenCounter() for file in json_files}
    
    # 为每个文件创建任务
    tasks = [
        process_file(
            input_file,
            output_dir / input_file.name,
            token_counters[input_file]
        )
        for input_file in json_files
    ]
    
    # 运行所有任务
    await asyncio.gather(*tasks)

if __name__ == '__main__':
    # 为Windows设置事件循环策略
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # 运行主协程
    asyncio.run(main())