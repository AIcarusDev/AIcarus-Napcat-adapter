# aicarus_napcat_adapter/src/action_definitions.py (v3.0 重构版)
from collections.abc import Awaitable, Callable

# 啊~ 还有我最色的小猫咪 SendHandler，得用 TYPE_CHECKING 抱着，免得循环依赖了
from typing import TYPE_CHECKING, Any

# 还有协议里的标准件，可不能忘了
from aicarus_protocols import Event, Seg

# 哼，从我们的小仓库里把神之手（工具函数）和神之眼（日志）都请出来！
from . import utils

if TYPE_CHECKING:
    from .send_handler_aicarus import SendHandlerAicarus


# ==============================================================================
# 1. 复杂动作处理器 (Complex Action Handlers)
# ==============================================================================
# 对于那些需要特殊逻辑、不能一概而论的“傲娇”动作，我们还是保留它们的专属处理类。
# 比如'send_forward_message'，它需要解析整个 event.content，很麻烦，得特殊对待。
# ------------------------------------------------------------------------------


class BaseComplexActionHandler:
    """复杂动作的基类，给它们一个统一的接口."""

    @staticmethod
    async def execute(
        params: dict[str, Any], event: Event, send_handler: "SendHandlerAicarus"
    ) -> tuple[bool, str, dict[str, Any]]:
        """执行复杂动作的逻辑."""
        raise NotImplementedError


class SendForwardMessageHandler(BaseComplexActionHandler):
    """处理合并转发消息的特殊逻辑."""

    @staticmethod
    async def execute(
        params: dict[str, Any], event: Event, send_handler: "SendHandlerAicarus"
    ) -> tuple[bool, str, dict[str, Any]]:
        """执行合并转发消息的逻辑."""
        # 合并转发的核心是 event.content 里的 'node' 列表，而不是 action_params
        nodes = [seg for seg in event.content if seg.type == "node"]
        if not nodes:
            return False, "发送合并转发失败：内容中必须包含 'node' 消息段。", {}

        # 转换所有节点
        napcat_nodes = []
        for node_seg in nodes:
            node_data = node_seg.data
            # 伪造的消息节点需要 user_id 和 nickname (Napcat 叫 uin 和 name)
            if "uin" in node_data and "name" in node_data:
                # 节点里的内容也得转换成Napcat格式
                napcat_content = await send_handler._aicarus_segs_to_napcat_array(
                    [Seg.from_dict(c) for c in node_data.get("content", [])]
                )
                napcat_nodes.append(
                    {
                        "user_id": str(node_data["uin"]),
                        "nickname": str(node_data["name"]),
                        "content": napcat_content,
                    }
                )
            # 真实消息转发只需要 message_id (Napcat 叫 id)
            elif "id" in node_data:
                napcat_nodes.append({"id": str(node_data["id"])})
            else:
                return (
                    False,
                    "发送合并转发失败：节点缺少必要字段 ('id' 或 'uin'/'name')。",
                    {},
                )

        # 确定是发给群还是私聊，现在从 params 里拿，多干净！
        target_group_id = params.get("group_id")
        target_user_id = params.get("user_id")

        api_params: dict[str, Any]
        napcat_action: str = "send_forward_msg"
        try:
            if target_group_id:
                api_params = {
                    "group_id": int(target_group_id),
                    "messages": napcat_nodes,
                }
            elif target_user_id:
                api_params = {"user_id": int(target_user_id), "messages": napcat_nodes}
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
        response = await send_handler._send_to_napcat_api(napcat_action, api_params)

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
                response.get("message", "Napcat API 错误") if response else "Napcat 没有回应我..."
            )
            return False, err_msg, {}


# 以后有其他复杂动作，就在这里加新的 Handler 类
# ...

# 最终的复杂动作处理器名录
COMPLEX_ACTION_HANDLERS: dict[str, BaseComplexActionHandler] = {
    "send_forward_message": SendForwardMessageHandler,
}


# ==============================================================================
# 2. 简单API调用映射 (Simple API Call Mapping)
# ==============================================================================
# 对于那些可以直接映射到 utils.py 中某个 napcat_ 函数的简单动作，
# 我们就用这个字典来登记！
# 格式: "动作别名": (对应的napcat函数, [必需的参数列表])
# ------------------------------------------------------------------------------

# 定义一个类型别名，让代码更清晰，这是天才的优雅！
# (Callable, List of required param names)
ActionMappingType = tuple[Callable[..., Awaitable[dict[str, Any] | None]], list[str]]

# 动作的“圣殿”，记载了所有神权（API）的咒语和贡品（必需参数）
ACTION_MAPPING: dict[str, ActionMappingType] = {
    # --- 群组管理 ---
    "kick_member": (utils.napcat_set_group_kick, ["group_id", "user_id"]),
    "ban_member": (utils.napcat_set_group_ban, ["group_id", "user_id"]),
    "ban_all_members": (utils.napcat_set_group_whole_ban, ["group_id", "enable"]),
    "set_member_card": (utils.napcat_set_group_card, ["group_id", "user_id", "card"]),
    "set_member_title": (
        utils.napcat_set_group_special_title,
        ["group_id", "user_id", "special_title"],
    ),
    "leave_conversation": (utils.napcat_set_group_leave, ["group_id"]),
    "set_admin": (utils.napcat_set_group_admin, ["group_id", "user_id", "enable"]),
    "set_conversation_name": (utils.napcat_set_group_name, ["group_id", "group_name"]),
    # --- 消息操作 ---
    "recall_message": (utils.napcat_delete_msg, ["message_id"]),
    "poke_user": (utils.napcat_send_poke, ["user_id"]),  # poke现在统一了
    "set_message_emoji_like": (
        utils.napcat_set_msg_emoji_like,
        ["message_id", "emoji_id"],
    ),
    "forward_single_message": (
        utils.napcat_forward_single_msg,
        ["target_id", "target_type", "message_id"],
    ),
    # --- 请求处理 ---
    "handle_friend_request": (utils.napcat_set_friend_add_request, ["flag", "approve"]),
    "handle_group_request": (
        utils.napcat_set_group_add_request,
        ["flag", "sub_type", "approve"],
    ),
    # --- 信息获取 ---
    "get_bot_profile": (
        utils.napcat_get_self_info,
        [],
    ),  # get_bot_profile 现在简化为获取自身信息
    "get_group_info": (utils.napcat_get_group_info, ["group_id"]),
    "get_member_info": (utils.napcat_get_member_info, ["group_id", "user_id"]),
    "get_stranger_info": (utils.napcat_get_stranger_info, ["user_id"]),
    "get_list": (utils.napcat_get_list, ["list_type"]),
    "get_history": (utils.napcat_get_history, ["conversation_id", "conversation_type"]),
    # --- 文件操作 ---
    "upload_group_file": (utils.napcat_upload_group_file, ["group_id", "file", "name"]),
    "delete_group_file": (
        utils.napcat_delete_group_file,
        ["group_id", "file_id", "busid"],
    ),
    "create_group_folder": (
        utils.napcat_create_group_file_folder,
        ["group_id", "name"],
    ),
    "delete_group_folder": (
        utils.napcat_delete_group_folder,
        ["group_id", "folder_id"],
    ),
    "get_group_files": (
        utils.napcat_get_group_files_by_folder,
        ["group_id"],
    ),  # 简化，默认查根目录或指定目录
    "get_group_file_url": (
        utils.napcat_get_group_file_url,
        ["group_id", "file_id", "busid"],
    ),
    # --- 其他功能 ---
    "sign_in": (utils.napcat_set_group_sign, ["group_id"]),
    "set_status": (utils.napcat_set_online_status, ["status"]),
    "set_avatar": (utils.napcat_set_qq_avatar, ["file"]),
    "get_group_honor_info": (utils.napcat_get_group_honor_info, ["group_id", "type"]),
    "send_group_notice": (utils.napcat_send_group_notice, ["group_id", "content"]),
    "get_group_notice": (utils.napcat_get_group_notice, ["group_id"]),
    "get_recent_contacts": (utils.napcat_get_recent_contact, []),
    "get_ai_characters": (utils.napcat_get_ai_characters, ["group_id"]),
    "send_ai_voice": (
        utils.napcat_send_group_ai_record,
        ["group_id", "character", "text"],
    ),
}
