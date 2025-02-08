# autoContents 使用教程

## 项目概述

autoContents 是一款专为扫描版 PDF 设计的书签自动生成工具，能够基于目录页内容创建可跳转书签。该工具支持单栏、双栏及混合排版的目录结构，适用于目录页数不超过 10 页且扫描质量合格（页面倾斜度 ≤2 度、文字清晰度满足 OCR 识别要求）的 PDF 文档。若目录包含“子节”即`x.x.x`级别的标题，目录页数限制可放宽至 20 页。

![目录结构及适用范围说明](./docs/目录结构及适用范围说明.svg)

项目需自行准备阿里云账户以使用基本功能，但面对情况较为复杂的文档时，可能需要使用 Azure 及 DeepSeek 以保证生成质量。若无程序开发经验，请参阅![如何配置基本开发环境](/docs/如何配置开发环境.md)；若不知道如何申请相应账户，请参阅![如何选择和申请云服务账户](./docs/如何选择和申请云服务账户.md)。

## Step 1 将源码下载至本地并打开

如果你知道`git clone`命令，那么这一步对你来说可能有些许幼稚，请将仓库克隆到本地后跳转至第二步。

1. 点击页面上的绿色按钮`Code`，然后点击`Download ZIP`，并解压下载的文件。
2. 打开 VSCode，在上方菜单选择`文件 -> 打开文件夹`，然后打开解压缩后的文件夹`autoContents-main`。

## Step 2 开发环境配置

### 2.1 配置环境变量

若无相应密钥，请参阅![如何选择和申请云服务账户](./docs/如何选择和申请云服务账户.md)。准备好密钥后，在 VSCode 的屏幕上方菜单中，选择`终端 -> 新建终端`。

1. 阿里云服务相关环境变量

   1. macOS 用户输入命令：
      ```zsh
      export DASHSCOPE_API_KEY='sk-4********8'
      export ALIBABA_CLOUD_ACCESS_KEY_ID='L********F'
      export ALIBABA_CLOUD_ACCESS_KEY_SECRET='f********j'
      ```

   2. Windows 用户输入命令：
      ```powershell
      [System.Environment]::SetEnvironmentVariable("DASHSCOPE_API_KEY", 'sk-4********8', [System.EnvironmentVariableTarget]::User)
      [System.Environment]::SetEnvironmentVariable("ALIBABA_CLOUD_ACCESS_KEY_ID", 'L********F', [System.EnvironmentVariableTarget]::User)
      [System.Environment]::SetEnvironmentVariable("ALIBABA_CLOUD_ACCESS_KEY_SECRET", 'f********j', [System.EnvironmentVariableTarget]::User)
      ```

2. Azure Document Intelligence 相关环境变量

   1. macOS 用户输入命令：
      ```zsh
      export AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT='https://***.cognitiveservices.azure.com/'
      export AZURE_DOCUMENT_INTELLIGENCE_KEY='7********C'
      ```

   2. Windows 用户输入命令：
      ```powershell
      [System.Environment]::SetEnvironmentVariable("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", 'https://***.cognitiveservices.azure.com/', [System.EnvironmentVariableTarget]::User)
      [System.Environment]::SetEnvironmentVariable("AZURE_DOCUMENT_INTELLIGENCE_KEY", '7********C', [System.EnvironmentVariableTarget]::User)
      ```

3. DeepSeek 相关环境变量

   1. macOS 用户输入命令：
      ```zsh
      export DEEPSEEK_API_KEY='sk-a********c'
      ```

   2. Windows 用户输入命令：
      ```powershell
      [System.Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", 'sk-a********c', [System.EnvironmentVariableTarget]::User)
      ```

### 2.2 安装 Poppler

1. 在 VSCode 的屏幕上方菜单中，选择`终端 -> 新建终端`。

2. macOS 用户输入命令：

   ```zsh
   brew install poppler
   ```

   Windows 用户输入命令：

   ```powershell
   choco install poppler
   ```
   
   如果报错，请查看基本开发环境是否正确配置。
   
3. 安装完成后，输入以下命令以验证安装：
   ```zsh
   pdfinfo --version
   ```

### 2.3 创建 venv 虚拟环境

1. 在 VSCode 中，在上方菜单选择`终端 -> 新建终端`，然后输入以下命令以修改 pip 镜像源：
   ```zsh
   pip config set global.index-url https://mirrors.aliyun.com/pypi/simple
   ```

2. 在 VSCode 中，按`Ctrl/Command + Shift + P`并搜索`Python: Select Interpreter`，点击`创建虚拟环境`，选择`Venv`，勾选`requirements-core.txt`，点击确定，然后等待创建完成。

3. 如果提示创建虚拟环境时出错，请注意勾选的是`requirements-core.txt`，不是`requirements.txt`。

4. 如果创建虚拟环境用时长于 5 分钟，请检查网络连接是否正常，以及是否忘记修改 pip 镜像源。

## Step 3 使用方法

### 3.1 运行程序

1. 若左侧无项目文件列表，请点击左上角的“资源管理器”按钮来把它打开。
2. 点击项目文件列表中的`app.py`，然后点击右上角的`运行 Python 文件`。
3. 查看命令行，并在按下`Ctrl/Cmd`后，鼠标左键点击`http://127.0.0.1:5xxx`以在浏览器中打开主界面。

### 3.2 上传 PDF 并处理

1. 点击“选择PDF文件”，然后选择需要处理的 PDF 文件。
2. 填写 PDF 数据：目录起始页指的是目录的第一页是 PDF 文件的第几页；目录结束页指的是目录的最后一页是 PDF 文件的第几页；正文起始页指的是正文的第一页是 PDF 文件的第几页。
3. 点击“开始执行”，等待进度条走完，浏览器会自动下载带有书签的 PDF 文件。