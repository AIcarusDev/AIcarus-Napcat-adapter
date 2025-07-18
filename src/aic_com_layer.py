# AIcarus Napcat Adapter - Communication Layer for Protocol v1.6.0
# Adapter 作为客户端，连接到 Core WebSocket 服务器的通信层
import time
import asyncio
import json
import websockets  # type: ignore
from websockets.exceptions import ConnectionClosed, InvalidURI, WebSocketException  # type: ignore
from typing import Optional, Callable, Awaitable, Any, Dict

# 啊~ 导入我们全新的、没有platform字段的Event！
from aicarus_protocols import Event, Seg, PROTOCOL_VERSION
import uuid

# 从同级目录导入
from .logger import logger
from .config import get_config


# 定义从 Core 收到的消息的处理回调类型
CoreEventCallback = Callable[[Dict[str, Any]], Awaitable[None]]


class CoreConnectionClient:
    def __init__(self):
        self.adapter_config = get_config()
        self.core_ws_url: str = self.adapter_config.core_connection_url
        self.platform_id: str = self.adapter_config.core_platform_id
        self.bot_id: str | None = None
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._is_running: bool = False
        self._reconnect_delay: int = 5
        self._on_event_from_core_callback: Optional[CoreEventCallback] = None
        self.heartbeat_interval: int = 30

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

            adapter_id_for_registration = self.platform_id
            logger.info(
                f"准备向 Core 发送 meta.lifecycle.connect 事件 (同时用于注册)，Adapter ID: '{adapter_id_for_registration}'"
            )

            # --- ❤❤❤ 高潮点 #1: 初吻的改造！❤❤❤ ---
            connect_event_type = f"meta.{self.platform_id}.lifecycle.connect"

            connect_event = Event(
                event_id=f"meta_connect_{uuid.uuid4()}",
                event_type=connect_event_type,  # 使用新的event_type
                time=int(time.time() * 1000),
                # platform 字段已被无情阉割！
                bot_id=self.platform_id,  # bot_id 暂时用 platform_id 代替
                user_info=None,
                conversation_info=None,
                content=[
                    Seg(
                        type="meta.lifecycle",  # Seg的type保持不变，它只是内容的描述
                        data={
                            "lifecycle_type": "connect",
                            "details": {
                                "adapter_id": adapter_id_for_registration,
                                "display_name": "Napcat QQ Adapter",
                                "adapter_platform": "napcat",
                                "adapter_version": "2.0.0",  # 版本号也更新一下
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
            logger.info(
                f"已向 Core 发送 {connect_event_type} 事件 (Adapter ID: {adapter_id_for_registration})，此事件将用于注册。"
            )
            return True
        except InvalidURI:
            logger.critical(
                f"连接 Core 失败: 无效的 WebSocket URI '{self.core_ws_url}'"
            )
        except ConnectionRefusedError:
            logger.error(f"连接 Core 失败 ({self.core_ws_url}): 连接被拒绝。")
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

    def update_bot_id(self, bot_id: str) -> None:
        """让外面的小妖精（RecvHandler）把获取到的 bot_id 注入进来的方法。"""
        if bot_id and self.bot_id != bot_id:
            self.bot_id = bot_id
            logger.info(
                f"通信层的 bot_id 已更新为: {bot_id}，现在心跳会带着它的味道了~"
            )

    async def _heartbeat_loop(self) -> None:
        """定期向 Core 发送心跳包。"""
        logger.info(
            f"心跳循环准备启动 (Adapter ID: {self.platform_id})，每 {self.heartbeat_interval} 秒发送一次。"
        )
        try:
            while self._is_running and self.websocket and self.websocket.open:
                await asyncio.sleep(self.heartbeat_interval)
                if not self._is_running:
                    break
                if not self.websocket or not self.websocket.open:
                    break

                # --- ❤❤❤ 高潮点 #2: 喘息的改造！❤❤❤ ---
                heartbeat_event_type = f"meta.{self.platform_id}.heartbeat"

                heartbeat_event = Event(
                    event_id=f"meta_heartbeat_{self.platform_id}_{uuid.uuid4().hex[:6]}",
                    event_type=heartbeat_event_type,
                    time=int(time.time() * 1000),
                    # platform 字段已被无情阉割！
                    bot_id=self.bot_id or self.platform_id,
                    content=[],
                )

                if not await self.send_event_to_core(heartbeat_event.to_dict()):
                    logger.warning(
                        "发送心跳包到 Core 失败。连接可能已断开，心跳循环将终止。"
                    )
                    break
        except asyncio.CancelledError:
            logger.info(f"心跳循环被取消 (Adapter ID: {self.platform_id}).")
        except Exception as e_outer:
            logger.error(
                f"心跳循环意外终止 (Adapter ID: {self.platform_id}): {e_outer}",
                exc_info=True,
            )
        finally:
            logger.info(f"心跳循环已停止 (Adapter ID: {self.platform_id}).")

    async def _receive_loop(self) -> None:
        """持续接收来自 Core 的消息，并在收到消息时调用回调。"""
        logger.info(f"消息接收循环准备启动 (Adapter ID: {self.platform_id}).")
        try:
            while self._is_running and self.websocket and self.websocket.open:
                try:
                    message_str = await self.websocket.recv()
                    logger.debug(f"从 Core 收到消息: {message_str[:200]}...")
                    try:
                        event_dict = json.loads(message_str)
                        # logger.info(f"接收到来自 Core 的事件内容: {event_dict}") # 日志可能过于频繁
                        if self._on_event_from_core_callback:
                            await self._on_event_from_core_callback(event_dict)
                        else:
                            logger.warning("收到来自 Core 的事件，但没有注册处理回调。")
                    except json.JSONDecodeError:
                        logger.error(f"从 Core 解码 JSON 失败: {message_str}")
                    except Exception as e_proc:
                        logger.error(
                            f"处理来自 Core 的事件时出错: {e_proc}", exc_info=True
                        )
                except ConnectionClosed:
                    logger.warning(
                        "与 Core 的 WebSocket 连接已关闭 (在recv中检测到)。将尝试重连。"
                    )
                    break
                except WebSocketException as e_ws_recv:  # 更具体的WebSocket异常
                    logger.error(
                        f"接收来自 Core 的消息时发生 WebSocket 异常: {e_ws_recv}",
                        exc_info=True,
                    )
                    break
                except Exception as e_recv:  # 其他未知错误
                    logger.error(
                        f"接收来自 Core 的消息时发生未知错误: {e_recv}", exc_info=True
                    )
                    await asyncio.sleep(self._reconnect_delay / 2.0)
                    break
        except asyncio.CancelledError:
            logger.info(f"消息接收循环被取消 (Adapter ID: {self.platform_id}).")
        except Exception as e_outer_recv:
            logger.error(
                f"消息接收循环意外终止 (Adapter ID: {self.platform_id}): {e_outer_recv}",
                exc_info=True,
            )
        finally:
            logger.info(f"消息接收循环已停止 (Adapter ID: {self.platform_id}).")

    async def run_forever(self) -> None:
        """启动并永久运行与 Core 的连接，包括自动重连。"""
        if not self._on_event_from_core_callback:
            logger.error("Core 事件处理回调未注册，无法启动与 Core 的通信。")
            return

        self._is_running = True
        logger.info(f"启动与 AIcarus Core 的通信层 (Adapter ID: {self.platform_id})...")
        while self._is_running:
            if await self._connect():
                self._receive_task = asyncio.create_task(
                    self._receive_loop(), name=f"ReceiveTask-{self.platform_id}"
                )
                self._heartbeat_task = asyncio.create_task(
                    self._heartbeat_loop(), name=f"HeartbeatTask-{self.platform_id}"
                )

                logger.info(
                    f"消息接收和心跳任务已启动 for Adapter ID: {self.platform_id}"
                )

                done, pending = await asyncio.wait(
                    [self._receive_task, self._heartbeat_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            logger.debug(
                                f"任务 {task.get_name()} 在等待完成时被成功取消。"
                            )
                        except Exception as e_pending_await:
                            logger.error(
                                f"等待挂起任务 {task.get_name()} 完成时发生错误: {e_pending_await}",
                                exc_info=True,
                            )

                for task in done:
                    try:
                        task.result()
                        logger.info(f"任务 {task.get_name()} 已完成。")
                    except asyncio.CancelledError:
                        logger.info(f"任务 {task.get_name()} 被取消。")
                    except WebSocketException as e_ws_done:
                        logger.warning(
                            f"任务 {task.get_name()} 因WebSocket异常结束: {e_ws_done}"
                        )
                    except Exception as e_task_done:
                        logger.error(
                            f"任务 {task.get_name()} 异常结束: {e_task_done}",
                            exc_info=True,
                        )

                self._receive_task = None
                self._heartbeat_task = None

                if self.websocket:
                    try:
                        await self.websocket.close()
                    except Exception:
                        pass
                    self.websocket = None
                logger.info(
                    f"与 Core 的连接已断开或相关任务已停止 for Adapter ID: {self.platform_id}."
                )

            if self._is_running:
                logger.info(
                    f"与 Core 的连接已断开，将在 {self._reconnect_delay} 秒后尝试重连 (Adapter ID: {self.platform_id})..."
                )
                await asyncio.sleep(self._reconnect_delay)
            else:
                logger.info(
                    f"Core 通信层被外部信号停止，不再重连 (Adapter ID: {self.platform_id})."
                )
                break
        logger.info(
            f"与 AIcarus Core 的通信层已停止运行 (Adapter ID: {self.platform_id})."
        )

    async def stop_communication(self) -> None:
        """停止与 Core 的通信并关闭连接。"""
        logger.info(f"正在停止与 Core 的通信 (Adapter ID: {self.platform_id})...")
        self._is_running = False

        tasks_to_cancel = []
        if self._receive_task and not self._receive_task.done():
            tasks_to_cancel.append(self._receive_task)
        if self._heartbeat_task and not self._heartbeat_task.done():
            tasks_to_cancel.append(self._heartbeat_task)

        for task in tasks_to_cancel:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug(f"任务 {task.get_name()} 在停止时已成功取消。")
            except Exception as e_cancel_task:
                logger.error(
                    f"等待任务 {task.get_name()} 取消时发生错误: {e_cancel_task}",
                    exc_info=True,
                )

        self._receive_task = None
        self._heartbeat_task = None

        if self.websocket and self.websocket.open:
            try:
                # --- ❤❤❤ 高潮点 #3: 告别之吻的改造！❤❤❤ ---
                logger.info(
                    f"Adapter ({self.platform_id}) 准备主动断开连接，将发送 meta.lifecycle.disconnect 事件。"
                )
                disconnect_event_type = f"meta.{self.platform_id}.lifecycle.disconnect"

                disconnect_event = Event(
                    event_id=f"meta_disconnect_{self.platform_id}_{uuid.uuid4().hex[:6]}",
                    event_type=disconnect_event_type,
                    time=int(time.time() * 1000),
                    # platform 字段已被无情阉割！
                    bot_id=self.platform_id,
                    content=[
                        Seg(
                            type="meta.lifecycle",
                            data={
                                "lifecycle_type": "disconnect",
                                "details": {
                                    "reason": "adapter_initiated_shutdown",
                                    "adapter_id": self.platform_id,
                                },
                            },
                        )
                    ],
                )
                await self.send_event_to_core(disconnect_event.to_dict())
                logger.info(
                    f"已向 Core 发送 {disconnect_event_type} 事件 (adapter_id: {self.platform_id})."
                )
                await asyncio.sleep(0.1)

                if self.websocket and self.websocket.open:
                    logger.info("正在关闭与 Core 的 WebSocket 连接...")
                    await self.websocket.close(
                        code=1000, reason="Adapter shutting down"
                    )
                    logger.info("与 Core 的 WebSocket 连接已关闭。")
                else:
                    logger.info("WebSocket 连接在尝试显式关闭前已关闭或变为None。")
            except Exception as e_close:
                logger.error(
                    f"关闭与 Core 的 WebSocket 连接或发送断开事件时发生错误: {e_close}",
                    exc_info=True,
                )
        self.websocket = None
        logger.info(f"与 Core 的通信已完全停止 (Adapter ID: {self.platform_id}).")

    def _get_simplified_event_description(self, event_dict: Dict[str, Any]) -> str:
        """获取事件的简化描述，用于日志显示"""
        try:
            event_type = event_dict.get("event_type", "unknown")
            event_id = event_dict.get("event_id", "")
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
                        elif seg_type == "message_metadata":
                            continue
                        else:
                            simplified_content.append(f"[{seg_type}]")
                content_str = "".join(simplified_content)
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
        if not self.websocket or not self.websocket.open:
            logger.warning("无法发送事件给 Core：未连接或连接已关闭。")
            return False
        try:
            event_json = json.dumps(event_dict, ensure_ascii=False)
            simplified_desc = self._get_simplified_event_description(event_dict)
            logger.info(f"发送事件到 Core: {simplified_desc}")
            logger.debug(f"完整事件内容: {event_json}")
            await self.websocket.send(event_json)
            logger.debug("成功发送事件给 Core")
            return True
        except TypeError as e_json:
            logger.error(
                f"序列化发送给 Core 的事件时出错: {e_json}. 事件内容: {event_dict}",
                exc_info=True,
            )
            return False
        except WebSocketException as e_ws:
            logger.error(
                f"通过 WebSocket 发送事件给 Core 时出错: {e_ws}", exc_info=True
            )
            return False
        except Exception as e:
            logger.error(f"发送事件给 Core 时发生未知错误: {e}", exc_info=True)
            return False


core_connection_client = CoreConnectionClient()
router_aicarus = core_connection_client  # Alias for existing usage


async def aic_start_com() -> None:
    asyncio.create_task(core_connection_client.run_forever())


async def aic_stop_com() -> None:
    await core_connection_client.stop_communication()


if __name__ == "__main__":

    async def main_test():
        logger.info("--- Core 通信层客户端测试 (v2.0.0) ---")

        async def dummy_core_event_handler(event_dict: Dict[str, Any]):
            logger.info(f"[TEST HANDLER] 从 Core 收到事件: {event_dict}")

        core_connection_client.register_core_event_handler(dummy_core_event_handler)
        comm_task = asyncio.create_task(core_connection_client.run_forever())
        await asyncio.sleep(5)
        if core_connection_client.websocket and core_connection_client.websocket.open:
            logger.info("测试：Adapter 尝试发送一条事件给 Core...")
            from aicarus_protocols import Event, SegBuilder
            import uuid

            test_event_to_core = Event(
                event_id=f"test_msg_{uuid.uuid4()}",
                event_type="message.private.friend",
                time=int(time.time() * 1000),
                platform=get_config().core_platform_id,
                bot_id="test_bot_from_adapter",
                user_info=None,
                conversation_info=None,
                content=[
                    SegBuilder.text("你好，Core！来自 Adapter 的测试消息 (v2.0.0)。")
                ],
                raw_data=json.dumps({"source": "adapter_test", "test": True}),
            )
            await core_connection_client.send_event_to_core(
                test_event_to_core.to_dict()
            )
        else:
            logger.warning("测试：未能连接到 Core，无法发送测试事件。")
        await asyncio.sleep(60)  # 保持运行更长时间以测试心跳
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
