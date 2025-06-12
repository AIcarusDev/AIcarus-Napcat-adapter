# AIcarus Napcat Adapter - Receive Handler for Protocol v1.4.0
# aicarus_napcat_adapter/src/recv_handler_aicarus.py
import time
import asyncio
import json
from typing import List, Optional, Dict, Any
import uuid
import websockets

# 项目内部模块
from .logger import logger
from .config import global_config
from .qq_emoji_list import qq_face

# 修正 utils.py 的导入
from .utils import (
    napcat_get_group_info,
    napcat_get_member_info,
    napcat_get_self_info,
    napcat_get_forward_msg_content,
    get_image_base64_from_url,  # 添加图片处理工具
)
from .napcat_definitions import (
    MetaEventType,
    MessageType,
    NoticeType,
    NapcatSegType,
)

# AIcarus 协议库 v1.4.0
from aicarus_protocols import (
    Event,
    UserInfo,
    ConversationInfo,
    Seg,
    ConversationType,
)


class RecvHandlerAicarus:
    maibot_router: Any  # Type hint for Router, will be set by main
    server_connection: Optional[websockets.WebSocketServerProtocol] = None
    last_heart_beat: float = 0.0
    napcat_bot_id: Optional[str] = None

    def __init__(self):
        self.maibot_router = None # 明确初始化 maibot_router
        cfg = global_config
        self.interval = cfg.napcat_heartbeat_interval_seconds

    async def _get_bot_id(self) -> Optional[str]:
        """获取并缓存机器人自身的ID"""
        if self.napcat_bot_id:
            return self.napcat_bot_id

        if self.server_connection:
            self_info = await napcat_get_self_info(self.server_connection)
            if self_info and self_info.get("user_id"):
                self.napcat_bot_id = str(self_info.get("user_id"))
                return self.napcat_bot_id
        return None

    async def _napcat_to_aicarus_userinfo(
        self, napcat_user_obj: dict, group_id: Optional[str] = None
    ) -> UserInfo:
        """将 Napcat 用户对象转换为 AIcarus UserInfo"""
        user_id = str(napcat_user_obj.get("user_id", ""))
        nickname = napcat_user_obj.get("nickname")
        cardname = napcat_user_obj.get("card")

        permission_level = None
        role = None
        title = None

        if group_id and user_id and self.server_connection:
            member_data = await napcat_get_member_info(
                self.server_connection, group_id, user_id
            )
            if member_data:
                cardname = member_data.get("card") or cardname
                nickname = member_data.get("nickname") or nickname
                title = member_data.get("title")
                napcat_role = member_data.get("role")
                if napcat_role == "owner":
                    permission_level = "owner"
                    role = "owner"
                elif napcat_role == "admin":
                    permission_level = "admin"
                    role = "admin"
                else:
                    permission_level = "member"
                    role = "member"

        cfg = global_config
        return UserInfo(
            platform=cfg.core_platform_id,
            user_id=user_id,
            user_nickname=nickname,
            user_cardname=cardname,
            user_titlename=title,
            permission_level=permission_level,
            role=role,
            additional_data=napcat_user_obj.get("additional_data", {}),
        )

    async def _napcat_to_aicarus_conversationinfo(
        self, napcat_group_id: str
    ) -> Optional[ConversationInfo]:
        """将 Napcat 群ID 转换为 AIcarus ConversationInfo"""
        if not self.server_connection:
            cfg = global_config
            return ConversationInfo(
                platform=cfg.core_platform_id,
                conversation_id=napcat_group_id,
                type=ConversationType.GROUP,
            )

        group_data = await napcat_get_group_info(
            self.server_connection, napcat_group_id
        )
        group_name = group_data.get("group_name") if group_data else None
        cfg = global_config
        return ConversationInfo(
            platform=cfg.core_platform_id,
            conversation_id=napcat_group_id,
            type=ConversationType.GROUP,
            name=group_name,
        )

    async def handle_meta_event(self, napcat_event: dict) -> None:
        """处理元事件，转换为v1.4.0协议"""
        event_type_raw = napcat_event.get("meta_event_type")
        bot_id = (
            str(napcat_event.get("self_id"))
            or await self._get_bot_id()
            or "unknown_bot"
        )
        cfg = global_config

        # 构建元事件内容
        meta_seg_data: Dict[str, Any] = {}
        event_type: str = "meta.unknown"

        if event_type_raw == MetaEventType.lifecycle:
            sub_type = napcat_event.get("sub_type")
            event_type = f"meta.lifecycle.{sub_type}"
            meta_seg_data = {
                "adapter_version": "1.0.0",
                "platform_api_version": "napcat",
            }
            if sub_type == MetaEventType.Lifecycle.connect:
                self.napcat_bot_id = bot_id
                self.last_heart_beat = time.time()
                logger.info(f"AIcarus Adapter: Bot {bot_id} connected to Napcat.")
                asyncio.create_task(self.check_heartbeat(bot_id))

        elif event_type_raw == MetaEventType.heartbeat:
            event_type = "meta.heartbeat"
            status_obj = napcat_event.get("status", {})
            meta_seg_data = {
                "status_object": status_obj,
                "interval_ms": napcat_event.get("interval"),
                "is_online": status_obj.get("online", False)
                and status_obj.get("good", False),
            }
            if meta_seg_data["is_online"]:
                self.last_heart_beat = time.time()
                if napcat_event.get("interval"):
                    self.interval = napcat_event.get("interval") / 1000.0
            else:
                logger.warning(
                    f"AIcarus Adapter: Bot {bot_id} Napcat heartbeat status is not good."
                )
        else:
            logger.warning(
                f"AIcarus Adapter: Unknown Napcat meta_event_type: {event_type_raw}"
            )
            event_type = f"meta.napcat.unknown_{event_type_raw}"
            meta_seg_data = {"raw_napcat_event": napcat_event}

        # 创建v1.4.0事件
        content_seg = Seg(type=event_type, data=meta_seg_data)

        meta_event = Event(
            event_id=f"meta_{event_type_raw}_{uuid.uuid4()}",
            event_type=event_type,
            time=napcat_event.get("time", time.time()) * 1000.0,
            platform=cfg.core_platform_id,
            bot_id=bot_id,
            user_info=None,
            conversation_info=None,
            content=[content_seg],
            raw_data=json.dumps(napcat_event),
        )

        await self.dispatch_to_core(meta_event)

    async def check_heartbeat(self, bot_id: str) -> None:
        """检查心跳超时"""
        cfg = global_config
        while True:
            await asyncio.sleep(self.interval)
            if time.time() - self.last_heart_beat > self.interval + 5:
                logger.warning(
                    f"AIcarus Adapter: Bot {bot_id} Napcat connection might be lost (heartbeat timeout)."
                )

                # 创建断开连接事件
                disconnect_seg = Seg(
                    type="meta.lifecycle.disconnect",
                    data={"reason": "heartbeat_timeout", "adapter_version": "1.0.0"},
                )

                disconnect_event = Event(
                    event_id=f"meta_disconnect_{uuid.uuid4()}",
                    event_type="meta.lifecycle.disconnect",
                    time=time.time() * 1000.0,
                    platform=cfg.core_platform_id,
                    bot_id=bot_id,
                    user_info=None,
                    conversation_info=None,
                    content=[disconnect_seg],
                )

                await self.dispatch_to_core(disconnect_event)
                break
            else:
                logger.debug(f"AIcarus Adapter: Bot {bot_id} heartbeat check passed.")

    async def handle_message_event(self, napcat_event: dict) -> None:
        """处理消息事件，转换为v1.4.0协议"""
        bot_id = (
            str(napcat_event.get("self_id"))
            or await self._get_bot_id()
            or "unknown_bot"
        )
        napcat_message_type = napcat_event.get("message_type")
        napcat_sub_type = napcat_event.get("sub_type")
        napcat_message_id = str(napcat_event.get("message_id", ""))

        aicarus_user_info: Optional[UserInfo] = None
        aicarus_conversation_info: Optional[ConversationInfo] = None

        napcat_sender = napcat_event.get("sender", {})
        cfg = global_config

        # 构建事件类型
        if napcat_message_type == MessageType.private:
            aicarus_user_info = await self._napcat_to_aicarus_userinfo(napcat_sender)
            if napcat_sub_type == MessageType.Private.friend:
                event_type = "message.private.friend"  # 使用字符串
            elif napcat_sub_type == MessageType.Private.group:
                event_type = "message.private.temporary"  # 使用字符串
                # 对于群临时会话，创建群会话信息
                temp_group_id = str(napcat_event.get("group_id")) or str(
                    napcat_sender.get("group_id", "")
                )
                if temp_group_id:
                    aicarus_conversation_info = (
                        await self._napcat_to_aicarus_conversationinfo(temp_group_id)
                    )
                else:
                    logger.warning(
                        "AIcarus Adapter: Group temporary chat missing group_id."
                    )
            else:
                event_type = "message.private.other"

        elif napcat_message_type == MessageType.group:
            group_id = str(napcat_event.get("group_id", ""))
            aicarus_user_info = await self._napcat_to_aicarus_userinfo(
                napcat_sender, group_id=group_id
            )
            aicarus_conversation_info = await self._napcat_to_aicarus_conversationinfo(
                group_id
            )

            if napcat_sub_type == MessageType.Group.normal:
                event_type = "message.group.normal"  # 使用字符串
            elif napcat_sub_type == MessageType.Group.anonymous:
                event_type = "message.group.anonymous"  # 使用字符串
            else:
                event_type = "message.group.other"
        else:
            logger.warning(
                f"AIcarus Adapter: Unknown Napcat message_type: {napcat_message_type}"
            )
            return

        # 构建消息内容
        content_segs = []

        # 添加消息元数据 - 修复 SegBuilder 使用
        metadata_seg = Seg(
            type="message_metadata",
            data={
                "message_id": napcat_message_id,
                "font": str(napcat_event.get("font"))
                if napcat_event.get("font") is not None
                else None,
            },
        )
        if napcat_sub_type == MessageType.Group.anonymous and napcat_event.get(
            "anonymous"
        ):
            metadata_seg.data["anonymity_info"] = napcat_event.get("anonymous")

        content_segs.append(metadata_seg)

        # 转换消息段
        message_segs = await self._napcat_to_aicarus_seglist(
            napcat_event.get("message", []), napcat_event
        )
        if not message_segs:
            logger.warning(
                f"AIcarus Adapter: Message {napcat_message_id} content is empty or unparseable, skipping."
            )
            return

        content_segs.extend(message_segs)

        # 创建v1.4.0消息事件
        message_event = Event(
            event_id=f"message_{napcat_message_id}_{uuid.uuid4()}",
            event_type=event_type,
            time=napcat_event.get("time", time.time()) * 1000.0,
            platform=cfg.core_platform_id,
            bot_id=bot_id,
            user_info=aicarus_user_info,
            conversation_info=aicarus_conversation_info,
            content=content_segs,
            raw_data=json.dumps(napcat_event),
        )

        await self.dispatch_to_core(message_event)

    async def _napcat_to_aicarus_seglist(
        self, napcat_segments: List[Dict[str, Any]], napcat_event: dict
    ) -> List[Seg]:
        """将 Napcat 消息段转换为 AIcarus Seg 列表"""
        aicarus_segs: List[Seg] = []

        for seg in napcat_segments:
            seg_type = seg.get("type")
            seg_data = seg.get("data", {})
            aicarus_s: Optional[Seg] = None

            if seg_type == NapcatSegType.text:
                aicarus_s = Seg(type="text", data={"text": seg_data.get("text", "")})

            elif seg_type == NapcatSegType.face:
                face_id = seg_data.get("id")
                face_name = qq_face.get(face_id, f"[未知表情:{face_id}]")
                aicarus_s = Seg(type="face", data={"id": face_id, "name": face_name})

            elif seg_type == NapcatSegType.image:
                # 处理图片：下载并转换为base64
                image_url = seg_data.get("url")
                image_base64 = None

                if image_url:
                    try:
                        image_base64 = await get_image_base64_from_url(image_url)
                        if image_base64:
                            logger.debug(f"成功下载并转换图片为base64: {image_url}")
                        else:
                            logger.warning(f"下载图片失败，将使用原始URL: {image_url}")
                    except Exception as e:
                        logger.error(f"处理图片时发生错误: {e}")

                aicarus_s = Seg(
                    type="image",
                    data={
                        "url": image_url,
                        "file_id": seg_data.get("file"),
                        "file_size": seg_data.get("file_size"),
                        "file_unique": seg_data.get("file_unique"),
                        "base64": image_base64,  # 添加base64字段
                    },
                )

            elif seg_type == NapcatSegType.at:
                display_name = None
                qq_num = seg_data.get("qq")
                if qq_num and qq_num != "all":
                    display_name = f"@{qq_num}"
                elif qq_num == "all":
                    display_name = "@全体成员"

                aicarus_s = Seg(
                    type="at",
                    data={
                        "user_id": str(qq_num) if qq_num else "",
                        "display_name": display_name,
                    },
                )

            elif seg_type == NapcatSegType.reply:
                aicarus_s = Seg(
                    type="reply", data={"message_id": seg_data.get("id", "")}
                )

            elif seg_type == NapcatSegType.record:
                aicarus_s = Seg(
                    type="record",
                    data={
                        "file": seg_data.get("file"),
                        "url": seg_data.get("url"),
                        "magic": seg_data.get("magic"),
                    },
                )

            elif seg_type == NapcatSegType.video:
                aicarus_s = Seg(
                    type="video",
                    data={"file": seg_data.get("file"), "url": seg_data.get("url")},
                )

            elif seg_type == NapcatSegType.forward:
                forward_id = seg_data.get("id")
                if forward_id and self.server_connection:
                    try:
                        forward_content = await napcat_get_forward_msg_content(
                            self.server_connection, forward_id
                        )
                        if forward_content and isinstance(forward_content, list):
                            aicarus_s = Seg(
                                type="forward",
                                data={"id": forward_id, "content": forward_content},
                            )
                        else:
                            aicarus_s = Seg(
                                type="text", data={"text": "[合并转发消息]"}
                            )
                    except Exception as e:
                        logger.warning(f"Failed to get forward message content: {e}")
                        aicarus_s = Seg(type="text", data={"text": "[合并转发消息]"})
                else:
                    aicarus_s = Seg(type="text", data={"text": "[合并转发消息]"})

            elif seg_type == NapcatSegType.json:
                aicarus_s = Seg(
                    type="json_card", data={"content": seg_data.get("data", "{}")}
                )

            elif seg_type == NapcatSegType.xml:
                aicarus_s = Seg(
                    type="xml_card", data={"content": seg_data.get("data", "")}
                )

            elif seg_type == NapcatSegType.share:
                aicarus_s = Seg(
                    type="share",
                    data={
                        "url": seg_data.get("url", ""),
                        "title": seg_data.get("title", ""),
                        "content": seg_data.get("content", ""),
                        "image_url": seg_data.get("image", ""),
                    },
                )
            else:
                logger.warning(
                    f"AIcarus Adapter: Unknown Napcat segment type: {seg_type}"
                )
                aicarus_s = Seg(
                    type="unknown",
                    data={"napcat_type": seg_type, "napcat_data": seg_data},
                )

            if aicarus_s:
                aicarus_segs.append(aicarus_s)

        return aicarus_segs

    async def handle_notice_event(self, napcat_event: dict) -> None:
        """处理通知事件，转换为v1.4.0协议"""
        notice_type = napcat_event.get("notice_type")
        bot_id = (
            str(napcat_event.get("self_id"))
            or await self._get_bot_id()
            or "unknown_bot"
        )
        cfg = global_config

        # 构建通知事件类型和数据
        event_type = f"notice.{notice_type}"
        notice_data: Dict[str, Any] = {}

        user_info: Optional[UserInfo] = None
        conversation_info: Optional[ConversationInfo] = None

        if notice_type == NoticeType.group_upload:
            event_type = "notice.conversation.file_upload"
            group_id = str(napcat_event.get("group_id", ""))
            user_id = str(napcat_event.get("user_id", ""))

            if group_id:
                conversation_info = await self._napcat_to_aicarus_conversationinfo(
                    group_id
                )
            if user_id:
                user_info = await self._napcat_to_aicarus_userinfo({"user_id": user_id})

            file_info = napcat_event.get("file", {})
            notice_data = {
                "file_info": {
                    "id": file_info.get("id"),
                    "name": file_info.get("name"),
                    "size": file_info.get("size"),
                    "busid": file_info.get("busid"),
                },
                "uploader_user_info": user_info.to_dict() if user_info else None,
            }

        elif notice_type == NoticeType.group_admin:
            event_type = "notice.conversation.admin_change"
            group_id = str(napcat_event.get("group_id", ""))
            user_id = str(napcat_event.get("user_id", ""))
            sub_type = napcat_event.get("sub_type")

            if group_id:
                conversation_info = await self._napcat_to_aicarus_conversationinfo(
                    group_id
                )
            if user_id:
                user_info = await self._napcat_to_aicarus_userinfo({"user_id": user_id})

            notice_data = {
                "target_user_info": user_info.to_dict() if user_info else None,
                "action_type": "set" if sub_type == "set" else "unset",
            }

        elif notice_type == NoticeType.group_decrease:
            event_type = "notice.conversation.member_decrease"
            group_id = str(napcat_event.get("group_id", ""))
            user_id = str(napcat_event.get("user_id", ""))
            operator_id = str(napcat_event.get("operator_id", ""))
            sub_type = napcat_event.get("sub_type")

            if group_id:
                conversation_info = await self._napcat_to_aicarus_conversationinfo(
                    group_id
                )
            if user_id:
                user_info = await self._napcat_to_aicarus_userinfo({"user_id": user_id})

            operator_user_info = None
            if operator_id and operator_id != user_id:
                operator_user_info = await self._napcat_to_aicarus_userinfo(
                    {"user_id": operator_id}
                )

            notice_data = {
                "operator_user_info": operator_user_info.to_dict()
                if operator_user_info
                else None,
                "leave_type": sub_type,
            }

        elif notice_type == NoticeType.group_increase:
            event_type = "notice.conversation.member_increase"
            group_id = str(napcat_event.get("group_id", ""))
            user_id = str(napcat_event.get("user_id", ""))
            operator_id = str(napcat_event.get("operator_id", ""))
            sub_type = napcat_event.get("sub_type")

            if group_id:
                conversation_info = await self._napcat_to_aicarus_conversationinfo(
                    group_id
                )
            if user_id:
                user_info = await self._napcat_to_aicarus_userinfo({"user_id": user_id})

            operator_user_info = None
            if operator_id and operator_id != user_id:
                operator_user_info = await self._napcat_to_aicarus_userinfo(
                    {"user_id": operator_id}
                )

            notice_data = {
                "operator_user_info": operator_user_info.to_dict()
                if operator_user_info
                else None,
                "join_type": sub_type,
            }

        elif notice_type == NoticeType.group_ban:
            event_type = "notice.conversation.member_ban"
            group_id = str(napcat_event.get("group_id", ""))
            user_id = str(napcat_event.get("user_id", ""))
            operator_id = str(napcat_event.get("operator_id", ""))
            duration = napcat_event.get("duration", 0)

            if group_id:
                conversation_info = await self._napcat_to_aicarus_conversationinfo(
                    group_id
                )
            if user_id:
                user_info = await self._napcat_to_aicarus_userinfo({"user_id": user_id})

            operator_user_info = None
            if operator_id:
                operator_user_info = await self._napcat_to_aicarus_userinfo(
                    {"user_id": operator_id}
                )

            notice_data = {
                "target_user_info": user_info.to_dict() if user_info else None,
                "operator_user_info": operator_user_info.to_dict()
                if operator_user_info
                else None,
                "duration_seconds": duration,
                "ban_type": "ban" if duration > 0 else "lift_ban",
            }

        elif notice_type == NoticeType.group_recall:
            event_type = "notice.message.recalled"
            group_id = str(napcat_event.get("group_id", ""))
            user_id = str(napcat_event.get("user_id", ""))
            operator_id = str(napcat_event.get("operator_id", ""))
            message_id = str(napcat_event.get("message_id", ""))

            if group_id:
                conversation_info = await self._napcat_to_aicarus_conversationinfo(
                    group_id
                )
            if user_id:
                user_info = await self._napcat_to_aicarus_userinfo({"user_id": user_id})

            operator_user_info = None
            if operator_id and operator_id != user_id:
                operator_user_info = await self._napcat_to_aicarus_userinfo(
                    {"user_id": operator_id}
                )

            notice_data = {
                "recalled_message_id": message_id,
                "recalled_message_sender_info": user_info.to_dict()
                if user_info
                else None,
                "operator_user_info": operator_user_info.to_dict()
                if operator_user_info
                else None,
            }

        elif notice_type == NoticeType.friend_recall:
            event_type = "notice.message.recalled"
            user_id = str(napcat_event.get("user_id", ""))
            message_id = str(napcat_event.get("message_id", ""))

            if user_id:
                user_info = await self._napcat_to_aicarus_userinfo({"user_id": user_id})

            notice_data = {
                "recalled_message_id": message_id,
                "friend_user_info": user_info.to_dict() if user_info else None,
                "operator_user_info": user_info.to_dict() if user_info else None,
            }

        elif notice_type == NoticeType.notify:
            sub_type = napcat_event.get("sub_type")
            if sub_type == "poke":
                event_type = "notice.user.poke"
                sender_id = str(napcat_event.get("sender_id", ""))
                target_id = str(napcat_event.get("target_id", ""))
                group_id = napcat_event.get("group_id")

                if group_id:
                    conversation_info = await self._napcat_to_aicarus_conversationinfo(
                        str(group_id)
                    )
                if sender_id:
                    user_info = await self._napcat_to_aicarus_userinfo(
                        {"user_id": sender_id}
                    )

                target_user_info = None
                if target_id:
                    target_user_info = await self._napcat_to_aicarus_userinfo(
                        {"user_id": target_id}
                    )

                notice_data = {
                    "sender_user_info": user_info.to_dict() if user_info else None,
                    "target_user_info": target_user_info.to_dict()
                    if target_user_info
                    else None,
                    "context_type": "group" if group_id else "private",
                }
            else:
                # 其他notify子类型
                event_type = f"notice.notify.{sub_type}"
                notice_data = napcat_event
        else:
            logger.warning(f"AIcarus Adapter: Unknown notice_type: {notice_type}")
            event_type = f"notice.unknown.{notice_type}"
            notice_data = napcat_event

        # 创建v1.4.0通知事件
        content_seg = Seg(type=event_type, data=notice_data)

        notice_event = Event(
            event_id=f"notice_{notice_type}_{uuid.uuid4()}",
            event_type=event_type,
            time=napcat_event.get("time", time.time()) * 1000.0,
            platform=cfg.core_platform_id,
            bot_id=bot_id,
            user_info=user_info,
            conversation_info=conversation_info,
            content=[content_seg],
            raw_data=json.dumps(napcat_event),
        )

        await self.dispatch_to_core(notice_event)

    async def handle_request_event(self, napcat_event: dict) -> None:
        """处理请求事件，转换为v1.4.0协议"""
        request_type = napcat_event.get("request_type")
        bot_id = (
            str(napcat_event.get("self_id"))
            or await self._get_bot_id()
            or "unknown_bot"
        )
        cfg = global_config

        # 构建请求事件类型和数据
        event_type = f"request.{request_type}"
        request_data: Dict[str, Any] = {}

        user_info: Optional[UserInfo] = None
        conversation_info: Optional[ConversationInfo] = None

        if request_type == "friend":
            event_type = "request.friend.add"
            user_id = str(napcat_event.get("user_id", ""))

            if user_id:
                user_info = await self._napcat_to_aicarus_userinfo({"user_id": user_id})

            request_data = {
                "comment": napcat_event.get("comment", ""),
                "request_flag": napcat_event.get("flag", ""),
            }

        elif request_type == "group":
            sub_type = napcat_event.get("sub_type")
            group_id = str(napcat_event.get("group_id", ""))
            user_id = str(napcat_event.get("user_id", ""))

            if group_id:
                conversation_info = await self._napcat_to_aicarus_conversationinfo(
                    group_id
                )
            if user_id:
                user_info = await self._napcat_to_aicarus_userinfo({"user_id": user_id})

            if sub_type == "add":
                event_type = "request.conversation.join_application"
            elif sub_type == "invite":
                event_type = "request.conversation.invitation"
            else:
                event_type = f"request.group.{sub_type}"

            request_data = {
                "comment": napcat_event.get("comment", ""),
                "request_flag": napcat_event.get("flag", ""),
                "sub_type": sub_type,
            }
        else:
            logger.warning(f"AIcarus Adapter: Unknown request_type: {request_type}")
            event_type = f"request.unknown.{request_type}"
            request_data = napcat_event

        # 创建v1.4.0请求事件
        content_seg = Seg(type=event_type, data=request_data)

        request_event = Event(
            event_id=f"request_{request_type}_{uuid.uuid4()}",
            event_type=event_type,
            time=napcat_event.get("time", time.time()) * 1000.0,
            platform=cfg.core_platform_id,
            bot_id=bot_id,
            user_info=user_info,
            conversation_info=conversation_info,
            content=[content_seg],
            raw_data=json.dumps(napcat_event),
        )

        await self.dispatch_to_core(request_event)

    async def dispatch_to_core(self, event: Event):
        """将事件发送到Core"""
        if self.maibot_router:
            try:
                # 序列化事件为字典
                serialized_event = event.to_dict()
                logger.debug(f"Dispatching event to Core: {serialized_event}")

                await self.maibot_router.send_event_to_core(serialized_event)
                logger.debug(
                    f"AIcarus Adapter: Dispatched event to Core: {event.event_type} / {event.event_id}"
                )
            except Exception as e:
                logger.error(
                    f"AIcarus Adapter: Failed to send event to Core via router: {e}"
                )
                logger.error(f"Event content: {event.to_dict()}")
        else:
            logger.error(
                "AIcarus Adapter: maibot_router is not set, cannot dispatch to Core."
            )

    async def recv_handler_aicarus(
        self, websocket: websockets.WebSocketServerProtocol, path: str
    ):
        """接收和处理来自Napcat的WebSocket消息"""
        self.server_connection = websocket
        logger.info(
            f"AIcarus Adapter: Napcat connected from {websocket.remote_address}"
        )

        try:
            async for raw_message in websocket:
                try:
                    napcat_event = json.loads(raw_message)
                    logger.debug(f"AIcarus Adapter: Received event: {napcat_event}")

                    post_type = napcat_event.get("post_type")
                    if post_type == "message":
                        await self.handle_message_event(napcat_event)
                    elif post_type == "notice":
                        await self.handle_notice_event(napcat_event)
                    elif post_type == "request":
                        await self.handle_request_event(napcat_event)
                    elif post_type == "meta_event":
                        await self.handle_meta_event(napcat_event)
                    else:
                        logger.warning(
                            f"AIcarus Adapter: Unknown post_type: {post_type}"
                        )

                except json.JSONDecodeError as e:
                    logger.error(f"AIcarus Adapter: JSON decode error: {e}")
                except Exception as e:
                    logger.error(
                        f"AIcarus Adapter: Error processing event: {e}", exc_info=True
                    )

        except websockets.exceptions.ConnectionClosed:
            logger.info("AIcarus Adapter: Napcat WebSocket connection closed")
        except Exception as e:
            logger.error(f"AIcarus Adapter: WebSocket error: {e}", exc_info=True)
        finally:
            self.server_connection = None
            logger.info("AIcarus Adapter: Cleaned up Napcat connection")

# 全局实例，以便其他模块导入和使用
recv_handler_aicarus = RecvHandlerAicarus()
