@echo off
chcp 65001
setlocal EnableDelayedExpansion

echo 请依次输入环境变量值（输入0可跳过）：
echo.

set VARS[0]=DASHSCOPE_API_KEY
set VARS[1]=ALIBABA_CLOUD_ACCESS_KEY_ID
set VARS[2]=ALIBABA_CLOUD_ACCESS_KEY_SECRET
set VARS[3]=AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
set VARS[4]=AZURE_DOCUMENT_INTELLIGENCE_KEY
set VARS[5]=DEEPSEEK_API_KEY

:validate_and_set
set "var=%~1"
set "value=%~2"
set "valid=true"
set "warning="

if "%var%"=="%VARS[0]%" (
    echo %value% | findstr /r "^sk-" >nul
    if errorlevel 1 (
        set "valid=false"
        set "warning=警告: %var%应以'sk-'开头"
    )
)
if "%var%"=="%VARS[5]%" (
    echo %value% | findstr /r "^sk-" >nul
    if errorlevel 1 (
        set "valid=false"
        set "warning=警告: %var%应以'sk-'开头"
    )
)
if "%var%"=="%VARS[1]%" (
    if not "!value:~24!"=="" (
        set "valid=false"
        set "warning=警告: %var%应为24个字符"
    )
    if "!value:~23,1!"=="" (
        set "valid=false"
        set "warning=警告: %var%应为24个字符"
    )
)
if "%var%"=="%VARS[2]%" (
    if not "!value:~30!"=="" (
        set "valid=false"
        set "warning=警告: %var%应为30个字符"
    )
    if "!value:~29,1!"=="" (
        set "valid=false"
        set "warning=警告: %var%应为30个字符"
    )
)
if "%var%"=="%VARS[4]%" (
    if not "!value:~84!"=="" (
        set "valid=false"
        set "warning=警告: %var%应为84个字符"
    )
    if "!value:~83,1!"=="" (
        set "valid=false"
        set "warning=警告: %var%应为84个字符"
    )
)

if "%valid%"=="false" (
    echo !warning!
    echo 是否仍要继续设置该值？(y/n/r^)
    echo y: 继续设置
    echo n: 跳过此变量
    echo r: 重新输入
    set /p choice=
    if "!choice!"=="y" (
        setx %var% "%value%"
        echo %var% 已设置为 %value%
    ) else if "!choice!"=="n" (
        echo 已跳过 %var%
    ) else if "!choice!"=="r" (
        exit /b 1
    ) else (
        echo 无效输入，已跳过 %var%
    )
) else (
    setx %var% "%value%"
    echo %var% 已设置为 %value%
)
exit /b 0

for /L %%i in (0,1,5) do (
    :input_loop
    set /p VALUE=请输入!VARS[%%i]!的值: 
    if "!VALUE!"=="0" (
        echo 已跳过 !VARS[%%i]!
        echo.
    ) else (
        call :validate_and_set "!VARS[%%i]!" "!VALUE!"
        if errorlevel 1 (
            goto input_loop
        )
        echo.
    )
)

echo 所有环境变量设置完成。请重启命令行或应用程序以使更改生效。
pause