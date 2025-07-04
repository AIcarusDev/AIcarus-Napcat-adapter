# aicarus_napcat_adapter/src/send_handler_aicarus.py (小色猫·最终高潮版)
from typing import List, Dict, Any, Optional, Tuple, Callable
import json
import uuid
import websockets
import asyncio

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

    def __init__(self):
        self.server_connection: Optional[websockets.WebSocketServerProtocol] = None
        self.SEGMENT_CONVERTERS: Dict[
            str, Callable[[Seg], Optional[Dict[str, Any]]]
        ] = {
            "text": self._convert_text_seg,
            "at": self._convert_at_seg,
            "reply": self._convert_reply_seg,
            "quote": self._convert_reply_seg,
            "image": self._convert_image_seg,
            "face": self._convert_face_seg,
            "record": self._convert_record_seg,
            "video": self._convert_video_seg,
            "file": self._convert_file_seg,
            "contact": self._convert_contact_seg,
            "music": self._convert_music_seg,
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
        target_qq = seg.data.get("user_id")
        if not target_qq:
            logger.warning("发送@失败：Seg段中缺少 user_id。")
            return None
        return {
            "type": NapcatSegType.at,
            "data": {"qq": str(target_qq)},
        }

    def _convert_reply_seg(self, seg: Seg) -> Optional[Dict[str, Any]]:
        """处理回复，就是那个 id。"""
        msg_id = seg.data.get("message_id")
        if not msg_id:
            logger.warning("发送回复失败：Seg段中缺少 message_id。")
            return None
        return {
            "type": NapcatSegType.reply,
            "data": {"id": str(msg_id)},
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

    def _convert_media_seg(
        self, seg: Seg, napcat_type: str
    ) -> Optional[Dict[str, Any]]:
        """把语音、视频、文件这种媒体资源都用这个处理，懒得写三遍。"""
        file_source = (
            seg.data.get("file") or seg.data.get("url") or seg.data.get("path")
        )
        if not file_source:
            logger.warning(f"发送{napcat_type}失败：Seg段中缺少 file, url 或 path。")
            return None

        # 视频还可以带个封面，真是麻烦
        data = {"file": file_source}
        if napcat_type == NapcatSegType.video and seg.data.get("thumb"):
            data["thumb"] = seg.data.get("thumb")

        return {"type": napcat_type, "data": data}

    def _convert_record_seg(self, seg: Seg) -> Optional[Dict[str, Any]]:
        """语音，跟图片也差不多嘛。"""
        return self._convert_media_seg(seg, NapcatSegType.record)

    def _convert_video_seg(self, seg: Seg) -> Optional[Dict[str, Any]]:
        """视频也一样，把文件丢过去就行了，真没技术含量。"""
        return self._convert_media_seg(seg, NapcatSegType.video)

    def _convert_file_seg(self, seg: Seg) -> Optional[Dict[str, Any]]:
        """文件也是。"""
        return self._convert_media_seg(seg, "file")  # NapcatSegType里没定义，我直接写了

    def _convert_contact_seg(self, seg: Seg) -> Optional[Dict[str, Any]]:
        """推荐好友或群，哼，你最好把类型和ID给对。"""
        contact_type = seg.data.get("contact_type")  # 'qq' or 'group'
        contact_id = seg.data.get("id")
        if not contact_type or not contact_id:
            logger.warning("发送联系人名片失败：Seg段中缺少 contact_type 或 id。")
            return None
        return {
            "type": NapcatSegType.contact,
            "data": {"type": contact_type, "id": str(contact_id)},
        }

    def _convert_music_seg(self, seg: Seg) -> Optional[Dict[str, Any]]:
        """音乐分享？这个最麻烦了！分两种，你自己看好怎么传数据！"""
        music_type = seg.data.get("music_type")  # 'qq', '163', 'custom' etc.
        if not music_type:
            logger.warning("发送音乐分享失败：Seg段中缺少 music_type。")
            return None

        music_data = {}
        if music_type == "custom":
            # 自定义音乐需要 url, audio, title
            required_keys = ["url", "audio", "title"]
            if not all(key in seg.data for key in required_keys):
                logger.warning(f"发送自定义音乐失败：缺少必要字段 {required_keys}。")
                return None
            music_data = {
                "type": "custom",
                "url": seg.data["url"],
                "audio": seg.data["audio"],
                "title": seg.data["title"],
                "image": seg.data.get("image"),  # 可选
                "singer": seg.data.get("singer"),  # 可选
            }
        else:
            # 平台音乐需要 id
            music_id = seg.data.get("id")
            if not music_id:
                logger.warning(f"发送平台音乐({music_type})失败：缺少 id。")
                return None
            music_data = {"type": music_type, "id": str(music_id)}

        return {"type": NapcatSegType.music, "data": music_data}

    # --- 重构后的“穿衣服”工具，现在清爽多了 ---
    async def _aicarus_segs_to_napcat_array(
        self, aicarus_segments: List[Seg]
    ) -> List[Dict[str, Any]]:
        napcat_message_array: List[Dict[str, Any]] = []
        for seg in aicarus_segments:
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

        # --- ❤❤❤ 构造响应事件时，也要用新的方式！❤❤❤ ---
        # EventBuilder 会从 aicarus_event.get_platform() 解析平台ID
        response_event = EventBuilder.create_action_response_event(
            response_type="success" if success else "failure",
            original_event=aicarus_event,  # 直接把原始事件喂进去
            message=message,
            data=details,
        )
        await recv_handler_aicarus.dispatch_to_core(response_event)
        logger.info(
            f"发送处理器: 已将动作 '{aicarus_event.event_id}' 的直接结果 ({'success' if success else 'failure'}) 发回给主人。"
        )

    async def _execute_action(self, event: Event) -> Tuple[bool, str, Dict[str, Any]]:
        """统一的动作执行器，无论是发消息还是其他骚操作"""

        # --- ❤❤❤ 最终高潮点！从新的event_type中解析出真正的动作别名！❤❤❤ ---
        full_action_type = event.event_type  # e.g., "action.napcat.message.send"

        # 我们只关心 'action.' 后面的部分
        if not full_action_type.startswith("action."):
            error_msg = f"收到了一个非动作类型的事件: {full_action_type}"
            logger.warning(error_msg)
            return False, error_msg, {}

        # 把 "action." 和平台ID都脱掉，露出最里面的动作别名
        # e.g., "action.napcat.message.send" -> "message.send"
        # e.g., "action.napcat.user.poke" -> "user.poke"
        action_alias = ".".join(full_action_type.split(".")[2:])

        logger.info(f"发送处理器正在分发动作，别名: {action_alias}")

        try:
            # 1. 专门为 action.message.send 开一个快速通道，因为它最常用
            if action_alias == "message.send":
                return await self._handle_send_message_action(event)

            # 2. 对于所有其他类型的动作，都统一从 action_definitions.py 里找处理器
            # 我们用新的动作别名去查找
            handler = get_action_handler(action_alias)
            if handler:
                if (
                    event.content
                    and isinstance(event.content, list)
                    and len(event.content) > 0
                ):
                    action_seg = event.content[0]
                    return await handler.execute(action_seg, event, self)
                else:
                    error_msg = f"动作 '{action_alias}' 找到了处理器，但事件内容为空，无法执行。"
                    logger.error(error_msg)
                    return False, error_msg, {}

            # 3. 如果找不到任何处理器
            error_msg = f"未知的动作别名 '{action_alias}'，我不知道该怎么做。"
            logger.warning(error_msg)
            return False, error_msg, {}

        except Exception as e:
            logger.error(
                f"执行动作 '{action_alias}' 时，身体不听使唤了: {e}", exc_info=True
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
                f"会话目标ID格式不对哦。当前ID: {target_group_id or target_user_id}",
                {},
            )

        response = await self._send_to_napcat_api(napcat_action, params)

        if response and response.get("status") == "ok":
            sent_message_id = str(response.get("data", {}).get("message_id", ""))
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
        try:
            return await get_napcat_api_response(request_uuid, timeout_seconds=30.0)
        except asyncio.TimeoutError:
            logger.warning(f"调用 Napcat API '{action}' 超时。")
            return {"status": "error", "message": f"调用 Napcat API '{action}' 超时"}


# 全局实例
send_handler_aicarus = SendHandlerAicarus()
