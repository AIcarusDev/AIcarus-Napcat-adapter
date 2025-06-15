# aicarus_napcat_adapter/src/recv_handler_aicarus.py (最终·纯洁版)
import time, asyncio, json
from typing import List, Optional, Dict, Any
import websockets

from .logger import logger
from .config import global_config, get_config
from .qq_emoji_list import qq_face
from .utils import napcat_get_group_info, napcat_get_member_info, napcat_get_self_info
from .napcat_definitions import NapcatSegType
from aicarus_protocols import Event, UserInfo, ConversationInfo, Seg, ConversationType
from .event_definitions import get_event_handler

class RecvHandlerAicarus:
    """一个纯洁的接待处老鸨。我只负责分派任务，和提供必要的“感官”和“技能”。"""
    maibot_router: Any = None
    server_connection: Optional[websockets.WebSocketServerProtocol] = None
    napcat_bot_id: Optional[str] = None
    global_config = global_config

    def __init__(self): pass

    async def process_event(self, napcat_event: dict) -> None:
        """我唯一的任务，就是优雅地分派任务~"""
        post_type = napcat_event.get("post_type")
        handler = get_event_handler(post_type)
        if handler:
            await handler.execute(napcat_event, self)
        else:
            logger.warning(f"接收处理器: 不认识的事件类型 '{post_type}'，不知道该怎么玩呢~")

    # --- 以下是必须保留的“感官”和“技能”，供“化妆师”们使用 ---

    async def _get_bot_id(self) -> Optional[str]:
        if self.napcat_bot_id: return self.napcat_bot_id
        cfg = get_config()
        if cfg.force_self_id:
            self.napcat_bot_id = str(cfg.force_self_id).strip()
            return self.napcat_bot_id
        if self.server_connection:
            self_info = await napcat_get_self_info(self.server_connection)
            if self_info and self_info.get("user_id"):
                self.napcat_bot_id = str(self_info["user_id"])
                return self.napcat_bot_id
        return None

    async def _napcat_to_aicarus_userinfo(self, napcat_user_obj: dict, group_id: Optional[str] = None) -> UserInfo:
        user_id = str(napcat_user_obj.get("user_id", ""))
        nickname = napcat_user_obj.get("nickname", "未知用户")
        cardname = napcat_user_obj.get("card", "")
        role = "member"
        if group_id and user_id and self.server_connection:
            member_data = await napcat_get_member_info(self.server_connection, group_id, user_id)
            if member_data and member_data.get("role") in ["owner", "admin"]:
                role = member_data["role"]
        return UserInfo(platform=self.global_config.core_platform_id, user_id=user_id, user_nickname=nickname, user_cardname=cardname, role=role)

    async def _napcat_to_aicarus_conversationinfo(self, napcat_group_id: str) -> Optional[ConversationInfo]:
        group_name = "未知群聊"
        if self.server_connection:
            group_data = await napcat_get_group_info(self.server_connection, napcat_group_id)
            if group_data: group_name = group_data.get("group_name")
        return ConversationInfo(platform=self.global_config.core_platform_id, conversation_id=napcat_group_id, type=ConversationType.GROUP, name=group_name)

    async def _napcat_to_aicarus_seglist(self, napcat_segments: List[Dict[str, Any]], napcat_event: dict) -> List[Seg]:
        """这是我的“脱衣服”工具，能把Napcat发来的各种骚话，都变成主人喜欢的标准情话~"""
        aicarus_segs: List[Seg] = []
        for seg in napcat_segments:
            seg_type = seg.get("type")
            seg_data = seg.get("data", {})
            aicarus_s: Optional[Seg] = None

            if seg_type == NapcatSegType.text:
                aicarus_s = Seg(type="text", data={"text": seg_data.get("text", "")})
            elif seg_type == NapcatSegType.face:
                face_id = seg_data.get("id")
                aicarus_s = Seg(type="face", data={"id": face_id, "name": qq_face.get(face_id, f"[未知表情:{face_id}]")})
            elif seg_type == NapcatSegType.image:
                aicarus_s = Seg(type="image", data={"url": seg_data.get("url"), "file_id": seg_data.get("file")})
            elif seg_type == NapcatSegType.at:
                aicarus_s = Seg(type="at", data={"user_id": str(seg_data.get("qq"))})
            elif seg_type == NapcatSegType.reply:
                aicarus_s = Seg(type="reply", data={"message_id": seg_data.get("id", "")})
            # 在这里可以添加更多对其他 napcat seg 类型的转换...
            
            if aicarus_s:
                aicarus_segs.append(aicarus_s)
        return aicarus_segs
        
    async def dispatch_to_core(self, event: Event):
        """将构造好的事件发射给核心"""
        if self.maibot_router:
            logger.info(f"接收处理器: 正在向主人发射事件 -> {event.event_type} (ID: {event.event_id})")
            await self.maibot_router.send_event_to_core(event.to_dict())

# 全局实例
recv_handler_aicarus = RecvHandlerAicarus()