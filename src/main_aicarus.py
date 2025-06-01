# aicarus_napcat_adapter/src/main_aicarus.py
import asyncio
import sys
import json
import websockets  # 确保导入

# 项目内部模块
from .logger import logger
from .recv_handler_aicarus import recv_handler_aicarus
from .send_handler_aicarus import send_handler_aicarus
from .config import get_config  # 使用 get_config()
from .mmc_com_layer_aicarus import (  # 从新的通信层导入
    mmc_start_com,  # 这个函数现在会启动 core_connection_client.run_forever()
    mmc_stop_com,  # 这个函数会调用 core_connection_client.stop_communication()
    router_aicarus as core_router,  # router_aicarus 是 core_connection_client 的实例
)

# 从新的消息队列模块导入 (如果 napcat_event_processor 仍使用它)
from .message_queue import (
    internal_event_queue,
    put_napcat_api_response,
    check_stale_api_responses_periodically,
)


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
    """从内部队列中取出 Napcat 事件并分发给相应的 AIcarus 协议处理器"""
    logger.info("Napcat 事件处理器已启动，等待处理事件...")
    while True:
        napcat_event = await internal_event_queue.get()  # 从内部队列获取事件
        post_type = napcat_event.get("post_type")

        logger.debug(f"正在处理 Napcat 事件 (post_type: {post_type})")
        try:
            if post_type == "meta_event":
                await recv_handler_aicarus.handle_meta_event(napcat_event)
            elif post_type == "message":
                await recv_handler_aicarus.handle_message_event(napcat_event)
            elif post_type == "notice":
                await recv_handler_aicarus.handle_notice_event(napcat_event)
            # elif post_type == "request": # 如果 Napcat 有明确的 request 类型
            #     await recv_handler_aicarus.handle_request_event(napcat_event) # 你需要实现这个方法
            else:
                logger.warning(
                    f"AIcarus Adapter: Unknown post_type in internal_event_queue: {post_type} for event: {napcat_event}"
                )
        except Exception:
            logger.exception(  # 使用 logger.exception 可以自动记录堆栈跟踪
                f"AIcarus Adapter: 处理 Napcat 事件 (post_type: {post_type}) 时发生错误:"
            )
            logger.error(f"出错的事件数据: {napcat_event}")  # 记录导致错误的数据

        internal_event_queue.task_done()  # 通知队列任务已完成
        await asyncio.sleep(0.01)  # 短暂休眠，避免CPU满载，允许其他任务运行


async def run_adapter():
    """运行 Adapter 的主异步函数。"""
    adapter_cfg = get_config()  # 加载并获取配置

    # 将 Core 通信客户端 (router_aicarus) 实例传递给 recv_handler，
    # 以便 recv_handler 可以通过它将转换后的 AIcarusMessageBase 发送给 Core。
    recv_handler_aicarus.maibot_router = core_router

    # 注册 send_handler_aicarus.handle_aicarus_action 作为从 Core 收到消息时的回调函数。
    # 当 CoreConnectionClient 收到来自 Core 的消息时，会调用此回调。
    if hasattr(core_router, "register_core_message_handler"):
        core_router.register_core_message_handler(
            send_handler_aicarus.handle_aicarus_action
        )
    else:
        logger.critical(
            "Core 通信层 (router_aicarus) 没有 register_core_message_handler 方法！请检查 mmc_com_layer_aicarus.py。"
        )
        return  # 无法继续

    logger.info(
        "AIcarus Adapter: 正在启动 Napcat WebSocket 服务器 (监听 Napcat 客户端)..."
    )
    # 创建并启动 Adapter 的 WebSocket 服务器，用于接收来自 Napcat 客户端的连接
    napcat_listener_server = await websockets.serve(  # await serve
        napcat_message_receiver,
        adapter_cfg.adapter_server_host,
        adapter_cfg.adapter_server_port,
    )
    logger.info(
        f"AIcarus Adapter: Napcat WebSocket 服务器正在监听 ws://{adapter_cfg.adapter_server_host}:{adapter_cfg.adapter_server_port}"
    )

    # 启动与 Core 的通信层 (mmc_com_layer_aicarus)
    # mmc_start_com() 内部现在会异步启动 core_connection_client.run_forever()
    # 它会尝试连接到 Core 并保持连接，同时在后台接收来自 Core 的消息。
    await mmc_start_com()

    # 创建并运行后台任务
    napcat_processor_task = asyncio.create_task(napcat_event_processor())
    stale_response_checker_task = asyncio.create_task(
        check_stale_api_responses_periodically()
    )

    try:
        # 保持 Adapter 主进程运行，直到被中断
        # gather 的主要目的是等待这些后台任务，如果它们意外退出，gather 会传播异常
        # napcat_listener_server.wait_closed() 会在服务器关闭时完成
        await asyncio.gather(
            napcat_listener_server.wait_closed(),  # 等待 Napcat 监听服务器关闭
            napcat_processor_task,  # 等待事件处理任务
            stale_response_checker_task,  # 等待超时响应检查任务
            # mmc_start_com() 内部的 run_forever 也是一个循环，它会通过 core_router 实例保持
        )
    except asyncio.CancelledError:
        logger.info("Adapter 主运行任务被取消。")
    finally:
        logger.info("Adapter 主运行循环结束，开始清理...")
        if napcat_listener_server.is_serving():
            napcat_listener_server.close()
            await napcat_listener_server.wait_closed()

        if napcat_processor_task and not napcat_processor_task.done():
            napcat_processor_task.cancel()
        if stale_response_checker_task and not stale_response_checker_task.done():
            stale_response_checker_task.cancel()

        # await mmc_stop_com() # 确保与 Core 的连接也关闭 (graceful_shutdown_aicarus 中也会调用)


async def graceful_shutdown_aicarus():
    """执行优雅关闭操作。"""
    logger.info("AIcarus Adapter: 正在执行优雅关闭...")

    # 1. 停止与 Core 的通信
    await mmc_stop_com()

    # 2. 取消所有其他正在运行的 asyncio 任务 (除了当前任务)
    # 这通常在主程序捕获到 KeyboardInterrupt 时调用
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        logger.info(f"正在取消 {len(tasks)} 个剩余的 asyncio 任务...")
        for task in tasks:
            task.cancel()
        try:
            # 等待所有任务被取消
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("所有剩余的 asyncio 任务已处理完毕。")
        except Exception as e_gather:
            logger.error(f"等待任务取消时发生错误: {e_gather}")
    else:
        logger.info("没有其他正在运行的 asyncio 任务需要取消。")

    logger.info("AIcarus Adapter: 优雅关闭完成。")


def main_aicarus_entry():
    """Adapter 程序的主入口点。"""
    # 获取配置，这也会触发默认配置文件的创建（如果不存在）
    try:
        get_config()
    except Exception as e_cfg:
        logger.critical(f"Adapter 启动失败：无法加载配置。错误: {e_cfg}", exc_info=True)
        return  # 配置失败则不继续

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    main_task = None
    try:
        main_task = loop.create_task(run_adapter())  # 创建主运行任务
        loop.run_until_complete(main_task)  # 运行直到主任务完成
    except KeyboardInterrupt:
        logger.warning(
            "AIcarus Adapter: 收到用户中断信号 (KeyboardInterrupt)，正在关闭..."
        )
    except asyncio.CancelledError:
        logger.info("AIcarus Adapter: 主任务 (run_adapter) 被取消。")
    except Exception as e:  # 捕获 run_adapter 中可能未处理的异常
        logger.critical(f"AIcarus Adapter: 主程序发生严重错误: {e}", exc_info=True)
    finally:
        logger.info("AIcarus Adapter: 开始最终清理流程...")
        if main_task and not main_task.done():  # 如果主任务因异常退出但未被取消
            main_task.cancel()
            try:
                loop.run_until_complete(main_task)  # 等待主任务取消
            except asyncio.CancelledError:
                pass  # 预期的取消
            except Exception as e_final_main:
                logger.error(f"等待主任务取消时发生错误: {e_final_main}")

        # 执行优雅关闭逻辑
        # graceful_shutdown_aicarus 内部的异步操作也需要在事件循环中运行
        if loop.is_running():  # 确保循环仍在运行以执行关闭操作
            loop.run_until_complete(graceful_shutdown_aicarus())
        else:  # 如果循环已关闭，尝试在新循环中运行关闭（不推荐，但作为后备）
            try:
                asyncio.run(graceful_shutdown_aicarus())
            except Exception as e_shutdown_fallback:
                logger.error(f"在后备关闭流程中发生错误: {e_shutdown_fallback}")

        # 关闭事件循环相关的资源 (仅 Python 3.9+)
        if sys.version_info >= (3, 9):
            try:
                # loop.run_until_complete(loop.shutdown_default_executor()) # 关闭默认执行器
                # 这个调用有时会引发 RuntimeError 如果事件循环已经关闭
                # 更安全的方式是确保在循环关闭前完成所有异步生成器的清理
                all_tasks_final = [
                    t
                    for t in asyncio.all_tasks(loop=loop)
                    if t is not asyncio.current_task()
                ]
                if all_tasks_final:
                    logger.debug(f"最终清理：等待 {len(all_tasks_final)} 个任务完成...")
                    loop.run_until_complete(
                        asyncio.gather(*all_tasks_final, return_exceptions=True)
                    )
            except RuntimeError as e_shutdown_exec:
                logger.warning(f"关闭默认执行器时出错 (可能已关闭): {e_shutdown_exec}")
            except Exception as e_final_cleanup:
                logger.error(f"最终清理阶段发生错误: {e_final_cleanup}")

        if not loop.is_closed():
            loop.close()
        logger.info("AIcarus Adapter: 事件循环已关闭。程序退出。")


if __name__ == "__main__":
    # 当直接运行此文件时 (python src/main_aicarus.py)，调用主入口函数
    # 但推荐通过项目根目录的 run_adapter.py 来启动
    main_aicarus_entry()
