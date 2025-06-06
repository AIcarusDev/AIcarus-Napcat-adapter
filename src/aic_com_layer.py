# AIcarus Napcat Adapter - Communication Layer for Protocol v1.4.0
# Adapter 作为客户端，连接到 Core WebSocket 服务器的通信层
import time
import asyncio
import json
import websockets  # type: ignore
from websockets.exceptions import ConnectionClosed, InvalidURI, WebSocketException  # type: ignore
from typing import Optional, Callable, Awaitable, Any, Dict

# 从同级目录导入
try:
    from .logger import logger
    from .config import get_config
    # send_handler_aicarus 将被注册为回调，所以这里不需要直接导入它的函数
    # 但如果需要类型提示，可以考虑 from .send_handler_aicarus_v1_4_0 import SendHandlerAicarus
except ImportError:

    class FallbackLogger:
        def info(self, msg: str):
            print(f"INFO (core_comm): {msg}")

        def warning(self, msg: str):
            print(f"WARNING (core_comm): {msg}")

        def error(self, msg: str):
            print(f"ERROR (core_comm): {msg}")

        def debug(self, msg: str):
            print(f"DEBUG (core_comm): {msg}")

    logger = FallbackLogger()  # type: ignore

    class FallbackConfig:
        core_connection_url = "ws://127.0.0.1:8000/ws"
        core_platform_id = "test_adapter"

    def get_config():
        return FallbackConfig()


# 定义从 Core 收到的消息的处理回调类型
# 参数：收到的消息字典 (通常是 Event.to_dict() 的结果)
CoreEventCallback = Callable[[Dict[str, Any]], Awaitable[None]]


class CoreConnectionClient:
    def __init__(self):
        self.adapter_config = get_config()  # 获取 Adapter 的配置
        self.core_ws_url: str = self.adapter_config.core_connection_url
        self.platform_id: str = (
            self.adapter_config.core_platform_id
        )  # Adapter 在 Core 注册的 ID

        self.websocket: Optional[websockets.WebSocketClientProtocol] = (
            None  # WebSocket 连接实例
        )
        self._receive_task: Optional[asyncio.Task] = None  # 接收消息的后台任务
        self._is_running: bool = False
        self._reconnect_delay: int = 5  # 重连延迟（秒）
        self._on_event_from_core_callback: Optional[CoreEventCallback] = (
            None  # 处理从 Core 收到的事件的回调
        )

    def register_core_event_handler(self, callback: CoreEventCallback) -> None:
        """注册一个回调函数，用于处理从 Core 服务器收到的事件。"""
        self._on_event_from_core_callback = callback
        logger.info(
            f"已为来自 Core 的事件注册处理回调: {callback.__name__ if hasattr(callback, '__name__') else callback}"
        )

    async def _connect(self) -> bool:
        """尝试连接到 Core WebSocket 服务器。"""
        if self.websocket and self.websocket.open:
            logger.debug("已连接到 Core，无需重新连接。")
            return True
        try:
            logger.info(
                f"正在尝试连接到 Core WebSocket 服务器: {self.core_ws_url} (Platform ID: {self.platform_id})"
            )
            self.websocket = await websockets.connect(self.core_ws_url)
            logger.info(f"已成功连接到 Core WebSocket 服务器: {self.core_ws_url}")

            # 发送连接事件，使用正确的 Seg 构造
            from aicarus_protocols import Event, Seg, PROTOCOL_VERSION
            import uuid
            import json

            connect_event = Event(
                event_id=f"meta_connect_{uuid.uuid4()}",
                event_type="meta.lifecycle.connect",
                time=time.time() * 1000,
                platform=self.platform_id,
                bot_id=self.platform_id,
                user_info=None,
                conversation_info=None,
                content=[
                    Seg(
                        type="meta.lifecycle",
                        data={
                            "lifecycle_type": "connect",
                            "details": {
                                "adapter_platform": "napcat",
                                "adapter_version": "0.1.0",
                                "protocol_version": PROTOCOL_VERSION,
                            },
                        },
                    )
                ],
                raw_data=json.dumps(
                    {
                        "source": "adapter_connection",
                        "platform": self.platform_id,
                    }
                ),
            )
            await self.send_event_to_core(connect_event.to_dict())
            logger.info("已向 Core 发送 meta.lifecycle.connect 事件。")
            return True
        except InvalidURI:
            logger.critical(
                f"连接 Core 失败: 无效的 WebSocket URI '{self.core_ws_url}'"
            )
        except ConnectionRefusedError:
            logger.error(
                f"连接 Core 失败 ({self.core_ws_url}): 连接被拒绝。请确保 Core 服务器正在运行并监听正确地址。"
            )
        except WebSocketException as e:
            logger.error(
                f"连接 Core ({self.core_ws_url}) 时发生 WebSocket 异常: {e}",
                exc_info=True,
            )
        except Exception as e:
            logger.error(
                f"连接 Core ({self.core_ws_url}) 时发生未知错误: {e}", exc_info=True
            )

        self.websocket = None
        return False

    async def _receive_loop(self) -> None:
        """持续接收来自 Core 的消息，并在收到消息时调用回调。"""
        while self._is_running and self.websocket and self.websocket.open:
            try:
                message_str = await self.websocket.recv()
                logger.debug(f"从 Core 收到消息: {message_str[:200]}...")
                try:
                    event_dict = json.loads(message_str)
                    logger.info(f"接收到来自 Core 的事件内容: {event_dict}")
                    if self._on_event_from_core_callback:
                        # 将收到的字典直接传递给回调函数
                        # 回调函数 (send_handler_aicarus_v1_4_0.handle_aicarus_action) 负责解析为 Event
                        await self._on_event_from_core_callback(event_dict)
                    else:
                        logger.warning("收到来自 Core 的事件，但没有注册处理回调。")
                except json.JSONDecodeError:
                    logger.error(f"从 Core 解码 JSON 失败: {message_str}")
                except Exception as e_proc:
                    logger.error(f"处理来自 Core 的事件时出错: {e_proc}", exc_info=True)
            except ConnectionClosed:
                logger.warning("与 Core 的 WebSocket 连接已关闭。将尝试重连。")
                break  # 退出接收循环，外层循环会处理重连
            except Exception as e_recv:
                logger.error(f"接收来自 Core 的消息时发生错误: {e_recv}", exc_info=True)
                # 发生未知错误时，也尝试断开并重连
                await asyncio.sleep(self._reconnect_delay / 2.0)  # 短暂等待后尝试重连
                break
        logger.info("Core 事件接收循环已停止。")

    async def run_forever(self) -> None:
        """启动并永久运行与 Core 的连接，包括自动重连。"""
        if not self._on_event_from_core_callback:
            logger.error("Core 事件处理回调未注册，无法启动与 Core 的通信。")
            return

        self._is_running = True
        logger.info("启动与 AIcarus Core 的通信层...")
        while self._is_running:
            if await self._connect():  # 尝试连接
                self._receive_task = asyncio.create_task(
                    self._receive_loop()
                )  # 启动接收任务
                try:
                    await self._receive_task  # 等待接收任务结束 (例如连接断开)
                except asyncio.CancelledError:
                    logger.info("Core 连接的接收任务被取消。")
                    break  # 如果任务被取消，则退出主循环
                except Exception as e_task:
                    logger.error(
                        f"Core 连接的接收任务异常结束: {e_task}", exc_info=True
                    )

                # 接收任务结束后，清理 websocket，准备重连 (如果仍在运行)
                if self.websocket:
                    try:
                        await self.websocket.close()
                    except Exception:
                        pass  # 忽略关闭时的错误
                    self.websocket = None

            if self._is_running:  # 如果不是因为 stop() 导致循环结束
                logger.info(
                    f"与 Core 的连接已断开，将在 {self._reconnect_delay} 秒后尝试重连..."
                )
                await asyncio.sleep(self._reconnect_delay)
            else:
                logger.info("Core 通信层被外部信号停止，不再重连。")
                break
        logger.info("与 AIcarus Core 的通信层已停止运行。")

    async def stop_communication(self) -> None:
        """停止与 Core 的通信并关闭连接。"""
        logger.info("正在停止与 Core 的通信...")
        self._is_running = False  # 设置运行标志为 False，这将使 run_forever 循环退出

        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()  # 取消正在运行的接收任务
            try:
                await self._receive_task  # 等待任务实际取消
            except asyncio.CancelledError:
                logger.debug("Core 事件接收任务已成功取消。")
            except Exception as e_cancel:
                logger.error(f"等待接收任务取消时发生错误: {e_cancel}")

        if self.websocket and self.websocket.open:
            try:
                logger.info("正在关闭与 Core 的 WebSocket 连接...")
                await self.websocket.close(code=1000, reason="Adapter shutting down")
                logger.info("与 Core 的 WebSocket 连接已关闭。")
            except Exception as e_close:
                logger.error(f"关闭与 Core 的 WebSocket 连接时发生错误: {e_close}")
        self.websocket = None
        logger.info("与 Core 的通信已完全停止。")

    def _get_simplified_event_description(self, event_dict: Dict[str, Any]) -> str:
        """获取事件的简化描述，用于日志显示"""
        try:
            event_type = event_dict.get("event_type", "unknown")
            event_id = event_dict.get("event_id", "")

            # 如果是消息事件，提取简化的内容描述
            if event_type.startswith("message."):
                content = event_dict.get("content", [])
                simplified_content = []

                for seg in content:
                    if isinstance(seg, dict):
                        seg_type = seg.get("type", "")
                        if seg_type == "text":
                            text = seg.get("data", {}).get("text", "")
                            simplified_content.append(
                                text[:50] + "..." if len(text) > 50 else text
                            )
                        elif seg_type == "image":
                            simplified_content.append("[图片]")
                        elif seg_type == "face":
                            face_name = seg.get("data", {}).get("name", "[表情]")
                            simplified_content.append(face_name)
                        elif seg_type == "at":
                            user_id = seg.get("data", {}).get("user_id", "")
                            simplified_content.append(f"@{user_id}")
                        elif seg_type == "record":
                            simplified_content.append("[语音]")
                        elif seg_type == "video":
                            simplified_content.append("[视频]")
                        elif seg_type == "forward":
                            simplified_content.append("[合并转发]")
                        elif seg_type == "json_card":
                            simplified_content.append("[JSON卡片]")
                        elif seg_type == "xml_card":
                            simplified_content.append("[XML卡片]")
                        elif seg_type == "share":
                            simplified_content.append("[分享]")
                        elif seg_type == "message.metadata":
                            continue  # 跳过元数据段
                        else:
                            simplified_content.append(f"[{seg_type}]")

                content_str = "".join(simplified_content)

                # 添加用户和群组信息
                user_info = event_dict.get("user_info", {})
                conversation_info = event_dict.get("conversation_info", {})

                user_name = user_info.get("user_nickname", "") or user_info.get(
                    "user_id", ""
                )
                group_name = conversation_info.get("name", "") or conversation_info.get(
                    "conversation_id", ""
                )

                if conversation_info.get("type") == "group":
                    return f"群消息 {group_name}({user_name}): {content_str}"
                else:
                    return f"私聊消息 {user_name}: {content_str}"

            elif event_type.startswith("notice."):
                return f"通知事件: {event_type}"
            elif event_type.startswith("request."):
                return f"请求事件: {event_type}"
            elif event_type.startswith("meta."):
                return f"元事件: {event_type}"
            else:
                return f"事件: {event_type} (ID: {event_id})"

        except Exception as e:
            return f"事件解析错误: {e}"

    async def send_event_to_core(self, event_dict: Dict[str, Any]) -> bool:
        """
        向 Core 发送一个已转换为字典的 Event 事件。

        Args:
            event_dict (Dict[str, Any]): 要发送的事件字典。

        Returns:
            bool: 如果事件成功发送则为 True，否则为 False。
        """
        if not self.websocket or not self.websocket.open:
            logger.warning("无法发送事件给 Core：未连接或连接已关闭。")
            return False
        try:
            event_json = json.dumps(event_dict, ensure_ascii=False)

            # 使用简化描述进行info级别日志
            simplified_desc = self._get_simplified_event_description(event_dict)
            logger.info(f"发送事件到 Core: {simplified_desc}")

            # 原始完整事件放到debug级别
            logger.debug(f"完整事件内容: {event_json}")

            await self.websocket.send(event_json)
            logger.debug("成功发送事件给 Core")
            return True
        except TypeError as e_json:  # JSON 序列化错误
            logger.error(
                f"序列化发送给 Core 的事件时出错: {e_json}. 事件内容: {event_dict}",
                exc_info=True,
            )
            return False
        except WebSocketException as e_ws:  # WebSocket 发送错误
            logger.error(
                f"通过 WebSocket 发送事件给 Core 时出错: {e_ws}", exc_info=True
            )
            # 可以在这里触发重连逻辑，或者让主循环处理
            return False
        except Exception as e:
            logger.error(f"发送事件给 Core 时发生未知错误: {e}", exc_info=True)
            return False


# --- 创建单例供其他模块使用 ---
# 这个实例将在 main_aicarus_v1_4_0.py 中被获取和启动
core_connection_client = CoreConnectionClient()


# --- 辅助函数，用于在 main_aicarus_v1_4_0.py 中调用 ---
async def aic_start_com() -> None:
    """启动与 Core 的通信。"""
    # send_handler_aicarus_v1_4_0 将在 main_aicarus_v1_4_0.py 中被注册
    # 这里仅启动连接和接收循环
    # run_forever 是一个阻塞调用（在其内部循环），所以需要 create_task
    asyncio.create_task(core_connection_client.run_forever())


async def aic_stop_com() -> None:
    """停止与 Core 的通信。"""
    await core_connection_client.stop_communication()


# 将 core_connection_client 重命名为 router_aicarus 以匹配你之前的用法
# 这样 main_aicarus_v1_4_0.py 中的 recv_handler_aicarus.maibot_router = router 就能工作
router_aicarus = core_connection_client


if __name__ == "__main__":
    # 简单的本地测试 (需要一个能响应的 WebSocket 服务器在配置的 core_ws_url 上运行)
    async def main_test():
        logger.info("--- Core 通信层客户端测试 (v1.4.0) ---")

        # 模拟 Core 发送事件的处理函数
        async def dummy_core_event_handler(event_dict: Dict[str, Any]):
            logger.info(f"[TEST HANDLER] 从 Core 收到事件: {event_dict}")
            # 可以在这里模拟 Core 发送一个动作回来
            # if core_connection_client.websocket and core_connection_client.websocket.open:
            #     action_reply = {
            #         "event_id": "action_test_123",
            #         "event_type": "action.send_message",
            #         "time": time.time() * 1000,
            #         "platform": "core",
            #         "bot_id": "core_bot",
            #         "content": [{"type": "send_message", "data": {"segments": [{"type": "text", "data": {"text": "Test action"}}]}}]
            #     }
            #     await core_connection_client.send_event_to_core(action_reply)

        core_connection_client.register_core_event_handler(dummy_core_event_handler)

        # 启动通信层 (它会自己处理连接和接收)
        # run_forever 是阻塞的，所以用 create_task
        comm_task = asyncio.create_task(core_connection_client.run_forever())

        # 模拟 Adapter 发送事件给 Core
        await asyncio.sleep(5)  # 等待连接建立
        if core_connection_client.websocket and core_connection_client.websocket.open:
            logger.info("测试：Adapter 尝试发送一条事件给 Core...")
            from aicarus_protocols import Event, SegBuilder
            import uuid

            test_event_to_core = Event(
                event_id=f"test_msg_{uuid.uuid4()}",
                event_type="message.private.friend",
                time=time.time() * 1000,
                platform=get_config().core_platform_id,
                bot_id="test_bot_from_adapter",
                user_info=None,
                conversation_info=None,
                content=[
                    SegBuilder.text("你好，Core！来自 Adapter 的测试消息 (v1.4.0)。")
                ],
                raw_data=json.dumps(
                    {
                        "source": "adapter_test",
                        "test": True,
                    }
                ),
            )
            await core_connection_client.send_event_to_core(
                test_event_to_core.to_dict()
            )
        else:
            logger.warning("测试：未能连接到 Core，无法发送测试事件。")

        await asyncio.sleep(10)  # 保持运行一段时间以接收消息或测试重连

        logger.info("测试：正在停止与 Core 的通信...")
        await core_connection_client.stop_communication()

        if comm_task and not comm_task.done():
            comm_task.cancel()
            try:
                await comm_task
            except asyncio.CancelledError:
                logger.info("通信任务已取消。")

        logger.info("--- Core 通信层客户端测试结束 ---")

    asyncio.run(main_test())
