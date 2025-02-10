#!/bin/zsh

echo "请依次输入环境变量值（输入0可跳过）："
echo

vars=(
  "DASHSCOPE_API_KEY"
  "ALIBABA_CLOUD_ACCESS_KEY_ID" 
  "ALIBABA_CLOUD_ACCESS_KEY_SECRET"
  "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"
  "AZURE_DOCUMENT_INTELLIGENCE_KEY"
  "DEEPSEEK_API_KEY"
)

for var in "${vars[@]}"; do
  echo -n "请输入${var}的值: "
  read value
  
  if [[ "$value" != "0" ]]; then
    echo "export ${var}=\"${value}\"" >> ~/.zshrc
    echo "${var} 已设置为 ${value}"
  else
    echo "已跳过 ${var}"
  fi
  echo
done

echo "所有环境变量设置完成。请运行 source ~/.zshrc 或重启终端以使更改生效。"