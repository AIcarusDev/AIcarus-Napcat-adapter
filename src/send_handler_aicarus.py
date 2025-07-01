# aicarus_napcat_adapter/src/send_handler_aicarus.py (被小懒猫重构并注入新功能的版本)
from typing import List, Dict, Any, Optional, Tuple, Callable
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

    # --- 小懒猫的重构：把消息段转换的逻辑抽出来，用字典管理，哼 ---
    def __init__(self):
        """
        初始化我的身体，准备好接收主人的命令。
        现在我有一个“
        工具箱”，里面装满了各种转换工具，可以把主人的情话（Segs）转换成Napcat能懂的格式。
        """
        # 这个字典就是我的“工具箱”，每种情话（Seg）都有专门的工具来打磨
        self.SEGMENT_CONVERTERS: Dict[str, Callable[[Seg], Optional[Dict[str, Any]]]] = {
            "text": self._convert_text_seg,
            "at": self._convert_at_seg,
            "reply": self._convert_reply_seg,
            "quote": self._convert_reply_seg, # 兼容 quote 类型
            "image": self._convert_image_seg,
            "face": self._convert_face_seg,
        }

    # --- 这是各种“打磨工具”的具体实现 ---

    def _convert_text_seg(self, seg: Seg) -> Optional[Dict[str, Any]]:
        """处理文字，最简单了，没劲。"""
        return {
            "type": NapcatSegType.text,
            "data": {"text": str(seg.data.get("text", ""))},
        }

    def _convert_at_seg(self, seg: Seg) -> Optional[Dict[str, Any]]:
        """处理@，也简单。"""
        return {
            "type": NapcatSegType.at,
            "data": {"qq": str(seg.data.get("user_id"))},
        }

    def _convert_reply_seg(self, seg: Seg) -> Optional[Dict[str, Any]]:
        """处理回复，就是那个 id。"""
        return {
            "type": NapcatSegType.reply,
            "data": {"id": str(seg.data.get("message_id"))},
        }

    def _convert_image_seg(self, seg: Seg) -> Optional[Dict[str, Any]]:
        """
        哼，处理图片，麻烦死了。
        AIcarus协议里的file_id, url, base64，我直接丢给Napcat的file字段，让它自己头疼去。
        """
        file_source = (
            seg.data.get("file")
            or seg.data.get("file_id")
            or seg.data.get("url")
            or seg.data.get("base64")
        )
        if not file_source:
            logger.warning("发送图片失败：Seg段中缺少 file, file_id, url 或 base64。")
            return None
        return {"type": NapcatSegType.image, "data": {"file": file_source}}

    def _convert_face_seg(self, seg: Seg) -> Optional[Dict[str, Any]]:
        """QQ表情，就是个数字ID，小意思。"""
        face_id = seg.data.get("id")
        if face_id is None:
            logger.warning("发送表情失败：Seg段中缺少 id。")
            return None
        return {"type": NapcatSegType.face, "data": {"id": str(face_id)}}

    # --- 重构后的“穿衣服”工具，现在清爽多了 ---
    async def _aicarus_segs_to_napcat_array(
        self, aicarus_segments: List[Seg]
    ) -> List[Dict[str, Any]]:
        """
        这是我自己的“穿衣服”工具，现在懂得用我的“工具箱”了，哼。
        """
        napcat_message_array: List[Dict[str, Any]] = []
        for seg in aicarus_segments:
            # 从我的“工具箱”里找对应的转换方法
            converter = self.SEGMENT_CONVERTERS.get(seg.type)
            if converter:
                napcat_seg = converter(seg)
                if napcat_seg:
                    napcat_message_array.append(napcat_seg)
            else:
                logger.warning(f"发送处理器: 还不知道怎么转换这种情话呢: {seg.type}")
        return napcat_message_array


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

        action_type = event.event_type
        logger.info(f"发送处理器正在分发动作，类型: {action_type}")

        try:
            # 1. 专门为 action.message.send 开一个快速通道，因为它最常用
            if action_type == "action.message.send":
                return await self._handle_send_message_action(event)

            # 2. 对于所有其他类型的动作，都统一从 action_definitions.py 里找处理器
            handler = get_action_handler(action_type)
            if handler:
                # 注意：handler 的 execute 方法需要 action_seg，我们从 content 里取第一个
                # 这是一个约定：所有非发消息的动作，其核心参数都在第一个 seg 里
                if (
                    event.content
                    and isinstance(event.content, list)
                    and len(event.content) > 0
                ):
                    action_seg = event.content[0]
                    return await handler.execute(action_seg, event, self)
                else:
                    # 如果有 handler 但没有 content，说明事件构造有问题
                    error_msg = (
                        f"动作 '{action_type}' 找到了处理器，但事件内容为空，无法执行。"
                    )
                    logger.error(error_msg)
                    return False, error_msg, {}

            # 3. 如果找不到任何处理器
            error_msg = f"未知的动作类型 '{action_type}'，我不知道该怎么做。"
            logger.warning(error_msg)
            return False, error_msg, {}

        except Exception as e:
            logger.error(
                f"执行动作 '{action_type}' 时，身体不听使唤了: {e}", exc_info=True
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

        if (
            target_user_id
            and isinstance(target_user_id, str)
            and target_user_id.startswith("private_")
        ):
            target_user_id = target_user_id.replace("private_", "")

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
            logger.info(
                f"发送处理器: API调用成功 (消息ID: {sent_message_id})。已登记用于回显识别。"
            )
            return True, "主人的爱意已成功送达~", {"sent_message_id": sent_message_id}
        else:
            err_msg = (
                response.get("message", "Napcat API 错误")
                if response
                else "Napcat 没有回应我..."
            )
            return False, err_msg, {}


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
