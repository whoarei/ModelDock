# timm 图像分类插件

使用锁定的 timm 1.0.31、PyTorch 2.10.0 CPU、torchvision 0.25.0 环境，在 Windows x64 和 SSH Linux x64 上执行图像分类。每节点只维护一个插件环境。

本版目录包含 209 个 ImageNet-1k 预训练配置，来自常见 ResNet、EfficientNet、MobileNet、ConvNeXt、ViT、Swin、RegNet、DenseNet 家族。目录由 `scripts/prepare_timm.py` 使用锁定环境生成，不在应用启动时跟随上游变化。各配置都必须通过实际加载检查；目录数量不代表已经逐项完成业务精度或性能验收。

在导入模型中搜索配置、选择家族，可选择官方预训练权重、本地文件、URL 或 SSH 节点已有路径。官方来源优先下载 Hugging Face 发布方的 `model.safetensors`，缺失时尝试 `pytorch_model.bin`，配套使用内置 ImageNet-1k 类别。文件按摘要缓存，后续测试不自动联网。

自定义权重须匹配所选 timm 架构与配置，填写训练时的类别数，并提供相同顺序的 UTF-8 类别文件。接受 safetensors 或 PyTorch 的纯张量 state_dict（也支持 state_dict/model 包装及 module. 前缀），严格检查键与形状；PT/PTH 后缀不代表任意完整模型对象均可加载。PyTorch 加载固定使用 weights_only=True，不回退到可执行的模型对象反序列化。

预处理取自该配置的输入尺寸、插值、裁剪和归一化参数；若训练时修改过这些约定，应制作匹配的插件配置。输出为 softmax 分类概率，支持 Top-K、单图、批量、预热性能测试、分阶段计时与报告。当前仅 CPU、batch=1；检测、分割、特征向量输出和 CUDA 环境不在本插件首版范围。

模型架构、类别描述与配置来源为 [timm](https://github.com/huggingface/pytorch-image-models)（Apache-2.0）；各预训练权重遵循各自发布页的许可，应用下载前显示目录中记录的许可。应用安装包不捆绑预训练权重。自动测试所用零参数/固定分类头为合成权重，仅验证执行与协议，不代表预训练模型效果。
