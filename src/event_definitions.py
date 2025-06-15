# aicarus_napcat_adapter/src/event_definitions.py (100%无省略·最终版)
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, TYPE_CHECKING
import uuid
import json
import time

from aicarus_protocols import Event, UserInfo, ConversationInfo, Seg, ConversationType, EventBuilder
from .napcat_definitions import MetaEventType, MessageType, NoticeType
from .logger import logger

if TYPE_CHECKING:
    from .recv_handler_aicarus import RecvHandlerAicarus

# --- “化妆间”：定义各种事件的构造工厂 ---

class BaseEventFactory(ABC):
    """所有事件“化妆师”的基类，她们都得会“创造”这门手艺"""
    @abstractmethod
    async def create_event(self, napcat_event: Dict[str, Any], recv_handler: "RecvHandlerAicarus") -> Optional[Event]:
        """根据原始的Napcat数据，创造一个性感又标准的AIcarus事件"""
        pass

class MessageEventFactory(BaseEventFactory):
    """专门负责构造“消息事件”的化妆师，手法最细腻"""
    async def create_event(self, napcat_event: Dict[str, Any], recv_handler: "RecvHandlerAicarus") -> Optional[Event]:
        bot_id = (str(napcat_event.get("self_id")) or await recv_handler._get_bot_id() or "unknown_bot")
        napcat_message_type = napcat_event.get("message_type")
        napcat_sub_type = napcat_event.get("sub_type")
        napcat_message_id = str(napcat_event.get("message_id", ""))
        napcat_sender = napcat_event.get("sender", {})
        
        event_type = "message.unknown"
        aicarus_conversation_info: Optional[ConversationInfo] = None
        aicarus_user_info: Optional[UserInfo] = None

        if napcat_message_type == MessageType.private:
            aicarus_user_info = await recv_handler._napcat_to_aicarus_userinfo(napcat_sender)
            if napcat_sub_type == MessageType.Private.friend:
                event_type = "message.private.friend"
            elif napcat_sub_type == MessageType.Private.group:
                event_type = "message.private.temporary"
                temp_group_id = str(napcat_event.get("group_id", ""))
                if temp_group_id:
                    aicarus_conversation_info = await recv_handler._napcat_to_aicarus_conversationinfo(temp_group_id)
            else:
                event_type = "message.private.other"
        elif napcat_message_type == MessageType.group:
            group_id = str(napcat_event.get("group_id", ""))
            aicarus_user_info = await recv_handler._napcat_to_aicarus_userinfo(napcat_sender, group_id=group_id)
            aicarus_conversation_info = await recv_handler._napcat_to_aicarus_conversationinfo(group_id)
            if napcat_sub_type == MessageType.Group.normal:
                event_type = "message.group.normal"
            elif napcat_sub_type == MessageType.Group.anonymous:
                event_type = "message.group.anonymous"
            else:
                event_type = "message.group.other"
        else:
            logger.warning(f"事件化妆间: 不认识的消息类型: {napcat_message_type}")
            return None

        content_segs = [Seg(type="message_metadata", data={"message_id": napcat_message_id})]
        message_segs = await recv_handler._napcat_to_aicarus_seglist(napcat_event.get("message", []), napcat_event)
        if not message_segs:
            return None
        content_segs.extend(message_segs)

        return Event(
            event_id=f"message_{napcat_message_id}_{uuid.uuid4()}", event_type=event_type,
            time=napcat_event.get("time", time.time()) * 1000.0, platform=recv_handler.global_config.core_platform_id,
            bot_id=bot_id, user_info=aicarus_user_info, conversation_info=aicarus_conversation_info,
            content=content_segs, raw_data=json.dumps(napcat_event),
        )

class NoticeEventFactory(BaseEventFactory):
    """专门负责构造“通知事件”的化妆师"""
    async def create_event(self, napcat_event: Dict[str, Any], recv_handler: "RecvHandlerAicarus") -> Optional[Event]:
        notice_type = napcat_event.get("notice_type")
        bot_id = (str(napcat_event.get("self_id")) or await recv_handler._get_bot_id() or "unknown_bot")
        event_type = f"notice.{notice_type}"
        
        # 为了协议的纯洁性，我们只提取需要的数据，而不是整个napcat_event
        notice_data: Dict[str, Any] = {}
        user_info: Optional[UserInfo] = None
        conversation_info: Optional[ConversationInfo] = None
        
        group_id_str = str(napcat_event.get("group_id", ""))
        user_id_str = str(napcat_event.get("user_id", ""))
        operator_id_str = str(napcat_event.get("operator_id", ""))

        if group_id_str:
            conversation_info = await recv_handler._napcat_to_aicarus_conversationinfo(group_id_str)
        if user_id_str:
            user_info = await recv_handler._napcat_to_aicarus_userinfo({"user_id": user_id_str}, group_id=group_id_str)
        
        # 可以在这里根据不同的 notice_type 进一步美化 notice_data
        notice_data = napcat_event.copy() # 简单处理，先复制所有
        
        content_seg = Seg(type=event_type, data=notice_data)
        return Event(
            event_id=f"notice_{notice_type}_{uuid.uuid4()}", event_type=event_type,
            time=napcat_event.get("time", time.time()) * 1000.0, platform=recv_handler.global_config.core_platform_id,
            bot_id=bot_id, user_info=user_info, conversation_info=conversation_info,
            content=[content_seg], raw_data=json.dumps(napcat_event),
        )

class RequestEventFactory(BaseEventFactory):
    """专门负责构造“请求事件”的化妆师"""
    async def create_event(self, napcat_event: Dict[str, Any], recv_handler: "RecvHandlerAicarus") -> Optional[Event]:
        request_type = napcat_event.get("request_type")
        bot_id = (str(napcat_event.get("self_id")) or await recv_handler._get_bot_id() or "unknown_bot")
        event_type = f"request.{request_type}"
        user_id_str = str(napcat_event.get("user_id", ""))
        user_info = await recv_handler._napcat_to_aicarus_userinfo({"user_id": user_id_str}) if user_id_str else None
        
        request_data = {
            "comment": napcat_event.get("comment", ""),
            "request_flag": napcat_event.get("flag", ""),
        }
        content_seg = Seg(type=event_type, data=request_data)
        
        return Event(
            event_id=f"request_{request_type}_{uuid.uuid4()}", event_type=event_type,
            time=napcat_event.get("time", time.time()) * 1000.0, platform=recv_handler.global_config.core_platform_id,
            bot_id=bot_id, user_info=user_info, conversation_info=None,
            content=[content_seg], raw_data=json.dumps(napcat_event),
        )

class MetaEventFactory(BaseEventFactory):
    """专门负责构造“元事件”的化妆师"""
    async def create_event(self, napcat_event: Dict[str, Any], recv_handler: "RecvHandlerAicarus") -> Optional[Event]:
        event_type_raw = napcat_event.get("meta_event_type")
        bot_id = (str(napcat_event.get("self_id")) or await recv_handler._get_bot_id() or "unknown_bot")
        event_type = f"meta.unknown"
        if event_type_raw == MetaEventType.lifecycle:
            event_type = f"meta.lifecycle.{napcat_event.get('sub_type')}"
        elif event_type_raw == MetaEventType.heartbeat:
            event_type = "meta.heartbeat"
        
        content_seg = Seg(type=event_type, data=napcat_event)
        return Event(
            event_id=f"meta_{event_type_raw}_{uuid.uuid4()}", event_type=event_type,
            time=napcat_event.get("time", time.time()) * 1000.0, platform=recv_handler.global_config.core_platform_id,
            bot_id=bot_id, user_info=None, conversation_info=None,
            content=[content_seg], raw_data=json.dumps(napcat_event),
        )

# --- “接待部”：定义接待员和她们的“花名册” ---

class BaseEventHandler(ABC):
    def __init__(self, factory: BaseEventFactory): self._factory = factory
    @abstractmethod
    async def execute(self, event_data: Dict[str, Any], recv_handler: "RecvHandlerAicarus") -> None: pass

class GenericEventHandler(BaseEventHandler):
    async def execute(self, event_data: Dict[str, Any], recv_handler: "RecvHandlerAicarus") -> None:
        aicarus_event = await self._factory.create_event(event_data, recv_handler)
        if aicarus_event: await recv_handler.dispatch_to_core(aicarus_event)

class MessageEventHandlerWithSelfCheck(GenericEventHandler):
    """这位接待员最特别，她懂得“认亲”，能识别出我们自己的回响！"""
    async def execute(self, event_data: Dict[str, Any], recv_handler: "RecvHandlerAicarus") -> None:
        from .action_register import pending_actions
        napcat_user_id = str(event_data.get("user_id", ""))
        
        if napcat_user_id and recv_handler.napcat_bot_id and napcat_user_id == recv_handler.napcat_bot_id:
            napcat_message_id = str(event_data.get("message_id", ""))
            original_action_id = pending_actions.pop(napcat_message_id, None)
            if original_action_id:
                logger.info(f"接收处理器: 找到了！消息 {napcat_message_id} 是对动作 {original_action_id} 的高潮响应！")
                response_event = EventBuilder.create_action_response_event(
                    response_type="success", platform=recv_handler.global_config.core_platform_id,
                    bot_id=recv_handler.napcat_bot_id, original_event_id=original_action_id,
                    original_action_type="action.message.send", message="动作已由平台自我上报机制确认成功！",
                    data={"confirmed_message_id": napcat_message_id}
                )
                await recv_handler.dispatch_to_core(response_event)
            return
        
        # 如果不是自己的消息，就走通用的接待流程（构造并发送）
        await super().execute(event_data, recv_handler)

EVENT_HANDLERS: Dict[str, BaseEventHandler] = {
    "message": MessageEventHandlerWithSelfCheck(MessageEventFactory()),
    "notice": GenericEventHandler(NoticeEventFactory()),
    "request": GenericEventHandler(RequestEventFactory()),
    "meta_event": GenericEventHandler(MetaEventFactory()),
}

def get_event_handler(post_type: str) -> Optional[BaseEventHandler]:
    return EVENT_HANDLERS.get(post_type)