# autoContents 使用教程

## 项目概述

autoContents 是一款专为扫描版 PDF 设计的书签全自动生成工具，能够基于目录页内容创建可跳转书签。如果想先看看该工具的实际表现情况，请[点击这里](https://www.bilibili.com/video/BV14wKGeQEvr)。

该工具支持单栏、双栏及混合排版的目录结构，适用于扫描质量合格（页面倾斜度 ≤2°，文字清晰度满足 OCR 识别要求）的 PDF 文档。适用的文档长度无理论上限，实测 500+ 页可稳定生成，更高的还未测试。

![目录结构及适用范围说明](./docs/目录结构及适用范围说明.svg)

## Step 1 下载程序

- 如果你会用`git clone`命令，请将仓库克隆到本地。
- 如果你不会`git clone`命令，请点击页面顶部的绿色按钮`Code`，然后点击`Download ZIP`以下载程序源码。

## Step 2 配置环境

### 2.1 申请云服务 API-KEY

在 95% 以上的测试样本中，阿里云能够提供稳定且优质的服务，足以满足大多数需求。因此建议优先完成阿里云相关服务的申请。仅在生成结果质量严重低于预期时，再考虑使用 Azure 作为补充方案。[点此查看全部教程](./docs/如何申请云服务账户.md)。

### 2.2 配置运行环境与 API-KEY

#### 2.2.1 Windows 用户

1. 右键点击`setup_documents`文件夹中的`windows_install.bat`，选择“以管理员身份运行”，等待脚本运行完成。
2. 双击打开`setup_documents`文件夹中的`windows_setup_api_keys.bat`，并按要求配置。

#### 2.2.2 macOS 用户

1. 打开“终端”APP，输入`chmod +x `（注意最后面有空格；注意是`+x`不是`-x`），然后将`setup_documents`文件夹中的`macos_install.sh`和`macos_setup_api_keys.sh`文件拖入终端窗口，按`return`。
2. 将`macos_install.sh`文件拖入终端窗口，按`return`，然后根据提示进行安装。
    - 如果未安装`Xcode CLI Tools`，会先安装该程序，安装完成后请重新运行该脚本，进行后续步骤。
    - 输入密码时，输入的内容并不会显示在屏幕上，输入完成后按`return`即可。
3. 重新打开“终端”APP，输入`sudo `（注意最后面有空格），然后再将`macos_install.sh`文件拖入终端窗口，按`return`，等待脚本执行完成。
4. 输入`sudo zsh `，将`macos_setup_api_keys.sh`文件拖入终端窗口，按`return`，并按要求配置。

## Step 3 使用方法

### 3.1 运行程序

1. 双击根目录下的`windows_start.bat`或`macos_start.command`来启动程序。
2. 在弹出的命令行窗口中找到`http://127.0.0.1:5xxx`，并复制到浏览器以打开。

### 3.2 上传 PDF 并处理

1. 点击“选择PDF文件”，然后选择需要处理的 PDF 文件。
2. 填写 PDF 数据：目录起始页指的是目录的第一页是 PDF 文件的第几页；目录结束页指的是目录的最后一页是 PDF 文件的第几页；正文起始页指的是正文的第一页是 PDF 文件的第几页。
3. 点击“开始执行”，等待进度条走完，浏览器会自动下载带有书签的 PDF 文件。

## Step 4 手动修正

如果生成的目录有少量页码错误等问题，可使用`contents_editor`中的工具进行手动更正，

## 疑难解答与问题反馈

请阅读[常见问题解答](./docs/问题排查方案.md)进行问题排查。

## 虽然 Star 不多但也放一个 History

[![Star History Chart](https://api.star-history.com/svg?repos=NatsUIJM/autoContents&type=Date)](https://star-history.com/#NatsUIJM/autoContents&Date)