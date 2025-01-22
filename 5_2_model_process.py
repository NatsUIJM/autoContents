import os
import json
import asyncio
import time
from openai import AsyncOpenAI
import platform
from pathlib import Path
from typing import Dict, NamedTuple

class ServiceConfig(NamedTuple):
    name: str
    api_key_env: str
    base_url: str
    model_name: str

SERVICES = {
    'dashscope': ServiceConfig(
        name='DashScope',
        api_key_env='DASHSCOPE_API_KEY',
        base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
        model_name='qwen-max'
    ),
    'deepseek': ServiceConfig(
        name='DeepSeek',
        api_key_env='DEEPSEEK_API_KEY',
        base_url='https://api.deepseek.com/v1',
        model_name='deepseek-chat'
    ),
    # Add more services as needed
}

class ServiceManager:
    def __init__(self, service_name: str):
        if service_name not in SERVICES:
            raise ValueError(f"Unsupported service: {service_name}")
        
        self.config = SERVICES[service_name]
        self.client = AsyncOpenAI(
            api_key=os.getenv(self.config.api_key_env),
            base_url=self.config.base_url
        )

class ProgressTracker:
    def __init__(self):
        self.total_input_chars = 0
        self.total_output_chars = 0
        self.last_progress_time = 0
        self.start_time = time.time()
        self.processed_chars = 0
    
    def add_input_chars(self, count: int):
        self.total_input_chars += count
    
    def add_output_chars(self, count: int):
        self.total_output_chars += count
        self.processed_chars += count
    
    def get_progress(self) -> float:
        if self.total_output_chars == 0:
            return 0.0
        return self.total_output_chars / (self.total_input_chars / 0.65) * 100

    def get_time_estimate(self) -> str:
        if self.processed_chars == 0:
            return "calculating..."
        
        elapsed_time = time.time() - self.start_time
        chars_per_second = self.processed_chars / elapsed_time
        remaining_chars = (self.total_input_chars / 0.65) - self.total_output_chars
        
        if chars_per_second > 0:
            remaining_seconds = remaining_chars / chars_per_second
            remaining_minutes = int(remaining_seconds / 60)
            remaining_seconds = int(remaining_seconds % 60)
            return f"{remaining_minutes}m {remaining_seconds}s"
        return "calculating..."

    def should_update(self) -> bool:
        current_time = time.time()
        if current_time - self.last_progress_time >= 1:
            self.last_progress_time = current_time
            return True
        return False

# Create global progress tracker
progress_tracker = ProgressTracker()

class TokenCounter:
    def __init__(self):
        self.completion_tokens = 0
        self.prompt_tokens = 0
    
    def update(self, completion_tokens, prompt_tokens):
        self.completion_tokens += completion_tokens
        self.prompt_tokens += prompt_tokens

def get_system_prompt() -> str:
    """Generate system prompt"""
    return """{
  "promptName": "JSON Table of Contents Processor",
  "version": "1.0",
  "description": "Process and normalize table of contents data in JSON format",
  "rules": {
    "textProcessing": {
      "operations": [
        "Fix OCR errors (typically 1-2 similar character mistakes per entry)",
        "Add space between chapter numbers and titles",
        "Remove redundant spaces and abnormal symbols"
      ]
    },
    "pageNumberProcessing": {
      "scenarios": {
        "unrecognizedOCR": {
          "condition": "Single-digit page numbers at beginning",
          "action": "Keep number as null",
          "confirmed": false
        },
        "lineBreakTitle": {
          "condition": "Long titles split across lines",
          "action": "Merge with adjacent lines",
          "useExistingNumber": true,
          "confirmed": true
        },
        "unmarkedPages": {
          "condition": "Level 1-2 titles without page numbers",
          "action": "Use first child page number",
          "confirmed": true
        }
      }
    },
    "titleMerging": {
      "condition": "Incomplete entry with chapter number",
      "actions": [
        "Merge with next unnumbered entry",
        "Use page number from next entry"
      ],
      "confirmed": true
    },
    "hierarchyRules": {
      "twoLevels": {
        "condition": "Chapter is highest level",
        "mapping": {
          "chapter": 1,
          "section": 2
        }
      },
      "threeLevels": {
        "condition": "Title above chapter exists",
        "mapping": {
          "topLevel": 1,
          "chapter": 2,
          "section": 3
        }
      }
    },
    "outputFormat": {
      "type": "JSON",
      "structure": {
        "items": {
          "type": "array",
          "elements": {
            "text": "string",
            "number": "integer|null",
            "confirmed": "boolean",
            "level": "integer(1-3)"
          }
        }
      }
    }
  }
}"""

system = """
You are a helpful assistant for a data processing task. You need to process JSON-formatted directory data, correct text errors, and standardize the format.
"""

async def process_single_file(file_path: Path, output_dir: Path, service_manager: ServiceManager, token_counter: TokenCounter, retry_count: int = 1):
    """Process a single file"""
    try:
        # Read file data
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Create model prompt
        prompt = f"{get_system_prompt()}\n\n{json.dumps(data, ensure_ascii=False, indent=2)}"
        
        # Update input character count
        progress_tracker.add_input_chars(len(prompt))
        
        # Retry specified number of times
        for attempt in range(retry_count + 1):
            try:
                # Use streaming call to model
                response = await service_manager.client.chat.completions.create(
                    model=service_manager.config.model_name,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    stream=True
                )
                
                full_response = ""
                async for chunk in response:
                    if chunk.choices[0].delta.content is not None:
                        content = chunk.choices[0].delta.content
                        full_response += content
                        progress_tracker.add_output_chars(len(content))
                        
                        # Check if progress should be updated
                        if progress_tracker.should_update():
                            print(f"Progress: {progress_tracker.get_progress():.2f}% | Estimated time remaining: {progress_tracker.get_time_estimate()}")
                            
                    if hasattr(chunk, 'usage') and chunk.usage:
                        token_counter.update(
                            chunk.usage.completion_tokens,
                            chunk.usage.prompt_tokens
                        )
                
                # Validate JSON format
                processed_data = json.loads(full_response)
                
                # Save processed data
                output_file = output_dir / f"{file_path.stem}_processed.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(processed_data, f, ensure_ascii=False, indent=2)
                
                print(f"Processed {file_path.name}")
                return True
                
            except Exception as e:
                if attempt < retry_count:
                    print(f"Retry {attempt + 1} for {file_path.name} due to: {str(e)}")
                    continue
                else:
                    # Generate error message JSON
                    error_data = {
                        "items": [{
                            "text": f"错误码{str(e)}",
                            "number": 1,
                            "confirmed": True,
                            "level": 1
                        }]
                    }
                    output_file = output_dir / f"{file_path.stem}_processed.json"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(error_data, f, ensure_ascii=False, indent=2)
                    print(f"Failed to process {file_path.name} after {retry_count} retries")
                    return False
                
    except Exception as e:
        print(f"Error processing {file_path.name}: {str(e)}")
        return False

async def main():
    # Get service selection from environment variable or use default
    service_name = os.getenv('LLM_SERVICE', 'deepseek').lower()
    service_manager = ServiceManager(service_name)
    
    input_dir = Path("4_initialContentInfo")
    output_dir = Path("4_1_LLMProcessed")
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Read file information
    with open(input_dir / "file_info.json", 'r', encoding='utf-8') as f:
        file_info = json.load(f)
    
    # Create task list
    tasks = []
    token_counters = {}
    
    for file_path_str in file_info.keys():
        file_path = Path(file_path_str)
        token_counters[file_path] = TokenCounter()
        tasks.append(process_single_file(file_path, output_dir, service_manager, token_counters[file_path]))
    
    # Run all tasks
    results = await asyncio.gather(*tasks)
    
    # Summarize processing results
    success_count = sum(1 for r in results if r)
    fail_count = len(results) - success_count
    print(f"\nProcessing complete. Success: {success_count}, Failed: {fail_count}")

if __name__ == '__main__':
    # Set event loop policy for Windows
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # Run main coroutine
    asyncio.run(main())