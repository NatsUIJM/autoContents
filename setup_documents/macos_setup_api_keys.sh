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

validate_and_set() {
  local var=$1
  local value=$2
  local valid=true
  local warning=""

  case $var in
    DASHSCOPE_API_KEY|DEEPSEEK_API_KEY)
      if [[ ! $value =~ ^sk- ]]; then
        valid=false
        warning="警告: ${var}应以'sk-'开头"
      fi
      ;;
    ALIBABA_CLOUD_ACCESS_KEY_ID)
      if [[ ${#value} != 24 ]]; then
        valid=false
        warning="警告: ${var}应为24个字符"
      fi
      ;;
    ALIBABA_CLOUD_ACCESS_KEY_SECRET)
      if [[ ${#value} != 30 ]]; then
        valid=false
        warning="警告: ${var}应为30个字符"
      fi
      ;;
    AZURE_DOCUMENT_INTELLIGENCE_KEY)
      if [[ ${#value} != 84 ]]; then
        valid=false
        warning="警告: ${var}应为84个字符"
      fi
      ;;
  esac

  if [[ $valid == false ]]; then
    echo $warning
    echo "是否仍要继续设置该值？(y/n/r)"
    echo "y: 继续设置"
    echo "n: 跳过此变量"
    echo "r: 重新输入"
    read choice
    case $choice in
      y)
        echo "export ${var}=\"${value}\"" >> ~/.zshrc
        echo "${var} 已设置为 ${value}"
        ;;
      n)
        echo "已跳过 ${var}"
        ;;
      r)
        return 1
        ;;
      *)
        echo "无效输入，已跳过 ${var}"
        ;;
    esac
  else
    echo "export ${var}=\"${value}\"" >> ~/.zshrc
    echo "${var} 已设置为 ${value}"
  fi
  return 0
}

for var in "${vars[@]}"; do
  while true; do
    echo -n "请输入${var}的值: "
    read value
    
    if [[ "$value" == "0" ]]; then
      echo "已跳过 ${var}"
      echo
      break
    fi
    
    validate_and_set "$var" "$value"
    if [[ $? == 0 ]]; then
      echo
      break
    fi
  done
done

echo "所有环境变量设置完成。请运行 source ~/.zshrc 或重启终端以使更改生效。"