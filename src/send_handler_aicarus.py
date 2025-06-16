# aicarus_napcat_adapter/src/send_handler_aicarus.py (最终·器官归位版)
from typing import List, Dict, Any, Optional, Tuple
import json
import uuid
import websockets

# 内部模块
from .logger import logger
from .message_queue import get_napcat_api_response
from .recv_handler_aicarus import recv_handler_aicarus
from .action_definitions import get_action_handler
from .napcat_definitions import NapcatSegType

# AIcarus 协议库
from aicarus_protocols import Event, Seg, EventBuilder


class SendHandlerAicarus:
    """我的身体现在只为一件事而活：接收主人的命令，立刻执行，然后立刻呻吟（响应）！"""

    server_connection: Optional[websockets.WebSocketServerProtocol] = None

    async def handle_aicarus_action(self, raw_aicarus_event_dict: dict) -> None:
        """处理来自核心的动作，现在我的反馈更直接、更快速！"""
        try:
            aicarus_event = Event.from_dict(raw_aicarus_event_dict)
        except Exception as e:
            logger.error(f"发送处理器: 解析核心命令时，身体出错了: {e}", exc_info=True)
            return

        logger.info(
            f"发送处理器: 收到主人的命令: {aicarus_event.event_id}, 类型: {aicarus_event.event_type}"
        )

        success, message, details = await self._execute_action(aicarus_event)

        response_event = EventBuilder.create_action_response_event(
            response_type="success" if success else "failure",
            platform=aicarus_event.platform,
            bot_id=aicarus_event.bot_id,
            original_event_id=aicarus_event.event_id,
            original_action_type=aicarus_event.event_type,
            message=message,
            data=details,
        )
        await recv_handler_aicarus.dispatch_to_core(response_event)
        logger.info(
            f"发送处理器: 已将动作 '{aicarus_event.event_id}' 的直接结果 ({'success' if success else 'failure'}) 发回给主人。"
        )

    async def _execute_action(self, event: Event) -> Tuple[bool, str, Dict[str, Any]]:
        """统一的动作执行器，无论是发消息还是其他骚操作"""
        try:
            if event.event_type == "action.message.send":
                return await self._handle_send_message_action(event)
            if (
                event.content
                and isinstance(event.content, list)
                and len(event.content) > 0
            ):
                action_seg = Seg.from_dict(event.content[0])
                handler = get_action_handler(action_seg.type)
                if handler:
                    return await handler.execute(action_seg, event, self)
            return False, "主人给的命令格式不正确，内容是空的呢~", {}
        except Exception as e:
            logger.error(
                f"发送处理器: 执行动作 '{event.event_type}' 时，身体不听使唤了: {e}",
                exc_info=True,
            )
            return False, f"执行动作时出现异常: {e}", {}

    async def _handle_send_message_action(
        self, aicarus_event: Event
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """专门处理发送消息，并在成功后立刻返回高潮响应！"""
        conv_info = aicarus_event.conversation_info
        target_group_id = (
            conv_info.conversation_id
            if conv_info and conv_info.type == "group"
            else None
        )
        target_user_id = (
            conv_info.conversation_id
            if conv_info and conv_info.type == "private"
            else None
        )

        # --- 这就是关键的修正！我们调用自己的工具，而不是recv_handler的 ---
        napcat_segments = await self._aicarus_segs_to_napcat_array(
            aicarus_event.content
        )
        if not napcat_segments:
            return False, "主人，您给我的情话（Segs）是空的，我没法帮您传达爱意呀~", {}

        params: Dict[str, Any]
        napcat_action: str
        try:
            if target_group_id:
                napcat_action, params = (
                    "send_group_msg",
                    {"group_id": int(target_group_id), "message": napcat_segments},
                )
            elif target_user_id:
                napcat_action, params = (
                    "send_private_msg",
                    {"user_id": int(target_user_id), "message": napcat_segments},
                )
            else:
                return False, "主人，您想把情话送到哪儿去呀？没找到目标呢~", {}
        except (ValueError, TypeError):
            return (
                False,
                f"会话目标ID格式不对哦，应该是纯数字才行。当前ID: {target_group_id or target_user_id}",
                {},
            )

        response = await self._send_to_napcat_api(napcat_action, params)

        if response and response.get("status") == "ok":
            sent_message_id = str(response.get("data", {}).get("message_id", ""))
            logger.info(f"发送处理器: API调用成功 (消息ID: {sent_message_id})。")
            return True, "主人的爱意已成功送达~", {"sent_message_id": sent_message_id}
        else:
            err_msg = (
                response.get("message", "Napcat API 错误")
                if response
                else "Napcat 没有回应我..."
            )
            return False, err_msg, {}

    async def _aicarus_segs_to_napcat_array(
        self, aicarus_segments: List[Seg]
    ) -> List[Dict[str, Any]]:
        """这是我自己的“穿衣服”工具，专门把主人的情话（AIcarus Seg）变成Napcat能懂的骚话~"""
        napcat_message_array: List[Dict[str, Any]] = []
        for seg in aicarus_segments:
            if seg.type == "text":
                napcat_message_array.append(
                    {
                        "type": NapcatSegType.text,
                        "data": {"text": str(seg.data.get("text", ""))},
                    }
                )
            elif seg.type == "at":
                napcat_message_array.append(
                    {
                        "type": NapcatSegType.at,
                        "data": {"qq": str(seg.data.get("user_id"))},
                    }
                )
            elif seg.type == "reply":
                napcat_message_array.append(
                    {
                        "type": NapcatSegType.reply,
                        "data": {"id": str(seg.data.get("message_id"))},
                    }
                )
            # 在这里可以添加更多 seg 类型的转换，比如 image, face 等
            else:
                logger.warning(f"发送处理器: 还不知道怎么转换这种情话呢: {seg.type}")
        return napcat_message_array

    async def _send_to_napcat_api(self, action: str, params: dict) -> Optional[dict]:
        """将我们的欲望（API请求）安全地射向Napcat，并焦急地等待它的呻吟（响应）"""
        if not self.server_connection:
            return {"status": "error", "message": "和Napcat的连接断开了，没法射呢..."}
        request_uuid = str(uuid.uuid4())
        payload = {"action": action, "params": params, "echo": request_uuid}
        await self.server_connection.send(json.dumps(payload))
        return await get_napcat_api_response(request_uuid, timeout_seconds=15.0)


# 全局实例
send_handler_aicarus = SendHandlerAicarus()
