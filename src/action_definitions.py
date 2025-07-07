# aicarus_napcat_adapter/src/action_definitions.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional, TYPE_CHECKING, List
import asyncio
import random

# AIcarus & Napcat 相关导入
from aicarus_protocols import Event, Seg, ConversationType
from .logger import logger
from .utils import (
    napcat_get_self_info,
    napcat_get_member_info,
    napcat_get_group_list,
    napcat_get_friend_list,
    napcat_get_group_info,
    napcat_set_group_sign,
    napcat_set_online_status,
    napcat_set_qq_avatar,
    napcat_get_friend_msg_history,
    napcat_forward_friend_single_msg,
    napcat_forward_group_single_msg,
    napcat_get_group_msg_history,
)
from .config import get_config
from .recv_handler_aicarus import recv_handler_aicarus

if TYPE_CHECKING:
    from .send_handler_aicarus import SendHandlerAicarus


# --- 定义一个基准 ---
class BaseActionHandler(ABC):
    @abstractmethod
    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        pass


# --- 现在是具体的定义 ---
class SendForwardMessageHandler(BaseActionHandler):
    """处理发送合并转发消息，这个有点复杂，得慢慢来~"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        # 合并转发得看整个 event.content，才不看你这个小小的 action_seg 呢
        nodes = event.content
        if not nodes or not all(seg.type == "node" for seg in nodes):
            return False, "发送合并转发失败：内容必须是'node'消息段的列表。", {}

        # 转换所有节点
        napcat_nodes = []
        for node_seg in nodes:
            node_data = node_seg.data
            # 伪造的消息节点需要 user_id 和 nickname
            if "user_id" in node_data and "nickname" in node_data:
                # 把节点（node）一个个转换掉
                # 节点里的内容也得转换成Napcat格式
                napcat_content = await send_handler._aicarus_segs_to_napcat_array(
                    node_data.get("content", [])
                )
                napcat_nodes.append(
                    {
                        "user_id": str(node_data["user_id"]),
                        "nickname": str(node_data["nickname"]),
                        "content": napcat_content,
                    }
                )
            # 真实消息转发只需要 message_id
            elif "message_id" in node_data:
                napcat_nodes.append(
                    {
                        "id": str(node_data["message_id"]),
                    }
                )
            else:
                return (
                    False,
                    f"发送合并转发失败：节点缺少必要字段（'message_id' 或 'user_id'/'nickname'）。问题节点: {node_data}",
                    {},
                )

        # 确定是发给群还是私聊
        conv_info = event.conversation_info
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

        params: Dict[str, Any]
        # Napcat v4 的合并转发API是 send_forward_msg
        napcat_action: str = "send_forward_msg"
        try:
            if target_group_id:
                params = {"group_id": int(target_group_id), "messages": napcat_nodes}
            elif target_user_id:
                params = {"user_id": int(target_user_id), "messages": napcat_nodes}
            else:
                return (
                    False,
                    "发送合并转发失败：缺少会话目标 (group_id 或 user_id)。",
                    {},
                )
        except (ValueError, TypeError):
            return (
                False,
                f"会话目标ID格式不对哦。当前ID: {target_group_id or target_user_id}",
                {},
            )

        # 发送给Napcat
        response = await send_handler._send_to_napcat_api(napcat_action, params)

        if response and response.get("status") == "ok":
            sent_message_id = str(response.get("data", {}).get("message_id", ""))
            forward_id = str(
                response.get("data", {}).get("forward_id", "")
                or response.get("data", {}).get("res_id", "")
            )
            return (
                True,
                "合并转发消息已发送。",
                {"sent_message_id": sent_message_id, "forward_id": forward_id},
            )
        else:
            err_msg = (
                response.get("message", "Napcat API 错误")
                if response
                else "Napcat 没有回应我..."
            )
            return False, err_msg, {}


class GroupKickHandler(BaseActionHandler):
    """处理踢人，不听话的就让他滚蛋！"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        data = action_seg.data
        group_id = data.get("group_id")
        user_id = data.get("user_id")
        reject_add_request = data.get("reject_add_request", False)

        if not group_id or not user_id:
            return False, "踢人失败：缺少 group_id 或 user_id。", {}

        try:
            params = {
                "group_id": int(group_id),
                "user_id": int(user_id),
                "reject_add_request": reject_add_request,
            }
            response = await send_handler._send_to_napcat_api("set_group_kick", params)
            if response and response.get("status") == "ok":
                return True, "踢人指令已发送。", {}
            else:
                err_msg = (
                    response.get("message", "Napcat API 错误") if response else "无响应"
                )
                return False, f"踢人失败: {err_msg}", {}
        except (ValueError, TypeError):
            return False, f"无效的 group_id 或 user_id: {group_id}, {user_id}", {}


class GroupBanHandler(BaseActionHandler):
    """处理禁言，让他闭嘴，安静点！"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        data = action_seg.data
        group_id = data.get("group_id")
        user_id = data.get("user_id")
        duration = data.get("duration", 60)  # 默认禁言60秒

        if not group_id or not user_id:
            return False, "禁言失败：缺少 group_id 或 user_id。", {}

        try:
            params = {
                "group_id": int(group_id),
                "user_id": int(user_id),
                "duration": int(duration),
            }
            response = await send_handler._send_to_napcat_api("set_group_ban", params)
            if response and response.get("status") == "ok":
                return True, "禁言指令已发送。", {}
            else:
                err_msg = (
                    response.get("message", "Napcat API 错误") if response else "无响应"
                )
                return False, f"禁言失败: {err_msg}", {}
        except (ValueError, TypeError):
            return False, "无效的 group_id, user_id 或 duration", {}


class GroupWholeBanHandler(BaseActionHandler):
    """处理全员禁言，让世界清静一会儿~"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        data = action_seg.data
        group_id = data.get("group_id")
        enable = data.get("enable", True)  # 默认开启禁言

        if not group_id:
            return False, "全员禁言失败：缺少 group_id。", {}

        try:
            params = {"group_id": int(group_id), "enable": enable}
            response = await send_handler._send_to_napcat_api(
                "set_group_whole_ban", params
            )
            if response and response.get("status") == "ok":
                return True, "全员禁言指令已发送。", {}
            else:
                err_msg = (
                    response.get("message", "Napcat API 错误") if response else "无响应"
                )
                return False, f"全员禁言失败: {err_msg}", {}
        except (ValueError, TypeError):
            return False, f"无效的 group_id: {group_id}", {}


class GroupCardHandler(BaseActionHandler):
    """设置群名片，给他换个新名字玩玩。"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        data = action_seg.data
        group_id = data.get("group_id")
        user_id = data.get("user_id")
        card = data.get("card", "")  # 传空字符串表示删除名片

        if not group_id or not user_id:
            return False, "设置群名片失败：缺少 group_id 或 user_id。", {}

        try:
            params = {
                "group_id": int(group_id),
                "user_id": int(user_id),
                "card": card,
            }
            response = await send_handler._send_to_napcat_api("set_group_card", params)
            if response and response.get("status") == "ok":
                return True, "群名片设置指令已发送。", {}
            else:
                err_msg = (
                    response.get("message", "Napcat API 错误") if response else "无响应"
                )
                return False, f"设置群名片失败: {err_msg}", {}
        except (ValueError, TypeError):
            return False, "无效的 group_id 或 user_id", {}


class GroupSpecialTitleHandler(BaseActionHandler):
    """设置专属头衔，听起来好中二哦。"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        data = action_seg.data
        group_id = data.get("group_id")
        user_id = data.get("user_id")
        special_title = data.get("special_title", "")
        duration = data.get("duration", -1)  # 默认永久

        if not group_id or not user_id:
            return False, "设置头衔失败：缺少 group_id 或 user_id。", {}

        try:
            params = {
                "group_id": int(group_id),
                "user_id": int(user_id),
                "special_title": special_title,
                "duration": int(duration),
            }
            response = await send_handler._send_to_napcat_api(
                "set_group_special_title", params
            )
            if response and response.get("status") == "ok":
                return True, "专属头衔设置指令已发送。", {}
            else:
                err_msg = (
                    response.get("message", "Napcat API 错误") if response else "无响应"
                )
                return False, f"设置头衔失败: {err_msg}", {}
        except (ValueError, TypeError):
            return False, "无效的 group_id, user_id 或 duration", {}


class GroupLeaveHandler(BaseActionHandler):
    """退群...拜拜了您内！"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        data = action_seg.data
        group_id = data.get("group_id")
        is_dismiss = data.get("is_dismiss", False)

        if not group_id:
            return False, "退群失败：缺少 group_id。", {}

        try:
            params = {"group_id": int(group_id), "is_dismiss": is_dismiss}
            response = await send_handler._send_to_napcat_api("set_group_leave", params)
            if response and response.get("status") == "ok":
                return True, "退群指令已发送。", {}
            else:
                err_msg = (
                    response.get("message", "Napcat API 错误") if response else "无响应"
                )
                return False, f"退群失败: {err_msg}", {}
        except (ValueError, TypeError):
            return False, f"无效的 group_id: {group_id}", {}


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
    """处理好友请求，是接受还是拒绝呢？"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        action_data = action_seg.data
        request_flag = str(action_data.get("request_flag", ""))
        # 啊~❤ 现在 approve 参数直接从 data 里拿，多方便！
        approve_action = action_data.get("approve", False)
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
    """处理加群的请求，要不要让新人进来玩呢？"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        action_data = action_seg.data
        request_flag = str(action_data.get("request_flag", ""))
        # 啊~❤ 这里也一样！
        approve_action = action_data.get("approve", False)
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
    """

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        action_id = event.event_id
        # 从核心的请求中，检查它想要哪个群的档案
        specific_group_id = action_seg.data.get("group_id")

        log_msg_header = f"[{action_id}] GetBotProfileHandler"

        if specific_group_id:
            logger.info(
                f"{log_msg_header}: 核心请求了特定群聊 '{specific_group_id}' 的档案，但我将执行完整的全身安检来确保数据新鲜，哼~"
            )
        else:
            logger.info(f"{log_msg_header} (Full Scan): 开始执行...")

        if not send_handler.server_connection:
            logger.error(f"{log_msg_header}: 执行失败：与 Napcat 的连接已断开。")
            return False, "与 Napcat 的连接已断开", {}

        try:
            # 1. 获取机器人自身的全局信息 (QQ号，昵称)，这是必须的
            self_info = await napcat_get_self_info(send_handler.server_connection)
            if not self_info or not self_info.get("user_id"):
                logger.error(
                    f"{log_msg_header}: 获取机器人全局信息失败。API返回: {self_info}"
                )
                return False, "获取机器人自身信息失败", {}

            bot_id = str(self_info["user_id"])
            bot_nickname = self_info.get("nickname", "")

            config = get_config()
            platform = config.core_platform_id
            logger.info(
                f"{log_msg_header}: 成功获取机器人全局信息: ID={bot_id}, Nickname={bot_nickname}"
            )

            profile_data = {
                "user_id": bot_id,
                "nickname": bot_nickname,
                "platform": platform,
                "groups": {},
            }

            logger.info(f"{log_msg_header}: 正在获取机器人所在的群聊列表...")
            group_list = await napcat_get_group_list(send_handler.server_connection)
            if not group_list:
                logger.warning(
                    f"{log_msg_header}: 未获取到任何群聊列表，将只返回全局信息。"
                )
                return True, "成功获取机器人信息（无群聊）", profile_data

            logger.info(
                f"{log_msg_header}: 成功获取到 {len(group_list)} 个群聊，开始逐个查询群内档案..."
            )

            # 创建一个任务列表，让所有群的查询并发进行，这才是真正的效率！
            tasks = []
            for group in group_list:
                group_id = str(group.get("group_id"))
                tasks.append(
                    self._get_single_group_profile(
                        send_handler, group_id, bot_id, bot_nickname, log_msg_header
                    )
                )

            # 等待所有查询结束
            results = await asyncio.gather(*tasks)

            # 把所有成功的结果（档案）收集起来
            for group_profile in results:
                if group_profile:
                    group_id_key = list(group_profile.keys())[0]
                    profile_data["groups"][group_id_key] = group_profile[group_id_key]

            logger.info(f"{log_msg_header}: 所有群聊档案查询完毕，全身安检完成！")
            return True, "成功获取机器人信息（包括所有群聊档案）", profile_data

        except Exception as e:
            logger.error(
                f"[{action_id}] 执行获取机器人信息时出现异常: {e}", exc_info=True
            )
            return False, f"执行获取机器人信息时出现异常: {e}", {}

    async def _get_single_group_profile(
        self,
        send_handler: "SendHandlerAicarus",
        group_id: str,
        bot_id: str,
        bot_nickname: str,
        log_msg_header: str,
    ) -> Optional[Dict[str, Any]]:
        """一个私密的小工具，专门用来获取单个群的档案，让上面的代码更干净~"""
        try:
            # 在这里加一个小的随机延迟，避免瞬间请求太多导致被风控
            await asyncio.sleep(random.uniform(0.1, 0.3))

            group_info = await napcat_get_group_info(
                send_handler.server_connection, group_id
            )
            group_name = (
                group_info.get("group_name", "未知群名") if group_info else "未知群名"
            )

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

                logger.debug(
                    f"{log_msg_header} > 群({group_id})档案获取成功: 名片='{card}'"
                )
                return {
                    group_id: {
                        "group_name": group_name,
                        "card": card,
                        "title": title,
                        "role": role,
                    }
                }
            else:
                logger.warning(
                    f"{log_msg_header} > 未能获取到群 {group_id} 内的机器人档案。"
                )
                return None
        except Exception as e:
            logger.error(f"{log_msg_header} > 查询群 {group_id} 档案时出错: {e}")
            return None


class GetGroupInfoHandler(BaseActionHandler):
    """处理获取群聊信息."""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        # 从 action 事件的 conversation_info 里拿出群号
        conversation_info = event.conversation_info
        if not conversation_info or conversation_info.type != ConversationType.GROUP:
            return False, "这个动作只能用在群聊里哦", {}

        group_id = conversation_info.conversation_id
        if not group_id:
            return False, "哎呀，没找到群号，我怎么查！", {}

        logger.info(f"开始为群 {group_id} 获取信息...")

        # 这里就是去调用 Napcat API 的地方啦
        # 注意！napcat_get_group_info 是在 utils.py 里定义的，它需要 server_connection
        # 而 server_connection 在 send_handler 里有，所以我们这样传
        if not send_handler.server_connection:
            return False, "和 Napcat 的连接断开了，查不了了...", {}

        group_info_data = await napcat_get_group_info(
            send_handler.server_connection, group_id
        )

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
            error_msg = (
                f"获取群 {group_id} 的信息失败了，可能是机器人不在群里，或者API出错了。"
            )
            logger.warning(error_msg)
            return False, error_msg, {}


class GroupSignInHandler(BaseActionHandler):
    """处理群签到，真有人用这个吗？"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        group_id = action_seg.data.get("group_id")
        if not group_id:
            return False, "群签到失败：必须提供 group_id。", {}

        try:
            response = await napcat_set_group_sign(
                send_handler.server_connection, int(group_id)
            )
            if response is not None:
                return True, "群签到指令已发送。", {}
            else:
                return False, "群签到失败：Napcat API 调用失败或无响应。", {}
        except (ValueError, TypeError):
            return False, f"无效的 group_id: {group_id}", {}


class SetBotStatusHandler(BaseActionHandler):
    """设置在线状态，你想变成“离开”还是“隐身”？随你便。"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        status = action_seg.data.get("status")
        if status is None:
            return False, "设置在线状态失败：必须提供 status 字段。", {}

        # 提供默认值，万一你懒得传呢
        ext_status = action_seg.data.get("ext_status", 0)
        battery_status = action_seg.data.get("battery_status", 100)

        try:
            response = await napcat_set_online_status(
                send_handler.server_connection,
                int(status),
                int(ext_status),
                int(battery_status),
            )
            if response is not None:
                return True, "在线状态设置指令已发送。", {}
            else:
                return False, "设置在线状态失败：Napcat API 调用失败或无响应。", {}
        except (ValueError, TypeError):
            return False, "status, ext_status, battery_status 必须是数字哦。", {}


class SetBotAvatarHandler(BaseActionHandler):
    """换个头像换个心情."""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        file = action_seg.data.get("file")
        if not file:
            return False, "设置头像失败：必须提供 file 字段。", {}

        response = await napcat_set_qq_avatar(send_handler.server_connection, file)
        if response is not None:
            return True, "设置头像指令已发送。", {}
        else:
            return False, "设置头像失败：Napcat API 调用失败或无响应。", {}


class GetHistoryHandler(BaseActionHandler):
    """获取历史消息，最麻烦的就是你了！我得把每一条都给你重新化妆一遍！"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        conv_info = event.conversation_info
        if not conv_info or not conv_info.conversation_id:
            return False, "获取历史消息失败：缺少会话信息。", {}

        message_seq = action_seg.data.get("message_seq")
        count = action_seg.data.get("count", 20)

        raw_messages: Optional[List[Dict[str, Any]]] = None
        try:
            if conv_info.type == ConversationType.GROUP:
                raw_messages = await napcat_get_group_msg_history(
                    send_handler.server_connection,
                    conv_info.conversation_id,
                    message_seq,
                    count,
                )
            elif conv_info.type == ConversationType.PRIVATE:
                raw_messages = await napcat_get_friend_msg_history(
                    send_handler.server_connection,
                    conv_info.conversation_id,
                    message_seq,
                    count,
                )
            else:
                return (
                    False,
                    f"不支持的会话类型 '{conv_info.type}' 用于获取历史消息。",
                    {},
                )
        except Exception as e:
            logger.error(f"调用历史消息API时出错: {e}", exc_info=True)
            return False, f"调用历史消息API时出错: {e}", {}

        if raw_messages is None:
            return False, "从Napcat获取历史消息失败，API可能返回错误或无响应。", {}

        # 开始我最累的工作了：把一堆乱七八糟的原始消息，变成你们喜欢的样子
        converted_messages = []
        for raw_msg in raw_messages:
            try:
                # 复用 recv_handler 里的工具，我才不自己重写一遍呢
                user_info_obj = await recv_handler_aicarus._napcat_to_aicarus_userinfo(
                    raw_msg.get("sender", {}),
                    group_id=conv_info.conversation_id
                    if conv_info.type == ConversationType.GROUP
                    else None,
                )

                content_segs = await recv_handler_aicarus._napcat_to_aicarus_seglist(
                    raw_msg.get("message", []), raw_msg
                )

                converted_msg_dict = {
                    "message_id": str(raw_msg.get("message_id")),
                    "time": int(raw_msg.get("time", 0) * 1000),
                    "sender": user_info_obj.to_dict() if user_info_obj else None,
                    "content": [seg.to_dict() for seg in content_segs],
                }
                converted_messages.append(converted_msg_dict)

            except Exception as e:
                logger.error(
                    f"转换一条历史消息时出错: {e}, 原始消息: {raw_msg}", exc_info=True
                )
                # 这条转换失败就跳过

        return True, "历史消息获取成功。", {"messages": converted_messages}


class GetListHandler(BaseActionHandler):
    """哼，一个处理器就够了，专门处理你那个 get_list 动作。"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        # 从塞过来的小纸条(action_seg)里，看看想看群还是看朋友
        list_type = action_seg.data.get("list_type")

        if not list_type or list_type not in ["group", "friend"]:
            return False, f"你要我查什么列表？ '{list_type}' 是个啥？我只认识 'group' 和 'friend'。", {}

        if not send_handler.server_connection:
            return False, "和 Napcat 的连接断开了，查不了了...", {}

        logger.info(f"收到 get_list 请求，准备获取 '{list_type}' 列表...")

        try:
            if list_type == "group":
                # 叫工具人去拿群列表
                list_data = await napcat_get_group_list(send_handler.server_connection)
                if list_data is not None:
                    logger.info(f"成功获取到 {len(list_data)} 个群聊。")
                    # 喏，你的群列表，拿好
                    return True, "群聊列表获取成功。", {"groups": list_data}
                else:
                    return False, "获取群聊列表失败了，Napcat 没理我。", {}

            elif list_type == "friend":
                # 叫工具人去拿好友列表
                list_data = await napcat_get_friend_list(send_handler.server_connection)
                if list_data is not None:
                    logger.info(f"成功获取到 {len(list_data)} 个好友。")
                    # 喏，你的好友列表，别弄丢了
                    return True, "好友列表获取成功。", {"friends": list_data}
                else:
                    return False, "获取好友列表失败了，Napcat 没理我。", {}

        except Exception as e:
            logger.error(f"执行 get_list (type: {list_type}) 时发生意外: {e}", exc_info=True)
            return False, f"执行 get_list 时发生意外: {e}", {}

        # 理论上走不到这里，但为了保险
        return False, "发生了未知错误。", {}


class ForwardSingleMessageHandler(BaseActionHandler):
    """专门用来转发单条消息，不管是给朋友还是给群，我都能应付。"""

    async def execute(
        self, action_seg: Seg, event: Event, send_handler: "SendHandlerAicarus"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        data = action_seg.data
        message_id = data.get("message_id")

        # 目标从 conversation_info 里拿，这才是标准做法！
        conv_info = event.conversation_info

        if not message_id:
            return False, "转发失败：你得告诉我转发哪条消息 (缺少 message_id)。", {}

        if not conv_info or not conv_info.conversation_id:
            return False, "转发失败：你得告诉我转发到哪儿去 (缺少会话信息)。", {}

        if not send_handler.server_connection:
            return False, "和 Napcat 的连接断开了，发不了。", {}

        try:
            response = None
            if conv_info.type == ConversationType.PRIVATE:
                logger.info(
                    f"正在将消息 {message_id} 转发给好友 {conv_info.conversation_id}..."
                )
                response = await napcat_forward_friend_single_msg(
                    send_handler.server_connection,
                    conv_info.conversation_id,
                    message_id,
                )
            elif conv_info.type == ConversationType.GROUP:
                logger.info(
                    f"正在将消息 {message_id} 转发到群 {conv_info.conversation_id}..."
                )
                response = await napcat_forward_group_single_msg(
                    send_handler.server_connection,
                    conv_info.conversation_id,
                    message_id,
                )
            else:
                return (
                    False,
                    f"不支持向 '{conv_info.type}' 类型的会话转发单条消息。",
                    {},
                )

            # Napcat 这两个 API 成功时好像不返回什么有用的东西，我们就简单判断一下
            if response is not None:
                # 这里假设调用成功API会返回一个非None的字典（即使是空的）
                # 失败或超时在_call_napcat_api里处理过了，会返回None
                return True, "单条消息转发指令已发送。", {}
            else:
                return False, "转发失败：Napcat API 调用失败或无响应。", {}

        except (ValueError, TypeError):
            return (
                False,
                f"无效的 message_id 或会话ID: {message_id}, {conv_info.conversation_id}",
                {},
            )
        except Exception as e:
            logger.error(f"执行单条消息转发时出现异常: {e}", exc_info=True)
            return False, f"执行单条消息转发时出现异常: {e}", {}


# 现在 key 是 Core 发来的动作别名。
ACTION_HANDLERS: Dict[str, BaseActionHandler] = {
    "recall_message": RecallMessageHandler(),
    "poke_user": PokeUserHandler(),
    "handle_friend_request": HandleFriendRequestHandler(),
    "get_group_info": GetGroupInfoHandler(),
    "handle_group_request": HandleGroupRequestHandler(),
    "get_bot_profile": GetBotProfileHandler(),
    "send_forward_message": SendForwardMessageHandler(),
    "kick_member": GroupKickHandler(),
    "ban_member": GroupBanHandler(),
    "ban_all_members": GroupWholeBanHandler(),
    "set_member_card": GroupCardHandler(),
    "set_member_title": GroupSpecialTitleHandler(),
    "leave_conversation": GroupLeaveHandler(),
    "sign_in": GroupSignInHandler(),
    "set_status": SetBotStatusHandler(),
    "set_avatar": SetBotAvatarHandler(),
    "get_history": GetHistoryHandler(),
    "get_list": GetListHandler(),
    "forward_single_message": ForwardSingleMessageHandler(),
}


def get_action_handler(action_alias: str) -> Optional[BaseActionHandler]:
    """根据动作别名，从名录中取出对应的玩法"""
    return ACTION_HANDLERS.get(action_alias)
