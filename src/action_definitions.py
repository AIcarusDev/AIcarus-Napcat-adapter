# aicarus_napcat_adapter/src/action_definitions.py
# 这是我们的“花式玩法名录”，哥哥你看，是不是很性感？
from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional, TYPE_CHECKING
import asyncio
import random

# AIcarus & Napcat 相关导入
from aicarus_protocols import Event, Seg, ConversationType
from .logger import logger
from .utils import napcat_get_self_info, napcat_get_member_info, napcat_get_group_list, napcat_get_group_info
from .config import get_config

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


class GetBotProfileHandler(BaseActionHandler):
    """
    处理获取机器人自身信息的请求。
    升级版！现在能一次性获取所有群的名片了，哼！
    """

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        action_id = event.event_id
        logger.info(f"[{action_id}] 开始执行 GetBotProfileHandler (上线安检)...")

        if not send_handler.server_connection:
            logger.error(f"[{action_id}] 执行失败：与 Napcat 的连接已断开。")
            return False, "与 Napcat 的连接已断开", {}

        try:
            # 1. 获取机器人自身的全局信息 (QQ号，昵称)
            logger.info(f"[{action_id}] 正在获取机器人全局信息...")
            self_info = await napcat_get_self_info(send_handler.server_connection)
            if not self_info or not self_info.get("user_id"):
                logger.error(
                    f"[{action_id}] 获取机器人全局信息失败。API返回: {self_info}"
                )
                return False, "获取机器人自身信息失败", {}

            bot_id = str(self_info["user_id"])
            bot_nickname = self_info.get("nickname", "")
            config = get_config()
            platform = config.core_platform_id
            logger.info(
                f"[{action_id}] 成功获取机器人全局信息: ID={bot_id}, Nickname={bot_nickname}"
            )

            # 2. 准备最终要返回给 Core 的数据结构
            profile_data = {
                "user_id": bot_id,
                "nickname": bot_nickname,
                "platform": platform,
                "groups": {},  # <-- 看这里！它创建了一个空的 groups 字典！
            }

            # 3. 获取机器人加入的所有群聊列表
            logger.info(f"[{action_id}] 正在获取机器人所在的群聊列表...")
            group_list = await napcat_get_group_list(send_handler.server_connection)
            if not group_list:
                logger.warning(
                    f"[{action_id}] 未获取到任何群聊列表，将只返回全局信息。"
                )
                return True, "成功获取机器人信息（无群聊）", profile_data

            logger.info(
                f"[{action_id}] 成功获取到 {len(group_list)} 个群聊，开始逐个查询群内档案..."
            )

            # 4. 遍历所有群，获取机器人在每个群里的名片、头衔等信息
            for group in group_list:
                group_id = str(group.get("group_id"))
                group_name = group.get("group_name", "未知群名")

                await asyncio.sleep(random.uniform(0.1, 0.3))

                member_info = await napcat_get_member_info(
                    send_handler.server_connection, group_id, bot_id
                )
                if member_info:
                    card = member_info.get("card") or bot_nickname
                    title = member_info.get("title", "")
                    role = "member"
                    napcat_role = member_info.get("role")
                    if napcat_role == "owner":
                        role = "owner"
                    elif napcat_role == "admin":
                        role = "admin"

                    # 把这个群的信息存到 groups 字典里！
                    profile_data["groups"][group_id] = {
                        "group_name": group_name,
                        "card": card,
                        "title": title,
                        "role": role,
                    }
                    logger.debug(
                        f"[{action_id}] > 群({group_id})档案获取成功: 名片='{card}'"
                    )
                else:
                    logger.warning(
                        f"[{action_id}] > 未能获取到群 {group_id} 内的机器人档案。"
                    )

            logger.info(f"[{action_id}] 所有群聊档案查询完毕，安检完成！")
            return True, "成功获取机器人信息（包括所有群聊档案）", profile_data

        except Exception as e:
            logger.error(
                f"[{action_id}] 执行获取机器人信息时出现异常: {e}", exc_info=True
            )
            return False, f"执行获取机器人信息时出现异常: {e}", {}

class GetGroupInfoHandler(BaseActionHandler):
    """处理获取群聊信息这个姿势，把它的底细都扒光~"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        # 从 action 事件的 conversation_info 里拿出群号
        conversation_info = event.conversation_info
        if not conversation_info or conversation_info.type != ConversationType.GROUP:
            return False, "这个动作只能用在群聊里哦，主人~", {}

        group_id = conversation_info.conversation_id
        if not group_id:
            return False, "哎呀，没找到群号，我怎么查嘛！", {}

        logger.info(f"开始为群 {group_id} 获取信息...")

        # 这里就是去调用 Napcat API 的地方啦
        # 注意！napcat_get_group_info 是在 utils.py 里定义的，它需要 server_connection
        # 而 server_connection 在 send_handler 里有，所以我们这样传
        if not send_handler.server_connection:
            return False, "和 Napcat 的连接断开了，查不了了...", {}

        group_info_data = await napcat_get_group_info(send_handler.server_connection, group_id)

        if group_info_data:
            logger.info(f"成功获取到群 {group_id} 的信息: {group_info_data}")
            # 把查到的信息整理好，准备作为响应数据返回
            details_for_response = {
                "group_id": str(group_info_data.get("group_id")),
                "group_name": group_info_data.get("group_name"),
                "member_count": group_info_data.get("member_count"),
                "max_member_count": group_info_data.get("max_member_count"),
                # 你想返回啥就在这里加啥
            }
            return True, "群信息已成功获取！", details_for_response
        else:
            error_msg = f"获取群 {group_id} 的信息失败了，可能是机器人不在群里，或者API出错了。"
            logger.warning(error_msg)
            return False, error_msg, {}


# --- 这就是我们的“花式玩法名录”（动作工厂） ---
ACTION_HANDLERS: Dict[str, BaseActionHandler] = {
    "action.message.recall": RecallMessageHandler(),
    "action.user.poke": PokeUserHandler(),
    "action.request.friend.approve": HandleFriendRequestHandler(),
    "action.request.friend.reject": HandleFriendRequestHandler(),
    "action.conversation.get_info": GetGroupInfoHandler(),
    "action.request.conversation.approve": HandleGroupRequestHandler(),
    "action.request.conversation.reject": HandleGroupRequestHandler(),
    "action.bot.get_profile": GetBotProfileHandler(),
}


def get_action_handler(action_type: str) -> Optional[BaseActionHandler]:
    """根据动作类型，从名录中取出对应的玩法"""
    return ACTION_HANDLERS.get(action_type)
