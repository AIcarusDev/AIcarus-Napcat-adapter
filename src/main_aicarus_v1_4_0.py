# AIcarus Napcat Adapter - Main Entry Point for Protocol v1.4.0
# aicarus_napcat_adapter/src/main_aicarus_v1_4_0.py
import asyncio
import sys
import json
import time
import uuid
import websockets  # 确保导入

# 项目内部模块
from .logger import logger
from .recv_handler_aicarus_v1_4_0 import RecvHandlerAicarus
from .send_handler_aicarus_v1_4_0 import send_handler_aicarus
from .config import get_config  # 使用 get_config()
from .aic_com_layer_v1_4_0 import (  # 从新的 v1.4.0 通信层导入
    aic_start_com,  # 这个函数现在会启动 core_connection_client.run_forever()
    aic_stop_com,  # 这个函数会调用 core_connection_client.stop_communication()
    router_aicarus as core_router,  # router_aicarus 是 core_connection_client 的实例
)

# 从新的消息队列模块导入 (如果 napcat_event_processor 仍使用它)
from .message_queue import (
    internal_event_queue,
    put_napcat_api_response,
    check_stale_api_responses_periodically,
)

# v1.4.0 协议库
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

# 创建处理器实例
recv_handler_aicarus = RecvHandlerAicarus()


async def napcat_message_receiver(
    server_connection: websockets.WebSocketServerProtocol,
):
    """处理来自 Napcat 的连接和消息"""
    logger.info(f"Napcat 客户端已连接: {server_connection.remote_address}")
    recv_handler_aicarus.server_connection = server_connection
    send_handler_aicarus.server_connection = server_connection

    # 首次连接时，尝试获取并缓存 bot_id
    await recv_handler_aicarus._get_bot_id()
    logger.info(
        f"AIcarus Adapter: Napcat Bot ID identified as: {recv_handler_aicarus.napcat_bot_id}"
    )

    try:
        async for raw_message_str in server_connection:
            logger.debug(
                f"AIcarus Adapter: Raw from Napcat: {raw_message_str[:120]}..."
                if len(raw_message_str) > 120
                else raw_message_str
            )
            try:
                napcat_event: dict = json.loads(raw_message_str)
            except json.JSONDecodeError:
                logger.error(
                    f"AIcarus Adapter: Failed to decode JSON from Napcat: {raw_message_str}"
                )
                continue

            post_type = napcat_event.get("post_type")

            if post_type in ["meta_event", "message", "notice", "request"]:
                await internal_event_queue.put(napcat_event)  # 将事件放入内部队列
            elif napcat_event.get("echo"):
                await put_napcat_api_response(napcat_event)  # 处理 Napcat API 响应
            elif post_type == "message_sent":
                logger.debug(
                    f"AIcarus Adapter: Processing message_sent event: {napcat_event}"
                )

                # 提取必要信息
                bot_id = str(napcat_event.get("self_id"))
                group_id = str(napcat_event.get("group_id"))
                user_id = str(napcat_event.get("user_id"))

                # 构造 v1.4.0 事件
                conversation_info = None
                if group_id:                    conversation_info = ConversationInfo(
                        conversation_id=group_id,
                        type=ConversationType.GROUP,
                        platform="napcat_qq",
                        name="", # 可以后续获取
                    )

                user_info = UserInfo(
                    platform="napcat_qq",
                    user_id=user_id,
                    user_name="", # 可以后续获取
                    user_displayname="",
                )

                # 构造事件内容
                content_segs = [
                    SegBuilder.message_sent(
                        sent_message_id=str(napcat_event.get("message_id", "")),
                        raw_message=napcat_event.get("raw_message"),
                        message_content=napcat_event.get("message"),
                    )
                ]

                # 构造完整事件并发送到 Core
                message_sent_event = Event(
                    event_id=f"message_sent_{uuid.uuid4()}",
                    event_type="notice.message.sent",
                    time=napcat_event.get("time", time.time()) * 1000.0,
                    platform="napcat_qq",
                    bot_id=bot_id,
                    user_info=user_info,
                    conversation_info=conversation_info,
                    content=content_segs,
                    raw_data=json.dumps(napcat_event)
                )
                await recv_handler_aicarus.dispatch_to_core(message_sent_event)
            else:
                logger.warning(
                    f"AIcarus Adapter: Unknown Napcat data structure: {napcat_event}"
                )
    except websockets.exceptions.ConnectionClosedOK:
        logger.info(
            f"Napcat client {server_connection.remote_address} disconnected gracefully."
        )
    except websockets.exceptions.ConnectionClosedError as e:
        logger.warning(
            f"Napcat client {server_connection.remote_address} connection closed with error: {e}"
        )
    except Exception as e:
        logger.error(
            f"处理 Napcat 连接时发生未知错误 ({server_connection.remote_address}): {e}",
            exc_info=True,
        )
    finally:
        logger.info(f"Napcat 客户端连接已结束: {server_connection.remote_address}")
        # 可以在这里进行一些清理，例如将 server_connection 实例置 None (如果 recv_handler 等处有检查)
        if recv_handler_aicarus.server_connection == server_connection:
            recv_handler_aicarus.server_connection = None
        if send_handler_aicarus.server_connection == server_connection:
            send_handler_aicarus.server_connection = None


async def napcat_event_processor():
    """从内部队列中取出 Napcat 事件并分发给相应的 AIcarus v1.4.0 协议处理器"""
    logger.info("Napcat 事件处理器已启动，等待处理事件... (Protocol v1.4.0)")
    while True:
        napcat_event = await internal_event_queue.get()  # 从内部队列获取事件
        post_type = napcat_event.get("post_type")

        logger.debug(f"正在处理 Napcat 事件 (post_type: {post_type}) - v1.4.0")
        try:
            if post_type == "meta_event":
                await recv_handler_aicarus.handle_meta_event(napcat_event)
            elif post_type == "message":
                await recv_handler_aicarus.handle_message_event(napcat_event)
            elif post_type == "notice":
                await recv_handler_aicarus.handle_notice_event(napcat_event)
            elif post_type == "request":
                await recv_handler_aicarus.handle_request_event(napcat_event)
            else:
                logger.warning(
                    f"AIcarus Adapter: Unknown post_type '{post_type}' in Napcat event."
                )
        except Exception as e:
            logger.error(
                f"AIcarus Adapter: Error processing Napcat event (post_type: {post_type}): {e}",
                exc_info=True,
            )
        finally:
            internal_event_queue.task_done()  # 标记任务完成


async def start_napcat_websocket_server(config):
    """启动 WebSocket 服务器，等待 Napcat 连接"""
    logger.info(
        f"启动 AIcarus Napcat Adapter WebSocket 服务器 (Protocol v{PROTOCOL_VERSION}): {config.adapter_server_host}:{config.adapter_server_port}"
    )

    try:
        async with websockets.serve(
            napcat_message_receiver,
            config.adapter_server_host,
            config.adapter_server_port,
            ping_interval=20,
            ping_timeout=10,
            max_size=2**20,  # 1MB max message size
        ):
            logger.info(
                f"AIcarus Napcat Adapter WebSocket 服务器已启动，等待 Napcat 连接... (Protocol v{PROTOCOL_VERSION})"
            )
            await asyncio.Future()  # 永远运行
    except Exception as e:
        logger.critical(
            f"启动 Napcat WebSocket 服务器时发生错误: {e}", exc_info=True
        )
        sys.exit(1)


async def main():
    """主函数，启动所有组件"""
    config = get_config()
    logger.info(f"AIcarus Napcat Adapter 正在启动... (Protocol v{PROTOCOL_VERSION})")
    logger.info(f"配置: Napcat 连接端口 {config.adapter_server_port}")
    logger.info(f"配置: Core 连接 URL {config.core_connection_url}")

    # 将 recv_handler 的 maibot_router 设置为 core_router，使其能够向 Core 发送消息
    recv_handler_aicarus.maibot_router = core_router
    logger.info("已将 recv_handler 的 Core 路由器配置完成。")

    # 注册 send_handler 的回调到 Core 通信层，使其能够接收来自 Core 的动作指令
    core_router.register_core_event_handler(send_handler_aicarus.handle_aicarus_action)
    logger.info("已注册 send_handler 为 Core 事件处理回调。")

    # 启动与 Core 的通信（异步任务）
    logger.info("启动与 AIcarus Core 的通信...")
    await aic_start_com()

    # 启动 Napcat 事件处理器（异步任务）
    logger.info("启动 Napcat 事件处理器...")
    napcat_processor_task = asyncio.create_task(napcat_event_processor())

    # 启动过期 API 响应检查器（异步任务）
    logger.info("启动过期 API 响应检查器...")
    stale_check_task = asyncio.create_task(check_stale_api_responses_periodically())

    # 启动 WebSocket 服务器等待 Napcat 连接（这会阻塞）
    try:
        await start_napcat_websocket_server(config)
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭 AIcarus Napcat Adapter...")
    except Exception as e:
        logger.critical(f"Adapter 运行时发生致命错误: {e}", exc_info=True)
    finally:
        # 清理和关闭
        logger.info("正在关闭所有组件...")

        # 取消异步任务
        if napcat_processor_task and not napcat_processor_task.done():
            napcat_processor_task.cancel()
            try:
                await napcat_processor_task
            except asyncio.CancelledError:
                logger.info("Napcat 事件处理器已停止。")

        if stale_check_task and not stale_check_task.done():
            stale_check_task.cancel()
            try:
                await stale_check_task
            except asyncio.CancelledError:
                logger.info("过期响应检查器已停止。")

        # 停止与 Core 的通信
        await aic_stop_com()

        logger.info("AIcarus Napcat Adapter 已完全关闭。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断。")
    except Exception as e:
        logger.critical(f"程序启动失败: {e}", exc_info=True)
        sys.exit(1)
