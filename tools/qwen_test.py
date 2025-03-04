"""
文件名: test_llm_api.py
功能: 测试qwen-max模型API调用
"""
import os
import json
import asyncio
import datetime
import platform
from openai import AsyncOpenAI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

async def test_qwen_max():
    # 获取API密钥
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        save_error("环境变量DASHSCOPE_API_KEY未设置")
        return
    
    # 设置API请求信息，与llm_handler.py保持一致
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    # 创建AsyncOpenAI客户端，与llm_handler.py相同的方法
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url
    )
    
    try:
        # 创建简单测试消息
        messages = [
            {"role": "system", "content": "你是一个有帮助的AI助手。"},
            {"role": "user", "content": "请简要介绍一下自己，不超过100字"}
        ]
        
        # 调用API，与llm_handler.py中的调用方式类似
        response = await client.chat.completions.create(
            model="qwen-max",
            messages=messages,
            temperature=0.7,
            stream=False
        )
        
        # 保存成功响应
        response_data = response.model_dump()
        save_response(response_data)
        print("测试成功，已保存响应结果")
        return True
        
    except Exception as e:
        error_message = f"发生异常: {str(e)}"
        save_error(error_message)
        print(error_message)
        return False

def save_response(response_data):
    """保存成功的响应结果"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"./tools/response_{timestamp}.txt"
    
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(response_data, file, ensure_ascii=False, indent=2)
    
    print(f"响应已保存至: {filename}")

def save_error(error_message):
    """保存错误信息"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"./tools/error_{timestamp}.txt"
    
    with open(filename, "w", encoding="utf-8") as file:
        file.write(error_message)
    
    print(f"错误已保存至: {filename}")

async def main():
    print("开始测试qwen-max模型...")
    success = await test_qwen_max()
    
    # 根据测试结果设置退出码
    return 0 if success else 1

if __name__ == "__main__":
    # 为Windows设置事件循环策略，与llm_handler.py相同
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # 运行主协程并获取退出码
    exit_code = asyncio.run(main())
    print(f"测试完成，退出码: {exit_code}")