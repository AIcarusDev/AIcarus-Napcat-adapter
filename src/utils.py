# aicarus_napcat_adapter/src/utils.py
# Adapter 项目专属的工具函数，主要用于与 Napcat API 交互
from typing import Dict, Any, Optional, Union, List
import asyncio
import json
import uuid
import aiohttp
import ssl
import base64
import io
from PIL import Image  # 用于图片格式处理

# 从同级目录导入
try:
    from .logger import logger

    # get_napcat_api_response 和 put_napcat_api_response 现在由 message_queue.py 提供
    from .message_queue import get_napcat_api_response
except ImportError:

    class FallbackLogger:
        def info(self, msg: str):
            print(f"INFO (utils.py): {msg}")

        def warning(self, msg: str):
            print(f"WARNING (utils.py): {msg}")

        def error(self, msg: str):
            print(f"ERROR (utils.py): {msg}")

        def debug(self, msg: str):
            print(f"DEBUG (utils.py): {msg}")

    logger = FallbackLogger()  # type: ignore

    async def get_napcat_api_response(
        echo_id: str, timeout_seconds: Optional[float] = None
    ) -> Any:  # type: ignore
        logger.warning("get_napcat_api_response fallback used in utils.py")
        await asyncio.sleep(1)
        return {"status": "error", "message": "Fallback response from utils.py"}


# --- Napcat API 调用辅助函数 ---
# 注意：所有这些函数都需要一个已建立的 WebSocket 连接 (server_connection) 作为参数


async def _call_napcat_api(
    server_connection: Any,  # 类型应为 websockets.server.WebSocketServerProtocol，但避免循环导入
    action: str,
    params: Dict[str, Any],
    timeout_seconds: float = 15.0,  # 为API调用设置一个默认超时
) -> Optional[Dict[str, Any]]:
    """
    通用的 Napcat API 调用函数。

    Args:
        server_connection: 与 Napcat 客户端的 WebSocket 连接。
        action (str): 要调用的 Napcat action 名称。
        params (Dict[str, Any]): action 所需的参数。
        timeout_seconds (float): 等待响应的超时时间。

    Returns:
        Optional[Dict[str, Any]]: Napcat 返回的响应数据中的 "data" 字段，如果成功且有数据。
                                    如果API调用失败、超时或响应格式不正确，则返回 None。
                                    如果API调用成功但没有 "data" 字段，会返回一个空字典 {}。
    """
    if not server_connection or server_connection.closed:
        logger.error(f"无法调用 Napcat API '{action}': WebSocket 连接不可用或已关闭。")
        return None

    request_echo_id = str(uuid.uuid4())
    payload = {"action": action, "params": params, "echo": request_echo_id}

    try:
        logger.debug(
            f"向 Napcat 发送 API 请求: action='{action}', params={params}, echo='{request_echo_id}'"
        )
        await server_connection.send(json.dumps(payload))

        # 等待响应
        response_data = await get_napcat_api_response(
            request_echo_id, timeout_seconds=timeout_seconds
        )

        if response_data and response_data.get("status") == "ok":
            logger.debug(
                f"Napcat API '{action}' (echo: {request_echo_id}) 调用成功。响应: {response_data.get('data')}"
            )
            # 即使 data 字段不存在，也返回一个空字典表示成功
            return (
                response_data.get("data")
                if response_data.get("data") is not None
                else {}
            )
        else:
            error_msg = (
                response_data.get("message", "未知错误")
                if response_data
                else "无响应或响应格式错误"
            )
            retcode = response_data.get("retcode", "N/A") if response_data else "N/A"
            logger.warning(
                f"Napcat API '{action}' (echo: {request_echo_id}) 调用失败或返回错误状态。Status: {response_data.get('status')}, Retcode: {retcode}, Message: {error_msg}"
            )
            return None

    except asyncio.TimeoutError:
        logger.error(
            f"调用 Napcat API '{action}' (echo: {request_echo_id}) 超时 ({timeout_seconds}s)。"
        )
        return None
    except Exception as e:
        logger.error(
            f"调用 Napcat API '{action}' (echo: {request_echo_id}) 时发生异常: {e}",
            exc_info=True,
        )
        return None


async def napcat_get_self_info(server_connection: Any) -> Optional[Dict[str, Any]]:
    """获取机器人自身信息。"""
    return await _call_napcat_api(server_connection, "get_login_info", {})


async def napcat_get_group_info(
    server_connection: Any, group_id: Union[str, int]
) -> Optional[Dict[str, Any]]:
    """获取群组信息。"""
    return await _call_napcat_api(
        server_connection, "get_group_info", {"group_id": int(group_id)}
    )


async def napcat_get_member_info(
    server_connection: Any,
    group_id: Union[str, int],
    user_id: Union[str, int],
    no_cache: bool = False,
) -> Optional[Dict[str, Any]]:
    """获取群成员信息。"""
    params = {"group_id": int(group_id), "user_id": int(user_id), "no_cache": no_cache}
    return await _call_napcat_api(server_connection, "get_group_member_info", params)


async def napcat_get_stranger_info(
    server_connection: Any, user_id: Union[str, int], no_cache: bool = False
) -> Optional[Dict[str, Any]]:
    """获取陌生人信息。"""
    params = {"user_id": int(user_id), "no_cache": no_cache}
    return await _call_napcat_api(server_connection, "get_stranger_info", params)


async def napcat_get_message_detail(
    server_connection: Any, message_id: Union[str, int]
) -> Optional[Dict[str, Any]]:
    """获取单条消息的详细信息。"""
    # Napcat 的消息 ID 通常是整数，但协议中可能是字符串，这里统一转为字符串以匹配 API 可能的预期
    return await _call_napcat_api(
        server_connection, "get_msg", {"message_id": str(message_id)}
    )


async def napcat_get_forward_msg_content(
    server_connection: Any, forward_msg_id: str
) -> Optional[List[Dict[str, Any]]]:
    """获取合并转发消息的内容。"""
    data = await _call_napcat_api(
        server_connection, "get_forward_msg", {"message_id": forward_msg_id}
    )
    if data and isinstance(data.get("messages"), list):
        return data["messages"]
    elif data:  # 如果返回了 data 但 messages 不是列表或不存在
        logger.warning(
            f"获取合并转发消息 (id: {forward_msg_id}) 内容时，返回的 'messages' 字段格式不正确: {data.get('messages')}"
        )
    return None


async def napcat_get_group_list(
    server_connection: Any,
) -> Optional[List[Dict[str, Any]]]:
    """
    获取机器人加入的群聊列表。
    返回的列表中每个元素包含群 ID、名称等信息。
    """
    return await _call_napcat_api(server_connection, "get_group_list", {})



async def napcat_get_friend_list(
    server_connection: Any,
) -> Optional[List[Dict[str, Any]]]:
    """获取机器人好友列表。"""
    return await _call_napcat_api(server_connection, "get_friend_list", {})


# --- 我新加的几个 API 调用函数，哼 ---


async def napcat_set_group_sign(
    server_connection: Any, group_id: Union[str, int]
) -> Optional[Dict[str, Any]]:
    """群签到。"""
    return await _call_napcat_api(
        server_connection, "set_group_sign", {"group_id": int(group_id)}
    )


async def napcat_set_online_status(
    server_connection: Any, status: int, ext_status: int, battery_status: int
) -> Optional[Dict[str, Any]]:
    """设置在线状态。"""
    params = {
        "status": status,
        "ext_status": ext_status,
        "battery_status": battery_status,
    }
    return await _call_napcat_api(server_connection, "set_online_status", params)


async def napcat_set_qq_avatar(
    server_connection: Any, file: str
) -> Optional[Dict[str, Any]]:
    """设置QQ头像。"""
    return await _call_napcat_api(server_connection, "set_qq_avatar", {"file": file})


async def napcat_get_friend_msg_history(
    server_connection: Any,
    user_id: Union[str, int],
    message_seq: Optional[Union[str, int]] = None,
    count: int = 20,
) -> Optional[List[Dict[str, Any]]]:
    """获取私聊历史记录。"""
    params: Dict[str, Any] = {"user_id": int(user_id), "count": count}
    if message_seq is not None:
        params["message_seq"] = str(message_seq)

    data = await _call_napcat_api(
        server_connection, "get_friend_msg_history", params, timeout_seconds=30
    )
    if data and isinstance(data.get("messages"), list):
        return data["messages"]
    return None


async def napcat_forward_friend_single_msg(
    server_connection: Any, user_id: Union[str, int], message_id: Union[str, int]
) -> Optional[Dict[str, Any]]:
    """转发单条消息给好友，哼。"""
    params = {"user_id": int(user_id), "message_id": int(message_id)}
    return await _call_napcat_api(
        server_connection, "forward_friend_single_msg", params
    )


async def napcat_forward_group_single_msg(
    server_connection: Any, group_id: Union[str, int], message_id: Union[str, int]
) -> Optional[Dict[str, Any]]:
    """转发单条消息到群里，啧。"""
    params = {"group_id": int(group_id), "message_id": int(message_id)}
    return await _call_napcat_api(
        server_connection, "forward_group_single_msg", params
    )


async def napcat_get_group_msg_history(
    server_connection: Any,
    group_id: Union[str, int],
    message_seq: Optional[Union[str, int]] = None,
    count: int = 20,
) -> Optional[List[Dict[str, Any]]]:
    """获取群消息历史记录。"""
    params: Dict[str, Any] = {"group_id": int(group_id), "count": count}
    if message_seq is not None:
        params["message_seq"] = int(message_seq)  # gocq-api 文档说是 int64

    data = await _call_napcat_api(
        server_connection, "get_group_msg_history", params, timeout_seconds=30
    )
    if data and isinstance(data.get("messages"), list):
        return data["messages"]
    return None


# --- 图片处理工具函数 ---


async def get_image_base64_from_url(url: str, timeout: int = 10) -> Optional[str]:
    """异步从 URL 下载图片并返回其 Base64 编码。"""
    # 创建 SSL 上下文以兼容某些服务器
    ssl_context = ssl.create_default_context()
    ssl_context.set_ciphers("DEFAULT@SECLEVEL=1")  # 有时需要降低安全级别以兼容旧服务器

    try:
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=ssl_context)
        ) as session:
            async with session.get(url, timeout=timeout) as response:
                if response.status == 200:
                    image_bytes = await response.read()
                    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
                    logger.debug(f"成功下载并编码图片: {url}")
                    return image_base64
                else:
                    logger.error(f"下载图片失败 (HTTP {response.status}): {url}")
                    return None
    except asyncio.TimeoutError:
        logger.error(f"下载图片超时 (URL: {url}, 超时: {timeout}s)")
        return None
    except Exception as e:
        logger.error(f"下载或处理图片时发生错误 (URL: {url}): {e}", exc_info=True)
        return None


def get_image_format_from_base64(base64_data: str) -> Optional[str]:
    """从 Base64 编码的图像数据中尝试确定图像格式。"""
    try:
        image_bytes = base64.b64decode(base64_data)
        image = Image.open(io.BytesIO(image_bytes))
        return image.format.lower() if image.format else None
    except Exception as e:
        logger.error(f"确定图像格式时发生错误: {e}")
        return None


def convert_image_to_gif_base64(image_base64: str) -> Optional[str]:
    """将 Base64 编码的图片转换为 GIF 格式的 Base64 编码。"""
    try:
        image_bytes = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(image_bytes))

        # 转换为 GIF 格式
        output_buffer = io.BytesIO()
        image.save(output_buffer, format="GIF")
        gif_bytes = output_buffer.getvalue()

        # 转换为 Base64
        gif_base64 = base64.b64encode(gif_bytes).decode("utf-8")
        return gif_base64
    except Exception as e:
        logger.error(f"转换图片为 GIF 格式时发生错误: {e}")
        return None


if __name__ == "__main__":
    # utils.py 的测试通常需要一个运行中的 Napcat 实例和 WebSocket 连接
    # 这里可以放一些不依赖外部连接的单元测试，例如图片格式转换

    async def test_image_conversion():
        logger.info("--- 测试图片处理工具 ---")
        # 你需要一个有效的图片 base64 字符串来进行测试
        # 例如，一个简单的 PNG base64:
        test_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="  # 1x1 red pixel png

        fmt = get_image_format_from_base64(test_png_b64)
        logger.info(f"测试 PNG 的格式: {fmt}")  # 应该输出 png
        assert fmt == "png"

        gif_b64 = convert_image_to_gif_base64(test_png_b64)
        if gif_b64:
            logger.info("PNG 已转换为 GIF (Base64 长度可能变化)")
            gif_fmt = get_image_format_from_base64(gif_b64)
            logger.info(f"转换后的 GIF 格式: {gif_fmt}")  # 应该输出 gif
            assert gif_fmt == "gif"
        else:
            logger.error("PNG 转换为 GIF 失败。")

        # 测试 URL 下载 (需要网络连接)
        # test_url = "https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"
        # logger.info(f"正在尝试从 URL 下载图片: {test_url}")
        # url_img_b64 = await get_image_base64_from_url(test_url)
        # if url_img_b64:
        #     logger.success(f"成功从 URL 下载图片并编码为 Base64 (长度: {len(url_img_b64[:50])}... )")
        #     url_img_fmt = get_image_format_from_base64(url_img_b64)
        #     logger.info(f"URL 图片格式: {url_img_fmt}")
        # else:
        #     logger.error("从 URL 下载图片失败。")

    asyncio.run(test_image_conversion())
