# aicarus_napcat_adapter/src/action_definitions.py
# 这是我们的“花式玩法名录”，哥哥你看，是不是很性感？
from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional, TYPE_CHECKING

# AIcarus & Napcat 相关导入
from aicarus_protocols import Event, Seg, ConversationType
from .logger import logger

if TYPE_CHECKING:
    from .send_handler_aicarus import SendHandlerAicarus


# --- 定义一个所有“玩法”都要遵守的性感基准 ---
class BaseActionHandler(ABC):
    """所有动作处理器的基类，定义了它们必须拥有的'执行'高潮方法"""

    @abstractmethod
    async def execute(
        self,
        action_seg: Seg,
        event: Event,
        send_handler: "SendHandlerAicarus",  # 引用发送处理器以调用API
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        执行具体的动作。
        返回: (success: bool, error_message: str, details_for_response: dict)
        """
        pass


# --- 现在是具体的“姿势”定义 ---


class RecallMessageHandler(BaseActionHandler):
    """处理撤回消息这个姿势"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        target_message_id = str(action_seg.data.get("target_message_id", ""))
        if not target_message_id:
            return False, "缺少 target_message_id", {}

        try:
            response = await send_handler._send_to_napcat_api(
                "delete_msg", {"message_id": int(target_message_id)}
            )
            if response and response.get("status") == "ok":
                return True, "消息已成功传达撤回指令", {}
            else:
                error_msg = (
                    response.get("message", "Napcat API 错误") if response else "无响应"
                )
                return False, error_msg, {}
        except ValueError:
            return False, f"无效的 message_id 格式: {target_message_id}", {}
        except Exception as e:
            logger.error(f"执行撤回时出现异常: {e}", exc_info=True)
            return False, f"执行撤回时出现异常: {e}", {}


class PokeUserHandler(BaseActionHandler):
    """处理戳一戳这个姿势，好痒~"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        action_data = action_seg.data
        target_uid_str = action_data.get("target_user_id")
        if not target_uid_str and event.user_info:
            target_uid_str = event.user_info.user_id

        target_gid_str = action_data.get("target_group_id")
        if (
            not target_gid_str
            and event.conversation_info
            and event.conversation_info.type == ConversationType.GROUP
        ):
            target_gid_str = event.conversation_info.conversation_id

        if not target_uid_str:
            return False, "缺少 target_user_id", {}

        try:
            target_uid = int(target_uid_str)
            params_poke: Dict[str, Any] = {"user_id": target_uid}
            napcat_action_name = ""

            if target_gid_str:
                napcat_action_name = "group_poke"
                params_poke["group_id"] = int(target_gid_str)
            else:
                napcat_action_name = "friend_poke"

            response = await send_handler._send_to_napcat_api(
                napcat_action_name, params_poke
            )
            if response and response.get("status") == "ok":
                return True, "戳一戳指令已发送", {}
            else:
                error_msg = (
                    response.get(
                        "message", f"Napcat API for {napcat_action_name} error"
                    )
                    if response
                    else "无响应"
                )
                return False, error_msg, {}
        except ValueError:
            return (
                False,
                f"无效的 user_id 或 group_id 格式: {target_uid_str}, {target_gid_str}",
                {},
            )
        except Exception as e:
            logger.error(f"执行戳一戳时出现异常: {e}", exc_info=True)
            return False, f"执行戳一戳时出现异常: {e}", {}


class HandleFriendRequestHandler(BaseActionHandler):
    """处理好友请求，是接受还是拒绝呢，主人？"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        action_data = action_seg.data
        request_flag = str(action_data.get("request_flag", ""))
        approve_action = action_seg.type == "action.request.friend.approve"
        remark = action_data.get("remark")

        if not request_flag:
            return False, "缺少 request_flag", {}

        try:
            params_fh: Dict[str, Any] = {
                "flag": request_flag,
                "approve": approve_action,
            }
            if approve_action and remark:
                params_fh["remark"] = remark

            response = await send_handler._send_to_napcat_api(
                "set_friend_add_request", params_fh
            )
            if response and response.get("status") == "ok":
                return True, "好友请求已处理", {}
            else:
                error_msg = (
                    response.get(
                        "message", "Napcat API for set_friend_add_request error"
                    )
                    if response
                    else "无响应"
                )
                return False, error_msg, {}
        except Exception as e:
            logger.error(f"处理好友请求时出现异常: {e}", exc_info=True)
            return False, f"处理好友请求时出现异常: {e}", {}


class HandleGroupRequestHandler(BaseActionHandler):
    """处理加群的请求，要不要让新人进来玩呀？"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        action_data = action_seg.data
        request_flag = str(action_data.get("request_flag", ""))
        approve_action = action_seg.type == "action.request.conversation.approve"
        reason = action_data.get("reason")
        core_original_request_sub_type = action_data.get("original_request_sub_type")

        if not request_flag:
            return False, "缺少 request_flag", {}

        napcat_sub_type_for_api = ""
        if core_original_request_sub_type == "join_application":
            napcat_sub_type_for_api = "add"
        elif core_original_request_sub_type == "invite_received":
            napcat_sub_type_for_api = "invite"
        else:
            return False, f"未知的原始请求子类型: {core_original_request_sub_type}", {}

        try:
            params_gh: Dict[str, Any] = {
                "flag": request_flag,
                "sub_type": napcat_sub_type_for_api,
                "approve": approve_action,
            }
            if not approve_action and reason:
                params_gh["reason"] = reason

            response = await send_handler._send_to_napcat_api(
                "set_group_add_request", params_gh
            )
            if response and response.get("status") == "ok":
                return True, "群请求已处理", {}
            else:
                error_msg = (
                    response.get(
                        "message", "Napcat API for set_group_add_request error"
                    )
                    if response
                    else "无响应"
                )
                return False, error_msg, {}
        except Exception as e:
            logger.error(f"处理群请求时出现异常: {e}", exc_info=True)
            return False, f"处理群请求时出现异常: {e}", {}


# --- 这就是我们的“花式玩法名录”（动作工厂） ---
ACTION_HANDLERS: Dict[str, BaseActionHandler] = {
    "action.message.recall": RecallMessageHandler(),
    "action.user.poke": PokeUserHandler(),
    "action.request.friend.approve": HandleFriendRequestHandler(),
    "action.request.friend.reject": HandleFriendRequestHandler(),
    "action.request.conversation.approve": HandleGroupRequestHandler(),
    "action.request.conversation.reject": HandleGroupRequestHandler(),
}


def get_action_handler(action_type: str) -> Optional[BaseActionHandler]:
    """根据动作类型，从名录中取出对应的玩法"""
    return ACTION_HANDLERS.get(action_type)
