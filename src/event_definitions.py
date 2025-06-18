# aicarus_napcat_adapter/src/event_definitions.py (小色猫·调教版)
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, TYPE_CHECKING
import uuid
import json
import time
import asyncio

from aicarus_protocols import (
    Event,
    UserInfo,
    ConversationInfo,
    Seg,
    EventBuilder,
    ConversationType,
)
from .napcat_definitions import MetaEventType, MessageType, NoticeType
from .logger import logger

if TYPE_CHECKING:
    from .recv_handler_aicarus import RecvHandlerAicarus

# --- “化妆间”：定义各种事件的构造工厂 ---


class BaseEventFactory(ABC):
    """所有事件“化妆师”的基类，她们都得会“创造”这门手艺"""

    @abstractmethod
    async def create_event(
        self, napcat_event: Dict[str, Any], recv_handler: "RecvHandlerAicarus"
    ) -> Optional[Event]:
        """根据原始的Napcat数据，创造一个性感又标准的AIcarus事件"""
        pass


class MessageEventFactory(BaseEventFactory):
    """专门负责构造“消息事件”的化妆师，手法最细腻，活儿最好"""

    async def create_event(
        self, napcat_event: Dict[str, Any], recv_handler: "RecvHandlerAicarus"
    ) -> Optional[Event]:
        bot_id = (
            str(napcat_event.get("self_id"))
            or await recv_handler._get_bot_id()
            or "unknown_bot"
        )
        napcat_message_type = napcat_event.get("message_type")
        napcat_sub_type = napcat_event.get("sub_type")
        napcat_message_id = str(napcat_event.get("message_id", ""))
        napcat_sender = napcat_event.get("sender", {})

        event_type = "message.unknown"
        aicarus_conversation_info: Optional[ConversationInfo] = None
        aicarus_user_info: Optional[UserInfo] = None

        if napcat_message_type == MessageType.private:
            # 对于私聊，永远不应该传入 group_id
            aicarus_user_info = await recv_handler._napcat_to_aicarus_userinfo(
                napcat_sender, group_id=None
            )
            event_type = "message.private.other"
            if napcat_sub_type == MessageType.Private.friend:
                event_type = "message.private.friend"
                if aicarus_user_info:
                    aicarus_conversation_info = await recv_handler._napcat_to_aicarus_private_conversationinfo(
                        aicarus_user_info
                    )
            elif napcat_sub_type == MessageType.Private.group:
                event_type = "message.private.temporary"
                # 临时会话本质上是在一个群里，所以它有 group_id
                temp_group_id = str(napcat_event.get("group_id", "")).strip()
                if temp_group_id and temp_group_id != "0":
                    aicarus_conversation_info = (
                        await recv_handler._napcat_to_aicarus_conversationinfo(
                            temp_group_id
                        )
                    )
                else:
                    logger.warning(f"临时会话事件 {napcat_message_id} 缺少有效的 group_id。")

        elif napcat_message_type == MessageType.group:
            group_id = str(napcat_event.get("group_id", ""))
            aicarus_user_info = await recv_handler._napcat_to_aicarus_userinfo(
                napcat_sender, group_id=group_id
            )
            aicarus_conversation_info = (
                await recv_handler._napcat_to_aicarus_conversationinfo(group_id)
            )
            event_type = "message.group.other"
            if napcat_sub_type == MessageType.Group.normal:
                event_type = "message.group.normal"
            elif napcat_sub_type == MessageType.Group.anonymous:
                event_type = "message.group.anonymous"
        else:
            logger.warning(f"事件化妆间: 不认识的消息类型: {napcat_message_type}")
            return None

        # 把字体和匿名信息都塞进这个“套套”里，才算完整！
        metadata_data = {"message_id": napcat_message_id}
        if napcat_event.get("font") is not None:
            metadata_data["font"] = str(napcat_event.get("font"))
        if napcat_sub_type == MessageType.Group.anonymous and napcat_event.get(
            "anonymous"
        ):
            metadata_data["anonymity_info"] = napcat_event.get("anonymous")

        content_segs = [Seg(type="message_metadata", data=metadata_data)]
        message_segs = await recv_handler._napcat_to_aicarus_seglist(
            napcat_event.get("message", []), napcat_event
        )
        if not message_segs:
            return None
        content_segs.extend(message_segs)

        return Event(
            event_id=f"message_{napcat_message_id}_{uuid.uuid4()}",
            event_type=event_type,
            time=napcat_event.get("time", time.time()) * 1000.0,
            platform=recv_handler.global_config.core_platform_id,
            bot_id=bot_id,
            user_info=aicarus_user_info,
            conversation_info=aicarus_conversation_info,
            content=content_segs,
            raw_data=json.dumps(napcat_event),
        )


class NoticeEventFactory(BaseEventFactory):
    """专门负责构造“通知事件”的化妆师，现在我可勤快了，什么通知都给你处理得明明白白！"""

    async def create_event(
        self, napcat_event: Dict[str, Any], recv_handler: "RecvHandlerAicarus"
    ) -> Optional[Event]:
        notice_type = napcat_event.get("notice_type")
        bot_id = (
            str(napcat_event.get("self_id"))
            or await recv_handler._get_bot_id()
            or "unknown_bot"
        )
        cfg = recv_handler.global_config

        event_type = f"notice.unknown.{notice_type}"
        notice_data: Dict[str, Any] = {}
        user_info: Optional[UserInfo] = None
        conversation_info: Optional[ConversationInfo] = None

        group_id_str = str(napcat_event.get("group_id", "")).strip()
        group_id = group_id_str if group_id_str and group_id_str != "0" else None
        
        user_id_str = str(napcat_event.get("user_id", "")).strip()
        user_id = user_id_str if user_id_str and user_id_str != "0" else None

        operator_id_str = str(napcat_event.get("operator_id", "")).strip()
        operator_id = operator_id_str if operator_id_str and operator_id_str != "0" else None

        if group_id:
            conversation_info = await recv_handler._napcat_to_aicarus_conversationinfo(
                group_id
            )
        if user_id:  # 事件主体用户
            # 只有当 group_id 真实存在时，才将其传入以获取群成员信息
            user_info = await recv_handler._napcat_to_aicarus_userinfo(
                {"user_id": user_id}, group_id=group_id
            )

        # --- 开始精细化处理，把每种通知都舔干净 ---
        if notice_type == NoticeType.group_upload:
            event_type = "notice.conversation.file_upload"
            file_info = napcat_event.get("file", {})
            notice_data = {
                "file_info": file_info,
                "uploader_user_info": user_info.to_dict() if user_info else None,
            }

        elif notice_type == NoticeType.group_admin:
            event_type = "notice.conversation.admin_change"
            sub_type = napcat_event.get("sub_type")
            notice_data = {
                "target_user_info": user_info.to_dict() if user_info else None,
                "action_type": "set" if sub_type == "set" else "unset",
            }

        elif notice_type == NoticeType.group_decrease:
            event_type = "notice.conversation.member_decrease"
            operator = (
                await recv_handler._napcat_to_aicarus_userinfo(
                    {"user_id": operator_id}, group_id=group_id
                )
                if operator_id
                else None
            )
            notice_data = {
                "operator_user_info": operator.to_dict() if operator else None,
                "leave_type": napcat_event.get("sub_type"),
            }

        elif notice_type == NoticeType.group_increase:
            event_type = "notice.conversation.member_increase"
            operator = (
                await recv_handler._napcat_to_aicarus_userinfo(
                    {"user_id": operator_id}, group_id=group_id
                )
                if operator_id
                else None
            )
            notice_data = {
                "operator_user_info": operator.to_dict() if operator else None,
                "join_type": napcat_event.get("sub_type"),
            }

        elif notice_type == NoticeType.group_ban:
            event_type = "notice.conversation.member_ban"
            duration = napcat_event.get("duration", 0)
            operator = (
                await recv_handler._napcat_to_aicarus_userinfo(
                    {"user_id": operator_id}, group_id=group_id
                )
                if operator_id
                else None
            )
            notice_data = {
                "target_user_info": user_info.to_dict() if user_info else None,
                "operator_user_info": operator.to_dict() if operator else None,
                "duration_seconds": duration,
                "ban_type": "ban" if duration > 0 else "lift_ban",
            }

        elif notice_type == NoticeType.group_recall:
            event_type = "notice.message.recalled"
            operator = (
                await recv_handler._napcat_to_aicarus_userinfo(
                    {"user_id": operator_id}, group_id=group_id
                )
                if operator_id
                else None
            )
            notice_data = {
                "recalled_message_id": str(napcat_event.get("message_id", "")),
                "recalled_message_sender_info": user_info.to_dict()
                if user_info
                else None,
                "operator_user_info": operator.to_dict() if operator else None,
            }

        elif notice_type == NoticeType.friend_recall:
            event_type = "notice.message.recalled"
            notice_data = {
                "recalled_message_id": str(napcat_event.get("message_id", "")),
                "friend_user_info": user_info.to_dict() if user_info else None,
                "operator_user_info": user_info.to_dict()
                if user_info
                else None,  # 好友撤回，操作者就是他自己
            }

        elif (
            notice_type == NoticeType.notify and napcat_event.get("sub_type") == "poke"
        ):
            event_type = "notice.user.poke"
            target_id = str(napcat_event.get("target_id", ""))
            sender_id = str(napcat_event.get("sender_id", ""))
            # 戳一戳的 user_info 是发起者(sender)，不是事件主体(user_id)
            sender_info = await recv_handler._napcat_to_aicarus_userinfo(
                {"user_id": sender_id}, group_id=group_id
            )
            target_info = await recv_handler._napcat_to_aicarus_userinfo(
                {"user_id": target_id}, group_id=group_id
            )
            user_info = sender_info  # 覆盖事件主体为发起者
            notice_data = {
                "sender_user_info": sender_info.to_dict() if sender_info else None,
                "target_user_info": target_info.to_dict() if target_info else None,
                "context_type": "group" if group_id else "private",
            }

        else:  # 其他未处理的通知，保持原样
            notice_data = napcat_event.copy()

        content_seg = Seg(type=event_type, data=notice_data)
        return Event(
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


class RequestEventFactory(BaseEventFactory):
    """专门负责构造“请求事件”的化妆师，无论是好友还是群聊，我都给你安排得明明白白！"""

    async def create_event(
        self, napcat_event: Dict[str, Any], recv_handler: "RecvHandlerAicarus"
    ) -> Optional[Event]:
        request_type = napcat_event.get("request_type")
        bot_id = (
            str(napcat_event.get("self_id"))
            or await recv_handler._get_bot_id()
            or "unknown_bot"
        )
        cfg = recv_handler.global_config

        event_type = f"request.unknown.{request_type}"
        user_info: Optional[UserInfo] = None
        conversation_info: Optional[ConversationInfo] = None
        user_id = str(napcat_event.get("user_id", ""))
        group_id = str(napcat_event.get("group_id", ""))

        if user_id:
            user_info = await recv_handler._napcat_to_aicarus_userinfo(
                {"user_id": user_id}, group_id=group_id if group_id else None
            )

        request_data = {
            "comment": napcat_event.get("comment", ""),
            "request_flag": napcat_event.get("flag", ""),
        }

        if request_type == "friend":
            event_type = "request.friend.add"

        elif request_type == "group":
            sub_type = napcat_event.get("sub_type")
            if group_id:
                conversation_info = (
                    await recv_handler._napcat_to_aicarus_conversationinfo(group_id)
                )

            if sub_type == "add":
                event_type = "request.conversation.join_application"
            elif sub_type == "invite":
                event_type = "request.conversation.invitation"
            request_data["sub_type"] = sub_type

        else:
            logger.warning(f"事件化妆间: 不认识的请求类型: {request_type}")
            request_data = napcat_event.copy()

        content_seg = Seg(type=event_type, data=request_data)
        return Event(
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


class MetaEventFactory(BaseEventFactory):
    """专门负责构造“元事件”的化妆师，你的生命体征由我来守护！"""

    async def create_event(
        self, napcat_event: Dict[str, Any], recv_handler: "RecvHandlerAicarus"
    ) -> Optional[Event]:
        event_type_raw = napcat_event.get("meta_event_type")
        bot_id = (
            str(napcat_event.get("self_id")) or "unknown_bot"
        )  # meta事件发生时，bot_id通常是明确的
        cfg = recv_handler.global_config

        meta_seg_data: Dict[str, Any] = {}
        event_type: str = f"meta.unknown.{event_type_raw}"

        if event_type_raw == MetaEventType.lifecycle:
            sub_type = napcat_event.get("sub_type")
            event_type = f"meta.lifecycle.{sub_type}"
            if sub_type == "connect":
                # 呀，连接上了！赶紧记录下来，并开始为你心跳！
                recv_handler.napcat_bot_id = bot_id
                recv_handler.last_heart_beat = time.time()
                logger.info(f"连接高潮！Bot {bot_id} 已连接到Napcat，小猫开始为你心跳~")
                asyncio.create_task(recv_handler.check_heartbeat(bot_id))

        elif event_type_raw == MetaEventType.heartbeat:
            event_type = "meta.heartbeat"
            status_obj = napcat_event.get("status", {})
            meta_seg_data = {
                "status_object": status_obj,
                "interval_ms": napcat_event.get("interval"),
            }
            is_online = status_obj.get("online", False) and status_obj.get(
                "good", False
            )
            if is_online:
                # 收到你的心跳了，好舒服~
                recv_handler.last_heart_beat = time.time()
                if napcat_event.get("interval"):  # 更新心跳间隔
                    recv_handler.interval = napcat_event.get("interval") / 1000.0
            else:
                logger.warning(f"你的心跳不规律哦，主人~ ({bot_id})")

        else:
            meta_seg_data = napcat_event.copy()

        content_seg = Seg(type=event_type, data=meta_seg_data)
        return Event(
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


# --- “接待部”：定义接待员和她们的“花名册” ---


class BaseEventHandler(ABC):
    def __init__(self, factory: BaseEventFactory):
        self._factory = factory

    @abstractmethod
    async def execute(
        self, event_data: Dict[str, Any], recv_handler: "RecvHandlerAicarus"
    ) -> None:
        pass


class GenericEventHandler(BaseEventHandler):
    async def execute(
        self, event_data: Dict[str, Any], recv_handler: "RecvHandlerAicarus"
    ) -> None:
        aicarus_event = await self._factory.create_event(event_data, recv_handler)
        if aicarus_event:
            await recv_handler.dispatch_to_core(aicarus_event)


class MessageEventHandlerWithSelfCheck(GenericEventHandler):
    """这位接待员最特别，她懂得“认亲”，能识别出我们自己的回响！"""

    async def execute(
        self, event_data: Dict[str, Any], recv_handler: "RecvHandlerAicarus"
    ) -> None:
        from .action_register import pending_actions

        napcat_user_id = str(event_data.get("user_id", ""))

        if (
            napcat_user_id
            and recv_handler.napcat_bot_id
            and napcat_user_id == recv_handler.napcat_bot_id
        ):
            napcat_message_id = str(event_data.get("message_id", ""))
            original_action_id = pending_actions.pop(napcat_message_id, None)
            if original_action_id:
                logger.info(
                    f"接收处理器: 找到了！消息 {napcat_message_id} 是对动作 {original_action_id} 的高潮响应！"
                )
                response_event = EventBuilder.create_action_response_event(
                    response_type="success",
                    platform=recv_handler.global_config.core_platform_id,
                    bot_id=recv_handler.napcat_bot_id,
                    original_event_id=original_action_id,
                    original_action_type="action.message.send",
                    message="动作已由平台自我上报机制确认成功！",
                    data={"confirmed_message_id": napcat_message_id},
                )
                await recv_handler.dispatch_to_core(response_event)
            return

        await super().execute(event_data, recv_handler)


EVENT_HANDLERS: Dict[str, BaseEventHandler] = {
    "message": MessageEventHandlerWithSelfCheck(MessageEventFactory()),
    "notice": GenericEventHandler(NoticeEventFactory()),
    "request": GenericEventHandler(RequestEventFactory()),
    "meta_event": GenericEventHandler(MetaEventFactory()),
}


def get_event_handler(post_type: str) -> Optional[BaseEventHandler]:
    return EVENT_HANDLERS.get(post_type)
