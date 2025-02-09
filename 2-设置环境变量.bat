@echo off
chcp 65001
title autoContents环境变量设置
setlocal EnableDelayedExpansion

echo 请依次输入环境变量值（输入0可跳过）：
echo.

set VARS[0]=DASHSCOPE_API_KEY
set VARS[1]=ALIBABA_CLOUD_ACCESS_KEY_ID
set VARS[2]=ALIBABA_CLOUD_ACCESS_KEY_SECRET
set VARS[3]=AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
set VARS[4]=AZURE_DOCUMENT_INTELLIGENCE_KEY
set VARS[5]=DEEPSEEK_API_KEY

for /L %%i in (0,1,5) do (
    set /p VALUE=请输入!VARS[%%i]!的值: 
    if not "!VALUE!"=="0" (
        setx !VARS[%%i]! "!VALUE!"
        echo !VARS[%%i]! 已设置为 !VALUE!
    ) else (
        echo 已跳过 !VARS[%%i]!
    )
    echo.
)

echo 所有环境变量设置完成。请重启命令行或应用程序以使更改生效。
pause