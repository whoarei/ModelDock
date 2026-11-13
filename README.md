# ModelDock · 模型坞

插件化本地与远程模型测试平台。以 Tauri 构建 Windows 桌面应用，通过 Python 插件接入模型，使用 uv 维护每节点、每插件的运行环境，并支持 SSH Linux 节点。

当前仓库为 **方案阶段**，仅包含产品、技术设计与插件协议，尚无可运行应用。

## 方案文档

| 文档 | 内容 | 可编辑源数据 |
| --- | --- | --- |
| [产品方案](docs/product-plan.html) | 定位、对象关系、范围、界面、流程、指标与验收 | [product-plan.json](docs/sources/product-plan.json) |
| [技术方案](docs/technical-plan.html) | 系统架构、uv、SSH、任务状态、计时和验证计划 | [technical-plan.json](docs/sources/technical-plan.json) |
| [Python 插件协议](docs/python-plugin-protocol.html) | 插件清单、支持模型、Python API、分类/检测结果、可视化与兼容规则 | [python-plugin-protocol.json](docs/sources/python-plugin-protocol.json) |

下载仓库后，用浏览器直接打开各 HTML 文件即可离线阅读。GitHub 文件页展示的是 HTML 源码；请下载文件或克隆仓库后打开。文档包含左侧目录、默认橙色的 10 套配色切换与“打印 / 保存 PDF”入口，无 CDN 或远程字体依赖。

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

文档均为方案草案，版本以各文档页标识为准；更新日期：2026-11-13。文档交互验证与应用功能验收分开，本文不表示应用已经实现。
