# ModelDock 使用、开发与维护

本文保留使用约定、开发、验证、发布和文档维护说明。下列命令默认从仓库根目录执行，另有说明的除外。

首版参考插件仅使用 **CPU、batch=1、NCHW float32 输入**。GPU、视频、标注精度评估和纯推理张量基准尚未开放。分类概率和检测置信度均不代表准确率。

参考分类插件采用 RGB、中心裁剪、ImageNet 均值/方差，B0 为 224×224，B1 为 240×240，输出为 logits。YOLO 参考插件只支持 640×640、`[1, 4+C, N]`、xywh、类别概率、无内置 NMS 的检测导出；不支持直接导入任意 YOLO 版本、NHWC、分割或姿态导出。不同预处理约定请创建自己的插件。

## 应用在线更新

0.2.0 起，桌面安装版会在启动后检查新的稳定版，也可以从侧栏“应用更新”手动检查。查看更新说明后点击“下载并安装”，应用校验内容签名和版本后安装并重启。本机任务、权重下载或插件环境操作尚未完成时会阻止安装；网络与校验失败可重试。

更新保留用户目录中的模型、插件环境与测试记录。浏览器开发预览不提供安装更新；0.1.0 试用包需要手动安装一次 0.2.0，之后可在线更新。首次正式安装包见 [v0.2.0](https://github.com/whoarei/ModelDock/releases/tag/v0.2.0)。

## 从 URL 导入权重

在“模型管理 → 导入模型”选择插件和支持模型，将“权重来源”切换为“URL 下载”，粘贴 HTTP/HTTPS 文件直链后点击“下载权重”。可选填写保存文件名和发布方提供的 SHA-256；下载完成后配置类别文件与参数，点击“验证并导入”。下载成功不等于模型兼容，仍由插件完成加载检查。

选中本机时下载到本机缓存；选中 SSH 节点时由该节点直接下载，类别文件填写远端路径。单文件最大 2 GiB，当前节点最多同时下载 3 个文件；支持重定向、取消和失败重试，重试从头开始。关闭导入窗口会请求取消正在进行的下载，成功文件保留在内容缓存中。链接返回登录页或分享网页时会提示改用文件直链；首批插件仍只支持声明的 ONNX 格式。

URL 权重下载从 0.3.0 起提供。

## timm 图像分类

在插件管理准备“timm 图像分类”的 torch-cpu 环境，再导入模型。timm 使用 SDK 0.1.1 的可选 describe/1 元数据接口；目录固定于 timm 1.0.31，包含 209 个常见 ImageNet-1k 配置，可搜索模型名并按家族筛选。选择“官方预训练权重”下载后自动填入 ImageNet 类别；也可导入匹配架构的 safetensors 或 PT/PTH/BIN 张量权重，填写训练时的类别数与类别文件。加载严格检查权重键、形状与类别数。

本版仅 CPU、batch=1，自动采用所选配置的输入尺寸、裁剪和归一化参数；训练时更改预处理的权重需提供匹配插件配置。安装包不捆绑预训练权重，下载前显示权重许可。目录配置逐次执行加载检查，目录数量不代表逐项业务精度与性能验收。详见 [插件说明](../plugins/timm/README.md)。

## 本地开发

需要 uv 0.13.6、Node.js 22+。Windows 原生开发还需要 Rust stable、Visual Studio C++ Build Tools 和 WebView2。发行安装包携带 uv 和控制器，首次准备 Python/依赖需要联网，之后就绪的本机环境可离线测试；不包含业务模型权重。

```sh
uv sync --locked
npm ci --prefix apps/desktop
uv run python scripts/prepare_resources.py --rust-licenses
```

开发原生桌面窗口：

```sh
cd apps/desktop
npm run tauri -- dev
```

也可以用两个终端运行开发预览（HTTP 桥仅监听 127.0.0.1，发行程序通过 Tauri IPC/stdio 调用控制器）：

```sh
uv run python -m modeldock.cli serve
```

```sh
npm run dev --prefix apps/desktop
```

修改 SDK 后，重新构建随插件分发的 wheel 并刷新它的锁定摘要，再生成资源。uv 工具从官方固定版本下载，并校验仓库中记录的 SHA-256；发行资源包括第三方许可。

```sh
uv run python scripts/prepare_plugins.py --lock
uv run python scripts/prepare_resources.py --rust-licenses
```

## 测试与 Windows 构建

```sh
uv run ruff check packages plugins scripts tests
uv run pytest
npm run build --prefix apps/desktop
```

界面端到端检查使用真实的本机开发桥、uv 环境和 ONNX Runtime。开发机安装 Playwright Chromium 后，在 `apps/desktop` 执行 `npx playwright test`；也可用 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 指定已有 Chromium。

`Verify ModelDock` 工作流分别验证 Linux 后端/SSH/浏览器和 Windows 后端/原生构建。Windows 流程构建 NSIS 安装器，并启动 Tauri/WebView2，通过真实 IPC 检查环境、分类、检测、预览和文件导出。成功后可从 Actions 下载 `ModelDock-windows-x64` 产物。稳定版安装包见 [Releases](https://github.com/whoarei/ModelDock/releases/latest)。

`tests` 与 `scripts/create_fixtures.py` 使用微型 ONNX 测试图（颜色分类和固定检测张量）验证协议、NMS、坐标和任务行为，**不是预训练 EfficientNet/YOLO 权重，也不能用其结果宣称业务精度或模型性能**。仓库不捆绑预训练模型或第三方业务图片。

## SSH 节点要求

本机需要 OpenSSH 的 ssh、sftp、ssh-keyscan；远端需要 Linux x86_64、Python 3.11+、可写用户目录和后台进程存活能力。应用核对主机指纹后部署控制器，用 uv 准备插件 Python。使用密钥文件或 SSH agent；加密私钥请先加载到系统 agent，首版不保存口令。

用户在界面点击“检查并部署”后才写入远端工作目录。移除节点只删除连接配置，不删除远端数据。每次任务与传输都有明确节点归属；上传使用 SFTP、摘要校验和原子重命名。

## 发布维护

应用版本由桌面 package.json、Tauri 配置、Cargo.toml 与控制器版本共同维护；SDK（当前 0.1.1）和参考插件采用各自的兼容版本，不随应用版本一起升级。

推送 `v<应用版本>` 标签会先运行完整验证并构建 NSIS 包。配置仓库 Actions Secrets `TAURI_SIGNING_PRIVATE_KEY` 和 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` 后，构建器可签名并发布稳定版。没有签名 Secret 时仅生成草稿 Release，不能将未签名包发布为在线更新。

本地签名发布时，下载草稿安装包到 `<release-dir>`，使用首次发布的同一私钥：

```sh
cd apps/desktop
npm run tauri -- signer sign --private-key-path <private-key-file> --app-version 0.3.0 <installer.exe>
cd ../..
uv run python scripts/release_assets.py <release-dir> --record
```

将生成的 `release-signatures/v<版本>.json` 提交到 main，会触发 `Verify and publish locally signed release`。该文件只含公开签名、版本与安装包 SHA-256；流水线先检查草稿安装包摘要，再附加更新清单，并复用升级工作流测试下载、安装、重启和数据保留，通过后才发布为 latest。签名记录也可指定已通过验证的源构建，由流水线核对源码、安装包摘要后创建候选标签和草稿，无需重复构建。也可单独运行 `Verify signed application upgrade` 检查指定草稿标签。私钥必须独立安全备份；遗失后无法用现有安装版信任的公钥继续更新。仓库只保存公钥。

## 代码布局

```text
apps/desktop/                 React / TypeScript / Tauri
packages/controller/          stdlib 控制器、SQLite、uv、SSH、任务监督
packages/python-sdk/          插件接口、校验、计时、ONNX 适配及 Worker
plugins/efficientnet/          分类参考插件、SDK wheel 与锁文件
plugins/yolo/                  检测参考插件、SDK wheel 与锁文件
plugins/timm/                  PyTorch CPU 分类、预训练目录与锁文件
scripts/                      可重建资源和小型 ONNX 测试图
```

Rust 负责桌面系统能力和受控进程桥；本机和远端复用 Python 控制器，避免维护两套任务逻辑。安装目录只含程序资源，环境、权重缓存和任务保存在用户数据目录；可用 `MODELDOCK_DATA_DIR` 指定开发/测试数据目录。

## 方案文档

| 文档 | 内容 | 可编辑源数据 |
| --- | --- | --- |
| [产品方案](product-plan.html) | 定位、对象关系、范围、界面、流程、指标与验收 | [product-plan.json](sources/product-plan.json) |
| [技术方案](technical-plan.html) | 系统架构、uv、SSH、任务状态、计时和验证计划 | [technical-plan.json](sources/technical-plan.json) |
| [Python 插件协议](python-plugin-protocol.html) | 插件清单、支持模型、Python API、分类/检测结果、可视化与兼容规则 | [python-plugin-protocol.json](sources/python-plugin-protocol.json) |

下载仓库后，用浏览器直接打开各 HTML 文件即可离线阅读。GitHub 文件页展示的是 HTML 源码；请下载文件或克隆仓库后打开。文档包含左侧目录、默认橙色的 10 套配色切换与“打印 / 保存 PDF”入口，无 CDN 或远程字体依赖。

插件接口以 [Python 插件协议](python-plugin-protocol.html) 为持续维护的契约来源；新增或扩展接口时，同步维护源数据、兼容说明与测试。维护规则见 [AGENTS.md](../AGENTS.md)。

## 已确定的设计原则

- 插件是部署与环境维护单元；每节点、每插件一个启用中的 uv 环境。
- 插件声明支持的模型列表，用户导入权重与类别形成模型实例。
- 统一分类与检测结果协议，模型开发者主要实现 Python 适配器。
- 本机与 SSH 远程执行复用同一任务协议，任务状态与连接状态分别管理。
- 首批参考方向为 EfficientNet 分类与 YOLO 检测，兼容范围以实现阶段验证为准。

## 文档维护

风格及渲染工具来自用户指定的 [whoarei/skills](https://github.com/whoarei/skills) 中的 [rtd-html-docs](https://github.com/whoarei/skills/tree/f8d312ed5e5f091e80562cf463758787e176d208/rtd-html-docs)；本次固定提交为 `f8d312ed5e5f091e80562cf463758787e176d208`。该源仓库需要相应访问权限，工具不复制进本仓库。

编辑 `docs/sources/*.json` 后，使用该 skill 的渲染器重建（`<skill-dir>` 为其 `rtd-html-docs` 目录）：

```sh
node <skill-dir>/scripts/render.mjs --input docs/sources/product-plan.json --output docs/product-plan.html --force
node <skill-dir>/scripts/render.mjs --input docs/sources/technical-plan.json --output docs/technical-plan.html --force
node <skill-dir>/scripts/render.mjs --input docs/sources/python-plugin-protocol.json --output docs/python-plugin-protocol.html --force
```

验证使用相同 skill 的 `scripts/verify.mjs`，需要 Node.js、Playwright 和 Chromium。将截图、报告与验证 PDF 输出到仓库外的临时目录；浏览器模块和可执行文件路径按本机安装情况传入。

```sh
node <skill-dir>/scripts/verify.mjs docs/product-plan.html --output-dir <temporary-dir>/product --playwright <playwright-module> --browser <chromium>
node <skill-dir>/scripts/verify.mjs docs/technical-plan.html --output-dir <temporary-dir>/technical --playwright <playwright-module> --browser <chromium>
node <skill-dir>/scripts/verify.mjs docs/python-plugin-protocol.html --output-dir <temporary-dir>/plugin --playwright <playwright-module> --browser <chromium>
```

本次文档检查覆盖目录锚点、10 套配色及刷新恢复、桌面/窄屏布局、无存储和无 JavaScript 回退、打印入口和配色、折叠内容恢复，并人工查看了默认/深色/移动截图与关系图。

验证环境的 Chromium 限制 `file://` 导航，因此将 skill 校验脚本的页面入口临时改为本机 HTTP 预览，保留其余检查；未在该环境验证直接打开本地文件。交付 HTML 无外部运行依赖，验证截图、报告和临时 PDF 不纳入仓库。

文档版本以各文档页标识为准，已分别标注当前实现与后续规划；更新日期：2026-11-13。文档交互检查与应用功能验收分别进行。
