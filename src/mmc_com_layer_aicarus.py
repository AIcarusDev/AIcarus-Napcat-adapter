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
    # 但如果需要类型提示，可以考虑 from .send_handler_aicarus import SendHandlerAicarus
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
# 参数：收到的消息字典 (通常是 AicarusMessageBase.to_dict() 的结果)
CoreMessageCallback = Callable[[Dict[str, Any]], Awaitable[None]]


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
        self._on_message_from_core_callback: Optional[CoreMessageCallback] = (
            None  # 处理从 Core 收到的消息的回调
        )

    def register_core_message_handler(self, callback: CoreMessageCallback) -> None:
        """注册一个回调函数，用于处理从 Core 服务器收到的消息。"""
        self._on_message_from_core_callback = callback
        logger.info(
            f"已为来自 Core 的消息注册处理回调: {callback.__name__ if hasattr(callback, '__name__') else callback}"
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
            # 可以在连接时发送一个初始的 "hello" 或身份验证消息 (如果 Core 需要)
            # 例如，通过 extra_headers 参数
            # headers = {"X-Platform-ID": self.platform_id}
            # self.websocket = await websockets.connect(self.core_ws_url, extra_headers=headers)
            self.websocket = await websockets.connect(self.core_ws_url)  # 简单连接
            logger.info(f"已成功连接到 Core WebSocket 服务器: {self.core_ws_url}")
            # 可以在连接成功后发送一个初始的注册/心跳消息 (如果协议需要)
            # 例如，发送一个 meta:lifecycle connect 事件
            from aicarus_protocols import MessageBase, BaseMessageInfo, Seg # 避免循环导入
            connect_meta = MessageBase(
                message_info=BaseMessageInfo(
                    platform=self.platform_id, # 用 Adapter 的 ID
                    bot_id=self.platform_id, # Adapter 自身标识, 修改为 platform_id
                    interaction_purpose="platform_meta",
                    time=time.time() * 1000,
                    additional_config={"protocol_version": "1.2.0"} # 使用你的协议版本
                ),
                message_segment=Seg(type="seglist", data=[
                    Seg(type="meta:lifecycle", data={"lifecycle_type": "connect", "details": {"adapter_platform": "napcat", "adapter_version": "0.1.0"}})
                ])
            )
            await self.send_message_to_core(connect_meta.to_dict())
            logger.info("已向 Core 发送 platform_meta (lifecycle connect) 消息。")
            return True
        except InvalidURI:
            logger.critical(
                f"连接 Core 失败: 无效的 WebSocket URI '{self.core_ws_url}'"
            )
        except ConnectionRefusedError:
            logger.error(
                f"连接 Core 失败 ({self.core_ws_url}): 连接被拒绝。请确保 Core 服务器正在运行并监听正确地址。"
            )
        except WebSocketException as e:  # 更通用的 WebSocket 异常
            logger.error(
                f"连接 Core ({self.core_ws_url}) 时发生 WebSocket 异常: {e}",
                exc_info=True,
            )
        except Exception as e:
            logger.error(
                f"连接 Core ({self.core_ws_url}) 时发生未知错误: {e}", exc_info=True
            )

        self.websocket = None  # 连接失败，重置 websocket 实例
        return False

    async def _receive_loop(self) -> None:
        """持续接收来自 Core 的消息，并在收到消息时调用回调。"""
        while self._is_running and self.websocket and self.websocket.open:
            try:
                message_str = await self.websocket.recv()
                logger.debug(f"从 Core 收到消息: {message_str[:200]}...")
                try:
                    message_dict = json.loads(message_str)
                    logger.info(f"接收到来自 Core 的消息内容: {message_dict}")
                    if self._on_message_from_core_callback:
                        # 将收到的字典直接传递给回调函数
                        # 回调函数 (send_handler_aicarus.handle_aicarus_action) 负责解析为 AicarusMessageBase
                        await self._on_message_from_core_callback(message_dict)
                    else:
                        logger.warning("收到来自 Core 的消息，但没有注册处理回调。")
                except json.JSONDecodeError:
                    logger.error(f"从 Core 解码 JSON 失败: {message_str}")
                except Exception as e_proc:
                    logger.error(f"处理来自 Core 的消息时出错: {e_proc}", exc_info=True)
            except ConnectionClosed:
                logger.warning("与 Core 的 WebSocket 连接已关闭。将尝试重连。")
                break  # 退出接收循环，外层循环会处理重连
            except Exception as e_recv:
                logger.error(f"接收来自 Core 的消息时发生错误: {e_recv}", exc_info=True)
                # 发生未知错误时，也尝试断开并重连
                await asyncio.sleep(self._reconnect_delay / 2.0)  # 短暂等待后尝试重连
                break
        logger.info("Core 消息接收循环已停止。")

    async def run_forever(self) -> None:
        """启动并永久运行与 Core 的连接，包括自动重连。"""
        if not self._on_message_from_core_callback:
            logger.error("Core 消息处理回调未注册，无法启动与 Core 的通信。")
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
                logger.debug("Core 消息接收任务已成功取消。")
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

    async def send_message_to_core(self, message_dict: Dict[str, Any]) -> bool:
        """
        向 Core 发送一个已转换为字典的 AicarusMessageBase 消消息。

        Args:
            message_dict (Dict[str, Any]): 要发送的消息字典。

        Returns:
            bool: 如果消息成功发送则为 True，否则为 False。
        """
        if not self.websocket or not self.websocket.open:
            logger.warning("无法发送消息给 Core：未连接或连接已关闭。")
            return False
        try:
            message_json = json.dumps(message_dict, ensure_ascii=False)
            logger.info(f"发送消息到 Core: {message_json}")  # 打印发送的消息内容
            await self.websocket.send(message_json)
            logger.debug(f"成功发送消息给 Core: {message_json[:200]}...")
            return True
        except TypeError as e_json:  # JSON 序列化错误
            logger.error(
                f"序列化发送给 Core 的消息时出错: {e_json}. 消息内容: {message_dict}",
                exc_info=True,
            )
            return False
        except WebSocketException as e_ws:  # WebSocket 发送错误
            logger.error(
                f"通过 WebSocket 发送消息给 Core 时出错: {e_ws}", exc_info=True
            )
            # 可以在这里触发重连逻辑，或者让主循环处理
            return False
        except Exception as e:
            logger.error(f"发送消息给 Core 时发生未知错误: {e}", exc_info=True)
            return False


# --- 创建单例供其他模块使用 ---
# 这个实例将在 main_aicarus.py 中被获取和启动
core_connection_client = CoreConnectionClient()


# --- 辅助函数，用于在 main_aicarus.py 中调用 ---
async def mmc_start_com() -> None:
    """启动与 Core 的通信。"""
    # send_handler_aicarus 将在 main_aicarus.py 中被注册
    # 这里仅启动连接和接收循环
    # run_forever 是一个阻塞调用（在其内部循环），所以需要 create_task
    asyncio.create_task(core_connection_client.run_forever())


async def mmc_stop_com() -> None:
    """停止与 Core 的通信。"""
    await core_connection_client.stop_communication()


# 将 core_connection_client 重命名为 router_aicarus 以匹配你之前的用法
# 这样 main_aicarus.py 中的 recv_handler_aicarus.maibot_router = router 就能工作
router_aicarus = core_connection_client


if __name__ == "__main__":
    # 简单的本地测试 (需要一个能响应的 WebSocket 服务器在配置的 core_ws_url 上运行)
    async def main_test():
        logger.info("--- Core 通信层客户端测试 ---")

        # 模拟 Core 发送消息的处理函数
        async def dummy_core_message_handler(msg_dict: Dict[str, Any]):
            logger.info(f"[TEST HANDLER] 从 Core 收到消息: {msg_dict}")
            # 可以在这里模拟 Core 发送一个动作回来
            # if core_connection_client.websocket and core_connection_client.websocket.open:
            #     action_reply = {
            #         "message_info": {"interaction_purpose": "core_action", "...": "..."},
            #         "message_segment": {"type": "seglist", "data": [{"type": "action:some_action", "data": {}}]}
            #     }
            #     await core_connection_client.send_message_to_core(action_reply)

        core_connection_client.register_core_message_handler(dummy_core_message_handler)

        # 启动通信层 (它会自己处理连接和接收)
        # run_forever 是阻塞的，所以用 create_task
        comm_task = asyncio.create_task(core_connection_client.run_forever())

        # 模拟 Adapter 发送消息给 Core
        await asyncio.sleep(5)  # 等待连接建立
        if core_connection_client.websocket and core_connection_client.websocket.open:
            logger.info("测试：Adapter 尝试发送一条消息给 Core...")
            test_message_to_core = {  # 这是一个模拟的 AicarusMessageBase 字典
                "message_info": {
                    "platform": get_config().core_platform_id,
                    "bot_id": "test_bot_from_adapter",
                    "interaction_purpose": "user_message",
                    "time": time.time() * 1000,
                    "message_id": "adapter_msg_123",
                    "additional_config": {"protocol_version": "1.2.0"},
                },
                "message_segment": {
                    "type": "seglist",
                    "data": [
                        {
                            "type": "text",
                            "data": "你好，Core！来自 Adapter 的测试消息。",
                        }
                    ],
                },
            }
            await core_connection_client.send_message_to_core(test_message_to_core)
        else:
            logger.warning("测试：未能连接到 Core，无法发送测试消息。")

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
