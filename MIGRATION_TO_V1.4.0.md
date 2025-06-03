# AIcarus-Napcat-adapter v1.4.0 迁移指南

## 迁移状态 ✅ 已完成

**最后更新**: 2025-06-03  
**版本状态**: v1.4.0 适配器已完成并通过所有测试

### 验证结果
- ✅ 协议安装: AIcarus-Message-Protocol v1.4.0
- ✅ 适配器文件: 所有 v1.4.0 文件已创建
- ✅ 模块导入: 所有模块可正常导入
- ✅ 配置文件: 配置加载正常
- ✅ 事件创建: 事件创建和序列化测试通过

## 概述

本指南说明如何从 AIcarus-Message-Protocol v1.2.0 迁移到 v1.4.0。新版本采用了全新的事件驱动架构，具有更好的类型安全性和扩展性。

## 主要变化

### 1. 协议结构变化

#### 旧版本 (v1.2.0)
- 使用 `MessageBase` 作为基础消息对象
- `interaction_purpose` 字段用于区分消息类型
- `GroupInfo` 表示群组信息
- 消息段结构不统一

#### 新版本 (v1.4.0)
- 使用 `Event` 作为基础事件对象
- `event_type` 采用层次化结构 (例如: `message.group.normal`)
- `ConversationInfo` 替代 `GroupInfo`，支持更多对话类型
- 所有内容统一为 `List[Seg]` 格式
- 6个主要事件类别：message, notice, request, action, action_response, meta

### 2. 文件结构

#### 新增的 v1.4.0 文件
- `recv_handler_aicarus_v1_4_0.py` - 接收处理器
- `send_handler_aicarus_v1_4_0.py` - 发送处理器
- `aic_com_layer_v1_4_0.py` - 通信层
- `main_aicarus_v1_4_0.py` - 主程序入口
- `napcat_definitions_v1_4_0.py` - 协议定义
- `run_adapter_v1_4_0.py` - 启动脚本

## 启动方式

### v1.2.0 (原版本)
```bash
python run_adapter.py
```

### v1.4.0 (新版本)
```bash
python run_adapter_v1_4_0.py
```

## 代码变化详解

### 1. 导入变化

#### 旧版本
```python
from aicarus_protocols.base import MessageBase, Seg, UserInfo, GroupInfo, BaseMessageInfo
```

#### 新版本
```python
from aicarus_protocols import (
    Event,
    UserInfo,
    ConversationInfo,
    Seg,
    SegBuilder,
    EventBuilder,
    EventType,
    ConversationType,
    PROTOCOL_VERSION,
)
```

### 2. 事件创建变化

#### 旧版本 (MessageBase)
```python
aicarus_message = MessageBase(
    message_info=BaseMessageInfo(
        platform="napcat",
        bot_id="12345",
        message_id="msg_001",
        time=1678886400000.0,
        interaction_purpose="user_message",
        group_info=GroupInfo(...),
        user_info=UserInfo(...),
    ),
    message_segment=Seg(type="seglist", data=[...]),
    raw_message=json.dumps(raw_data),
)
```

#### 新版本 (Event)
```python
event = Event(
    event_id="msg_001",
    event_type="message.group.normal",
    time=1678886400000.0,
    platform="napcat",
    bot_id="12345",
    user_info=UserInfo(...),
    conversation_info=ConversationInfo(...),
    content=[
        SegBuilder.text("Hello World"),
        SegBuilder.image(file_id="image123"),
    ],
    raw_data=json.dumps(raw_data),
)
```

### 3. 事件类型映射

| v1.2.0 interaction_purpose | v1.4.0 event_type |
|----------------------------|-------------------|
| `user_message` (群聊) | `message.group.normal` |
| `user_message` (私聊) | `message.private.friend` |
| `message_sent` | `message.group.normal` (bot 发送) |
| `platform_meta` | `meta.lifecycle.connect` |
| `platform_notification` | `notice.group.member_increase` |
| `platform_request` | `request.group.invite` |

### 4. 回调函数变化

#### 旧版本
```python
CoreMessageCallback = Callable[[Dict[str, Any]], Awaitable[None]]

async def handle_message(message_dict: Dict[str, Any]):
    message = MessageBase.from_dict(message_dict)
    # 处理 MessageBase
```

#### 新版本
```python
CoreEventCallback = Callable[[Dict[str, Any]], Awaitable[None]]

async def handle_event(event_dict: Dict[str, Any]):
    event = Event.from_dict(event_dict)
    # 处理 Event
```

### 5. 动作处理变化

#### 旧版本
```python
if action_type == "action:send_message":
    # 处理发送消息动作
```

#### 新版本
```python
if event.event_type.startswith("action."):
    action_type = content_seg.type  # 从内容段获取动作类型
    if action_type == "send_message":  # 移除了 "action:" 前缀
        # 处理发送消息动作
```

## 测试和验证

### 1. 协议版本检查
确保系统正确识别 v1.4.0 协议：
```python
from aicarus_protocols import PROTOCOL_VERSION
print(f"Protocol Version: {PROTOCOL_VERSION}")  # 应该输出 "1.4.0"
```

### 2. 事件序列化测试
```python
event = Event(...)
event_dict = event.to_dict()
restored_event = Event.from_dict(event_dict)
assert event.event_id == restored_event.event_id
```

### 3. 通信测试
启动 v1.4.0 适配器并验证：
- Core 连接建立
- Napcat 连接接收
- 消息转换正确性
- 动作执行成功

## 兼容性说明

### 向后兼容性
- **不保证向后兼容**：v1.4.0 是重大版本更新
- 原 v1.2.0 文件保持不变，可以并行运行
- 两个版本可以同时存在，通过不同的启动脚本选择

### 数据迁移
- 不需要数据库迁移
- 配置文件格式兼容
- 日志格式兼容

## 部署建议

### 1. 渐进式迁移
1. **测试阶段**：使用 `run_adapter_v1_4_0.py` 启动新版本进行测试
2. **验证阶段**：确保所有功能正常工作
3. **切换阶段**：更新生产环境启动脚本

### 2. 回滚方案
如果遇到问题，可以快速回滚到 v1.2.0：
```bash
# 停止 v1.4.0
# 启动 v1.2.0
python run_adapter.py
```

### 3. 监控要点
- 连接稳定性
- 消息转换准确性
- 性能对比
- 错误日志

## 故障排除

### 常见问题

1. **导入错误**
   ```
   ImportError: cannot import name 'Event' from 'aicarus_protocols'
   ```
   解决：确保 AIcarus-Message-Protocol 已更新到 v1.4.0

2. **协议版本不匹配**
   ```
   ProtocolVersionMismatch: Expected 1.4.0, got 1.2.0
   ```
   解决：检查 Core 是否支持 v1.4.0 协议

3. **配置问题**
   检查配置文件中的协议版本设置

### 调试技巧

1. **启用详细日志**
   ```python
   logger.setLevel(logging.DEBUG)
   ```

2. **检查事件格式**
   ```python
   logger.debug(f"Event dict: {event.to_dict()}")
   ```

3. **验证协议版本**
   ```python
   logger.info(f"Using protocol version: {PROTOCOL_VERSION}")
   ```

## 已修复的问题

在开发过程中遇到并已修复的问题：

### 1. ConversationInfo 构造参数问题
**问题**: `ConversationInfo.__init__() got an unexpected keyword argument 'conversation_type'`
**解决**: 将参数名从 `conversation_type` 修正为 `type`

### 2. ConversationInfo 名称参数问题  
**问题**: `ConversationInfo.__init__() got an unexpected keyword argument 'conversation_name'`
**解决**: 将参数名从 `conversation_name` 修正为 `name`

### 3. 参数顺序问题
**问题**: ConversationInfo 构造函数的参数顺序不正确
**解决**: 按照正确顺序传递参数：`conversation_id`, `type`, `platform`, `name`

## 最终状态

v1.4.0 适配器现已完全就绪：

- 🎯 **完整功能**: 支持所有 v1.4.0 事件类型
- 🔧 **并行部署**: 与 v1.2.0 版本共存，无冲突
- ✅ **全面测试**: 通过语法检查、导入测试、事件创建测试
- 📚 **完整文档**: 包含迁移指南和配置检查工具

### 快速启动
```bash
# 检查 v1.4.0 环境
python check_v1_4_0.py

# 启动 v1.4.0 适配器
python run_adapter_v1_4_0.py
```

### 回退方案
如需回退到 v1.2.0，只需使用原启动脚本：
```bash
python run_adapter.py
```

---
**项目**: AIcarus-Napcat-adapter  
**协议版本**: v1.4.0  
**完成时间**: 2025-06-03  
**状态**: ✅ 就绪可用
