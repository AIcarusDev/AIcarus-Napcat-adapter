# AIcarusNapcatAdapter v2.0.0

**AIcarusNapcatAdapter** 是一个高效、稳定的适配器，旨在将 Napcat QQ 客户端的事件和 API 调用，无缝转换为 **AIcarus 消息协议 v1.6.0** 进行通信。它作为 Napcat 和 AIcarus Core 之间的核心桥梁，确保了消息和指令能够准确、可靠地双向流动。

## ✨ 功能亮点 (v2.0.0)

*   **协议适配 v1.6.0**: 全面兼容 AIcarus Message Protocol `v1.6.0` 版本，支持基于命名空间的动态事件类型系统，实现了真正的平台解耦。
*   **双向通信**:
    *   **事件上报**: 将 Napcat 的各类事件（如消息、通知、请求）标准化为 AIcarus 协议事件，并发送到 AIcarus Core。
    *   **动作执行**: 接收来自 Core 的 AIcarus 动作指令，并将其精确转换为 Napcat API 调用以执行相应操作（如发送消息、踢人、戳一戳等）。
*   **智能档案管理**:
    *   **上线自检**: 在适配器与 Core 成功连接后，会自动执行一次“上线安检”，获取机器人所在所有群聊的档案信息（如群名片、角色等），并同步至 Core。
    *   **被动更新**: 采用事件驱动模式，能够监听并处理由 Napcat 主动推送的机器人档案变更通知（例如群名片被修改），并实时将更新同步到 Core，确保数据的高时效性。
*   **健壮的连接管理**:
    *   内置双向心跳机制，主动监控与 Core 的连接健康度，同时也能响应 Napcat 的心跳检查。
    *   具备自动重连功能，在网络波动或服务重启导致连接中断时，能够自动尝试重新建立连接，保障服务的持续可用性。
*   **灵活的配置系统**:
    *   采用易于读写的 `toml` 格式作为配置文件。
    *   内置版本管理和自动更新机制。当使用新版本的模板时，系统会自动合并旧配置文件中的用户设置，实现平滑升级，减少手动配置的麻烦。
*   **清晰的日志系统**:
    *   集成 `Loguru` 日志库，提供结构化、分级别的日志输出。
    *   支持控制台和文件双路输出，并可独立配置级别，便于在开发调试和生产监控等不同场景下使用。

## 🚀 快速启动

1.  **环境准备**
    *   确保您的系统已安装 **Python 3.10** 或更高版本。
    *   使用 pip 安装所有必要的依赖库：
        ```bash
        pip install -r requirements.txt
        ```

2.  **配置适配器**
    *   首次运行适配器时，系统会在项目根目录自动生成一份 `config.toml` 配置文件。
    *   请打开此文件，并根据您的环境修改以下关键配置项：
        *   `[adapter_server]`: 设置适配器监听 Napcat 客户端连接的 `host` 和 `port` (默认: `127.0.0.1:8095`)。
        *   `[core_connection]`:
            *   `url`: AIcarus Core 的 WebSocket 服务器地址 (默认: `ws://127.0.0.1:8077`)。
            *   `platform_id`: **(极其重要!)** 此适配器在 AIcarus Core 中注册的唯一平台ID。**必须**与 Core 端 `platform_builders` 中定义的平台ID完全一致 (例如: `napcat_qq`)。
        *   `[bot_settings]`:
            *   `force_self_id`: （推荐）可在此处强制指定机器人的 QQ 号，以避免因 API 调用失败而无法获取。
    *   **重要提示**: 每次配置文件被创建或更新后，程序都会提示您检查并自动退出。请您检查并确认配置无误后，再重新启动适配器。

3.  **运行适配器**
    *   首先，确保您的 Napcat 客户端已启动，并已配置其正向 WebSocket 连接到适配器所监听的地址（例如：`ws://127.0.0.1:8095`）。
    *   然后，在项目根目录运行主启动脚本：
        ```bash
        python run_adapter.py
        ```
    *   启动成功后，您将在控制台看到适配器成功连接到 Core 和等待 Napcat 连接的日志信息。

## 🛠️ 项目结构

```
AIcarus-Napcat-adapter/
├── run_adapter.py             # 适配器主启动脚本
├── requirements.txt           # Python 依赖项清单
├── config.toml                # 运行时配置文件 (首次启动时自动生成)
├── template/
│   └── config_template.toml   # 配置文件模板，用于版本比对和新配置生成
└── src/
    ├── main_aicarus.py        # 程序主入口，负责编排和启动所有服务
    ├── aic_com_layer.py       # Core 通信层：管理与 AIcarus Core 的 WebSocket 连接
    ├── recv_handler_aicarus.py# 接收处理器：将 Napcat 事件转换为 AIcarus 标准事件
    ├── send_handler_aicarus.py# 发送处理器：将 AIcarus 动作指令转换为 Napcat API 调用
    ├── action_definitions.py  # 动作定义：实现所有可由 Core 调用的具体 QQ 平台动作
    ├── event_definitions.py   # 事件定义：定义如何将各类 Napcat 事件转换为标准协议格式
    ├── config.py              # 配置模块：负责加载、验证和更新配置文件
    ├── logger.py              # 日志模块：基于 Loguru 的全局日志配置
    ├── message_queue.py       # 消息队列：管理内部事件流和 API 响应的匹配
    ├── napcat_definitions.py  # Napcat 定义：包含 Napcat 特有的常量和枚举
    └── utils.py               # 工具函数：封装了通用的 Napcat API 调用和图像处理等功能
```

## 🤝 贡献代码

我们欢迎任何形式的贡献！如果您有任何问题、功能建议或发现了 bug，请通过提交 Issue 或 Pull Request 的方式告知我们。

## 许可证

本项目基于 [MIT](LICENSE) 许可证开源。