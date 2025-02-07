"""
文件名: content_validator_auto.py (原名: content_validator_auto.py)
功能: 验证和修正内容的level和number字段
"""
import json
import os
import sys
from typing import List, Dict, Any
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

import dotenv
dotenv.load_dotenv()

# 从环境变量获取路径配置
CONTENT_VALIDATOR_AUTO_INPUT = os.getenv('CONTENT_VALIDATOR_AUTO_INPUT')
CONTENT_VALIDATOR_AUTO_OUTPUT = os.getenv('CONTENT_VALIDATOR_AUTO_OUTPUT')

if not CONTENT_VALIDATOR_AUTO_INPUT or not CONTENT_VALIDATOR_AUTO_OUTPUT:
    raise ValueError("必须设置 CONTENT_VALIDATOR_AUTO_INPUT 和 CONTENT_VALIDATOR_AUTO_OUTPUT 环境变量")

def process_level(items: List[Dict[str, Any]]) -> None:
    """将level为0的条目改为1"""
    for item in items:
        if item["level"] == 0:
            item["level"] = 1

def process_null_numbers(items: List[Dict[str, Any]]) -> None:
    """处理number为null的情况，确保输出为整数"""
    for i in range(len(items)):
        if items[i]["number"] is None:
            # 获取level=1的下一个number
            if items[i]["level"] == 1:
                # 寻找下一个有效number
                next_number = None
                for j in range(i+1, len(items)):
                    if items[j]["number"] is not None:
                        next_number = items[j]["number"]
                        break
                
                # 如果找不到下一个number，使用上一个有效number
                if next_number is None:
                    for j in range(i-1, -1, -1):
                        if items[j]["number"] is not None:
                            items[i]["number"] = int(items[j]["number"]) + 1
                            break
                    # 如果还是没找到，设为1
                    if items[i]["number"] is None:
                        items[i]["number"] = 1
                else:
                    items[i]["number"] = int(next_number)
            
            # 非level=1的情况,取前后均值并取整
            else:
                prev_number = None
                next_number = None
                
                # 找前一个有效number
                for j in range(i-1, -1, -1):
                    if items[j]["number"] is not None:
                        prev_number = items[j]["number"]
                        break
                
                # 找后一个有效number        
                for j in range(i+1, len(items)):
                    if items[j]["number"] is not None:
                        next_number = items[j]["number"]
                        break
                
                # 根据找到的number情况处理
                if prev_number is not None and next_number is not None:
                    items[i]["number"] = int((prev_number + next_number) / 2)
                elif prev_number is not None:
                    items[i]["number"] = int(prev_number) + 1
                elif next_number is not None:
                    items[i]["number"] = int(next_number) - 1
                else:
                    items[i]["number"] = 1

def main():
    # 确保输出目录存在
    os.makedirs(CONTENT_VALIDATOR_AUTO_OUTPUT, exist_ok=True)
    
    # 处理每个json文件
    for filename in os.listdir(CONTENT_VALIDATOR_AUTO_INPUT):
        if filename.endswith('.json'):
            source_path = os.path.join(CONTENT_VALIDATOR_AUTO_INPUT, filename)
            target_path = os.path.join(CONTENT_VALIDATOR_AUTO_OUTPUT, filename)
            
            try:
                # 读取JSON
                with open(source_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 处理数据
                process_level(data["items"])
                process_null_numbers(data["items"])
                
                # 写入新文件
                with open(target_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    
            except Exception as e:
                print(f"处理文件 {filename} 时发生错误: {str(e)}")

if __name__ == "__main__":
    main()