# Adapter 项目专属的消息队列和API响应管理模块

import asyncio
import time
from typing import Dict, Any, Optional

# 从同级目录导入 logger 和 config
try:
    from .logger import logger
    from .config import get_config  # 使用 get_config() 获取配置实例
except ImportError:
    # Fallback for isolated testing, though in a running app this import should work
    class FallbackLogger:
        def info(self, msg: str):
            print(f"INFO (message_queue.py): {msg}")

        def warning(self, msg: str):
            print(f"WARNING (message_queue.py): {msg}")

        def error(self, msg: str):
            print(f"ERROR (message_queue.py): {msg}")

    logger = FallbackLogger()  # type: ignore

    class FallbackConfig:
        napcat_heartbeat_interval_seconds = 30  # 提供一个默认值

    def get_config():
        return FallbackConfig()


# 用于存储 Napcat API 调用的响应
# 键是请求的 echo ID (通常是一个 UUID)，值是 asyncio.Future
# 当 Napcat 返回带有相同 echo ID 的响应时，对应的 Future 会被设置结果
_api_response_futures: Dict[str, asyncio.Future] = {}

# 用于存储响应的接收时间，以便清理超时的响应
_api_response_received_time: Dict[str, float] = {}

# 可选：内部事件/消息队列，用于解耦 Adapter 内部的组件
# 例如，WebSocket 接收线程可以将原始 Napcat 事件放入此队列，
# 由另一个任务（如 napcat_event_processor）来处理。
# 这与你之前参考代码中的 message_queue 类似。
internal_event_queue = asyncio.Queue()


async def get_napcat_api_response(
    request_echo_id: str, timeout_seconds: Optional[float] = None
) -> Any:
    """
    异步等待并获取 Napcat API 调用的响应。

    Args:
        request_echo_id (str): 发送给 Napcat API 请求时使用的 echo ID。
        timeout_seconds (float, optional): 等待响应的超时时间（秒）。
                                            如果为 None，则使用配置文件中的心跳间隔作为大致参考。

    Returns:
        Any: Napcat 返回的响应数据 (通常是字典)。

    Raises:
        asyncio.TimeoutError: 如果在超时时间内未收到响应。
    """
    adapter_config = get_config()  # 获取配置
    # 如果未指定超时时间，可以使用一个基于心跳的合理默认值，例如心跳间隔的两倍
    # 或者一个固定的较短超时，例如10-15秒，因为API调用通常不应花费太长时间
    effective_timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else float(adapter_config.napcat_heartbeat_interval_seconds * 2)
    )
    if effective_timeout <= 0:  # 确保超时时间为正
        effective_timeout = 15.0  # 一个备用默认值

    future = asyncio.Future()
    _api_response_futures[request_echo_id] = future
    logger.debug(
        f"正在为 Napcat API 请求 (echo: {request_echo_id}) 等待响应，超时时间: {effective_timeout}s"
    )

    try:
        # 等待 Future 被设置结果，或者超时
        response_data = await asyncio.wait_for(future, timeout=effective_timeout)
        logger.debug(f"收到 Napcat API 响应 (echo: {request_echo_id})")
        return response_data
    except asyncio.TimeoutError:
        logger.warning(
            f"等待 Napcat API 响应超时 (echo: {request_echo_id}, 超时: {effective_timeout}s)"
        )
        raise  # 将 TimeoutError 重新抛出，让调用者处理
    finally:
        # 清理对应的 Future 和时间戳
        if request_echo_id in _api_response_futures:
            del _api_response_futures[request_echo_id]
        if request_echo_id in _api_response_received_time:
            del _api_response_received_time[request_echo_id]


async def put_napcat_api_response(response_data: Dict[str, Any]) -> None:
    """
    当 Adapter 从 Napcat 收到一个 API 调用的响应时，调用此函数。
    它会找到对应的 Future 并设置其结果。

    Args:
        response_data (Dict[str, Any]): 从 Napcat 收到的完整响应字典，应包含 "echo" 字段。
    """
    echo_id = response_data.get("echo")
    if not echo_id:
        logger.warning(
            f"收到一个没有 echo ID 的 Napcat 响应，无法匹配请求: {response_data}"
        )
        return

    future = _api_response_futures.get(str(echo_id))  # echo_id 可能是整数或字符串
    if future and not future.done():
        future.set_result(response_data)  # 将响应数据设置为 Future 的结果
        _api_response_received_time[str(echo_id)] = time.monotonic()  # 记录响应时间
        logger.debug(f"已为 echo ID '{echo_id}' 设置 Napcat API 响应。")
    elif future and future.done():
        logger.warning(
            f"收到 echo ID '{echo_id}' 的重复或延迟的 Napcat 响应，但 Future 已完成。"
        )
    else:
        # 可能是超时后收到的响应，或者是一个未知的 echo ID
        logger.warning(
            f"收到 echo ID '{echo_id}' 的 Napcat 响应，但没有找到匹配的等待请求或请求已超时/取消。"
        )


async def check_stale_api_responses_periodically(
    interval_seconds: Optional[float] = None,
) -> None:
    """
    定期检查并清理可能已过时但未被正确移除的 API 响应 Future。
    这主要是一个保障机制，正常情况下 Future 会在 get_napcat_api_response 中被清理。
    """
    adapter_config = get_config()
    check_interval = (
        interval_seconds
        if interval_seconds is not None
        else float(adapter_config.napcat_heartbeat_interval_seconds * 2)
    )
    if check_interval <= 0:
        check_interval = 60.0  # 默认60秒检查一次

    logger.info(f"启动 Napcat API 响应超时清理任务，检查间隔: {check_interval}s")
    while True:
        await asyncio.sleep(check_interval)
        now = time.monotonic()
        stale_echo_ids = []
        # 检查 _api_response_received_time 中是否有远早于当前时间的条目
        # 这表示响应已收到，但可能 get_napcat_api_response 中的 finally 块由于某些原因未执行清理
        for echo_id, received_time in list(_api_response_received_time.items()):
            # 如果响应已收到超过 (例如) 5倍的心跳间隔，则认为它非常陈旧
            if now - received_time > (
                adapter_config.napcat_heartbeat_interval_seconds * 5
            ):
                stale_echo_ids.append(echo_id)
                logger.warning(f"发现陈旧的已接收响应 (echo: {echo_id})，将被清理。")

        # 检查 _api_response_futures 中是否有创建了很久但仍未完成的 Future
        # (这部分比较难判断，因为不知道其原始超时设置，get_napcat_api_response 中的 wait_for 会处理超时)
        # 主要清理 _api_response_received_time 即可

        for echo_id in stale_echo_ids:
            if echo_id in _api_response_futures:
                # 如果 Future 还在，并且未完成，可以尝试取消它
                future_to_cancel = _api_response_futures[echo_id]
                if not future_to_cancel.done():
                    future_to_cancel.cancel()
                    logger.debug(f"取消了陈旧响应 (echo: {echo_id}) 的 Future。")
                del _api_response_futures[echo_id]
            if echo_id in _api_response_received_time:
                del _api_response_received_time[echo_id]

        if stale_echo_ids:
            logger.info(f"清理了 {len(stale_echo_ids)} 个陈旧的 Napcat API 响应记录。")
        else:
            logger.debug("未发现需要清理的陈旧 Napcat API 响应记录。")


if __name__ == "__main__":
    # 简单测试 (需要在一个异步环境中运行)
    async def test_message_queue():
        logger.info("测试消息队列模块...")

        test_echo_id = "test-uuid-123"

        async def mock_napcat_responder():
            await asyncio.sleep(2)  # 模拟 Napcat 处理延迟
            response = {
                "echo": test_echo_id,
                "status": "ok",
                "data": {"message_id": "msg_abc"},
            }
            logger.info(f"模拟 Napcat 发送响应: {response}")
            await put_napcat_api_response(response)

        async def mock_api_caller():
            logger.info(f"模拟 Adapter 调用 Napcat API (echo: {test_echo_id})")
            try:
                api_result = await get_napcat_api_response(
                    test_echo_id, timeout_seconds=5
                )
                logger.info(f"Adapter 收到 API 结果: {api_result}")
                assert api_result["data"]["message_id"] == "msg_abc"
            except asyncio.TimeoutError:
                logger.error("Adapter 调用 Napcat API 超时！")
            except Exception as e:
                logger.exception(f"Adapter 调用 Napcat API 时发生错误: {e}")

        async def mock_timeout_caller():
            timeout_echo_id = "timeout-test-uuid"
            logger.info(
                f"模拟 Adapter 调用 Napcat API (echo: {timeout_echo_id})，预期超时。"
            )
            try:
                await get_napcat_api_response(timeout_echo_id, timeout_seconds=1)
            except asyncio.TimeoutError:
                logger.success("成功捕获到预期的 API 调用超时！")
            except Exception as e:
                logger.error(f"超时测试中发生意外错误: {e}")

        # 启动清理任务 (通常在主程序中启动)
        # cleanup_task = asyncio.create_task(check_stale_api_responses_periodically(interval_seconds=5))

        await asyncio.gather(
            mock_api_caller(), mock_napcat_responder(), mock_timeout_caller()
        )

        # cleanup_task.cancel() # 测试完成后取消清理任务
        # try:
        #     await cleanup_task
        # except asyncio.CancelledError:
        #     logger.info("超时清理任务已取消。")

        logger.info("消息队列模块测试结束。")

    asyncio.run(test_message_queue())
