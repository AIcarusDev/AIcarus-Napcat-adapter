# AIcarus-Napcat-adapter
AIcarus-Napcat-adapter 是一个高效、稳定的适配器，旨在将 Napcat 客户端的事件和 API 调用转换为 AIcarus 消息协议（版本 `v1.4.0`）进行通信。它作为 Napcat 和 AIcarus Core 之间的桥梁，确保消息能够无缝流动。

## ✨ 特性亮点 (v1.4.0)
* **协议升级：** 完全适配 AIcarus Message Protocol `v1.4.0` 版本，带来更丰富、更强大的消息处理能力。
* **双向通信：** 不仅能将 Napcat 事件（如消息、通知、请求）转换为 AIcarus 协议事件发送到 Core，也能接收来自 Core 的 AIcarus 动作指令，并转换为 Napcat API 调用执行。
* **智能事件处理：** 能够处理 Napcat 的 `meta_event`、`message`、`notice` 和 `request` 等多种事件类型，并将其标准化为 AIcarus 事件格式。
* **API 响应管理：** 内置消息队列和 API 响应管理机制，确保 Napcat API 调用的请求与响应正确匹配，并处理超时情况。
* **健壮性与稳定性：** 具备心跳机制，能够监控 Napcat 连接状态，并在连接中断时尝试自动重连，保障服务持续运行。
* **配置灵活：** 采用 `toml` 格式的配置文件，支持版本管理和自动更新/合并，确保配置平滑升级。
* **精细日志：** 使用 `Loguru` 作为日志工具，提供分级日志输出（控制台/文件），便于调试和监控适配器运行状态。

## 🚀 快速启动

1.  **环境准备**
    确保您的系统安装了 Python 3.8+。
    安装必要的依赖：
    ```bash
    pip install -r requirements.txt
    ```
    你将需要 `aiohappyeyeballs`, `aiohttp`, `websockets` 等核心库来满足运行需求。

2.  **配置适配器**
    首次运行 Adapter 时，系统会自动在项目根目录生成 `config.toml` 配置文件。
    请务必根据您的实际情况修改此文件，尤其是以下关键配置项：
    * `adapter_server.host` 和 `adapter_server.port`: Adapter 自身监听 Napcat 客户端的地址和端口。默认值为 `127.0.0.1:8095`。
    * `core_connection.url`: AIcarus Core WebSocket 服务器的连接地址。默认值为 `ws://127.0.0.1:8000/ws`。
    * `core_connection.platform_id`: Adapter 在 AIcarus Core 中注册的唯一平台 ID (例如: `napcat_qq`)。
    * `bot_settings.nickname`: 可选，设置 Bot 的昵称，用于一些消息处理或显示。

    **重要提示：** 每次配置文件被创建或更新后，程序都会提示您检查并退出。请您检查并确认配置无误后，重新启动 Adapter。

3.  **运行适配器**
    确保您已启动 Napcat 客户端并配置其连接到 Adapter 监听的地址（例如：`ws://127.0.0.1:8095`）。
    然后，运行主启动脚本：
    ```bash
    python run_adapter.py
    ```
    一旦成功启动，您将看到适配器连接到 Core 和等待 Napcat 连接的日志信息。

## 🛠️ 项目结构

```
AIcarus-Napcat-adapter/
├── run_adapter.py             # 适配器启动脚本
├── requirements.txt           # Python 依赖清单
├── config.toml                # 运行时配置文件 (首次启动自动生成)
├── template/
│   └── config_template.toml   # 配置文件模板
├── logs/
│   └── adapter/               # 日志文件目录
│       └──YYYY-MM-DD.log     # 日志文件 (例如: 2025-06-04.log)
└── src/
    ├── main_aicarus.py        # 适配器主入口，负责启动各项服务
    ├── aic_com_layer.py       # AIcarus Core 通信层，处理与 Core 的 WebSocket 连接
    ├── recv_handler_aicarus.py# 接收处理模块，将 Napcat 事件转换为 AIcarus 事件
    ├── send_handler_aicarus.py# 发送处理模块，将 AIcarus 动作转换为 Napcat API 调用
    ├── config.py              # 配置管理模块，处理配置加载、版本和合并
    ├── logger.py              # 日志工具模块，基于 Loguru
    ├── message_queue.py       # 内部消息队列和 API 响应管理
    ├── napcat_definitions.py  # 定义 Napcat 特有的常量和消息类型
    └── utils.py               # 辅助工具函数，包含 Napcat API 调用封装和图片处理

```

## 🤝 贡献
欢迎所有对 AIcarus-Napcat-adapter 的贡献！如果您有任何问题、建议或发现了 bug，请随时提出 Issue 或 Pull Request。

## 许可证
本项目采用 MIT 许可证。