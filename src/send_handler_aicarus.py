# AIcarus Napcat Adapter - Send Handler for Protocol v1.4.0
# aicarus_napcat_adapter/src/send_handler_aicarus.py
from typing import List, Dict, Any, Optional
import json
import uuid
import websockets # type: ignore
import asyncio

# 项目内部模块
from .logger import logger

# 修正：从 .message_queue 导入 get_napcat_api_response
from .message_queue import get_napcat_api_response

# AIcarus 协议库 v1.4.0
from aicarus_protocols import (
    Event,
    Seg,
    ConversationInfo, # 导入 ConversationInfo
    UserInfo,         # 导入 UserInfo
    ConversationType,
)
from .napcat_definitions import NapcatSegType  # Napcat 消息段类型定义


class SendHandlerAicarus:
    server_connection: Optional[websockets.WebSocketServerProtocol] = None

    async def handle_aicarus_action(self, raw_aicarus_event_dict: dict) -> None:
        """处理从 Core 收到的 AIcarus Event (应为 action 类型)"""
        if not self.server_connection:
            logger.error(
                "AIcarus Adapter Send: Napcat server_connection is not available."
            )
            return

        try:
            aicarus_event = Event.from_dict(raw_aicarus_event_dict)
        except Exception as e:
            logger.error(f"AIcarus Adapter Send: Failed to parse Event from dict: {e}")
            logger.error(f"Received dict: {raw_aicarus_event_dict}")
            return

        # 检查是否为 action 事件
        if not aicarus_event.event_type.startswith("action."):
            logger.warning(
                f"AIcarus Adapter Send: Received non-action event, ignoring. Event type: {aicarus_event.event_type}"
            )
            return

        logger.info(
            f"AIcarus Adapter Send: Received action event from Core. Event ID: {aicarus_event.event_id}, Type: {aicarus_event.event_type}"
        )
        logger.debug(
            f"AIcarus Adapter Send: Full action event: {aicarus_event.to_dict()}"
        )

        # 主事件类型，例如 "action.message.send", "action.message.recall"
        event_main_type = aicarus_event.event_type
        action_results: List[Dict[str, Any]] = [] # 用于未来可能的 action_response

        success = False # 初始化成功状态
        details_for_response: Dict[str, Any] = {} # 初始化响应详情
        error_message = "" # 初始化错误消息
        # original_action_type_for_response 应为事件的主类型
        original_action_type_for_response = event_main_type

        try:
            # 根据主事件类型进行分发处理
            if event_main_type == "action.message.send":
                logger.info(
                    f"AIcarus Adapter Send: Processing event_type '{event_main_type}'."
                )
                # 从 conversation_info 获取目标信息
                target_user_id: Optional[str] = None
                target_group_id: Optional[str] = None
                
                # 优先从 conversation_info 中获取目标
                if aicarus_event.conversation_info:
                    conv_info = aicarus_event.conversation_info
                    if conv_info.type == ConversationType.GROUP:
                        target_group_id = conv_info.conversation_id
                    elif conv_info.type == ConversationType.PRIVATE:
                        target_user_id = conv_info.conversation_id
                    # 可以根据需要添加对其他会话类型（如频道）的处理
                    logger.debug(f"Target from conversation_info: group_id={target_group_id}, user_id={target_user_id}")

                # 如果 conversation_info 中没有明确的目标，并且是私聊场景，尝试从 user_info 获取
                # 注意：action.message.send 的目标通常由 conversation_info 指定。
                # user_info 在 action 事件中通常指执行动作的用户（如果相关）或为null。
                # 但为了兼容某些场景或旧逻辑，可以保留一个回退检查。
                if not target_group_id and not target_user_id:
                    if aicarus_event.user_info and aicarus_event.user_info.user_id:
                        # 假设如果 conversation_info 未指定类型，但 user_info 存在，则可能是私聊
                        # 但这依赖于Core如何构造事件，更规范的是依赖 conversation_info.type
                        logger.warning(
                            "action.message.send: conversation_info did not yield a target. "
                            f"Falling back to user_info.user_id ({aicarus_event.user_info.user_id}) as potential private chat target. "
                            "It's recommended that Core explicitly sets conversation_info for send actions."
                        )
                        # target_user_id = aicarus_event.user_info.user_id # 谨慎使用此回退

                # "action.message.send" 事件的 content 就是要发送的消息段列表
                segments_to_send_aicarus: List[Seg] = []
                if isinstance(aicarus_event.content, list):
                    for seg_data in aicarus_event.content:
                        if isinstance(seg_data, dict):
                            segments_to_send_aicarus.append(Seg.from_dict(seg_data))
                        elif isinstance(seg_data, Seg): # 如果已经是Seg对象
                            segments_to_send_aicarus.append(seg_data)
                        else:
                            logger.warning(f"Skipping invalid segment data in action.message.send content: {type(seg_data)}")
                
                if not segments_to_send_aicarus: # 检查转换后是否有有效的Seg对象
                     logger.warning(
                        "AIcarus Adapter Send: No valid Seg objects found in content for action.message.send."
                    )
                     error_message = "No valid Seg objects to process for sending."


                napcat_segments_to_send = await self._aicarus_seglist_to_napcat_array(
                    segments_to_send_aicarus
                )

                if not error_message and not napcat_segments_to_send: # 如果之前没有错误，但转换后为空
                    logger.warning(
                        "AIcarus Adapter Send: No segments to send after conversion for action.message.send."
                    )
                    error_message = "No valid segments to send after conversion."
                
                if not error_message: # 只有在没有预设错误的情况下才继续
                    if target_group_id:
                        napcat_action = "send_group_msg"
                        params = {
                            "group_id": int(target_group_id),
                            "message": napcat_segments_to_send,
                        }
                        logger.debug(
                            f"AIcarus Adapter Send: Calling Napcat API '{napcat_action}' with params: {params}"
                        )
                        response = await self._send_to_napcat_api(napcat_action, params)
                        if response and response.get("status") == "ok":
                            success = True
                            details_for_response["sent_message_id"] = str(
                                response.get("data", {}).get("message_id", "")
                            )
                        else:
                            error_message = (
                                response.get("message", "Napcat API error for send_group_msg") # type: ignore
                                if response
                                else "No response from Napcat API"
                            )
                    elif target_user_id:
                        napcat_action = "send_private_msg"
                        params = {
                            "user_id": int(target_user_id),
                            "message": napcat_segments_to_send,
                        }
                        logger.debug(
                            f"AIcarus Adapter Send: Calling Napcat API '{napcat_action}' with params: {params}"
                        )
                        response = await self._send_to_napcat_api(napcat_action, params)
                        if response and response.get("status") == "ok":
                            success = True
                            details_for_response["sent_message_id"] = str(
                                response.get("data", {}).get("message_id", "")
                            )
                        else:
                            error_message = (
                                response.get("message", "Napcat API error for send_private_msg") # type: ignore
                                if response
                                else "No response from Napcat API"
                            )
                    else:
                        logger.error(
                            "AIcarus Adapter Send: action.message.send missing target_user_id or target_group_id from conversation_info or user_info fallback."
                        )
                        error_message = "Missing target_user_id or target_group_id for send_message action."
            
            # 处理其他类型的 action 事件
            # 这类事件的 aicarus_event.content 预计包含一个定义具体动作的 Seg
            elif aicarus_event.content and isinstance(aicarus_event.content, list) and len(aicarus_event.content) > 0:
                action_definition_seg_raw = aicarus_event.content[0] # 获取第一个（且应该是唯一一个）定义动作的Seg
                action_definition_seg: Seg
                if isinstance(action_definition_seg_raw, dict):
                    action_definition_seg = Seg.from_dict(action_definition_seg_raw)
                elif isinstance(action_definition_seg_raw, Seg):
                     action_definition_seg = action_definition_seg_raw
                else:
                    logger.error(f"Invalid action definition segment type: {type(action_definition_seg_raw)}")
                    error_message = "Invalid action definition segment format."
                    # 跳过后续处理，因为无法解析动作定义
                    raise ValueError(error_message)


                # 这个Seg的type字段是具体要执行的动作类型，例如 "action.message.recall"
                specific_action_type_from_seg = action_definition_seg.type
                action_data_from_seg = action_definition_seg.data
                original_action_type_for_response = specific_action_type_from_seg # 更新用于响应日志的动作类型

                logger.info(
                    f"AIcarus Adapter Send: Processing specific action from Seg: type='{specific_action_type_from_seg}', data='{action_data_from_seg}'"
                )

                if specific_action_type_from_seg == "action.message.recall":
                    target_message_id = str(action_data_from_seg.get("target_message_id", ""))
                    if target_message_id:
                        # Napcat 的 message_id 通常是整数
                        response = await self._send_to_napcat_api(
                            "delete_msg", {"message_id": int(target_message_id)}
                        )
                        success = response and response.get("status") == "ok"
                        if not success:
                            error_message = (
                                response.get("message", "Napcat API error for delete_msg") # type: ignore
                                if response
                                else "No response from Napcat API"
                            )
                    else:
                        error_message = "Missing target_message_id for action.message.recall."

                elif specific_action_type_from_seg == "action.user.poke":
                    target_uid_str = action_data_from_seg.get("target_user_id")
                    if not target_uid_str and aicarus_event.user_info:
                        target_uid_str = aicarus_event.user_info.user_id
                    
                    target_gid_str = action_data_from_seg.get("target_group_id")
                    if not target_gid_str and aicarus_event.conversation_info and aicarus_event.conversation_info.type == ConversationType.GROUP:
                        target_gid_str = aicarus_event.conversation_info.conversation_id

                    if target_uid_str:
                        target_uid = int(target_uid_str)
                        napcat_action_name = "" # 初始化为空
                        params_poke: Dict[str, Any] = {"user_id": target_uid}

                        if target_gid_str: # 如果是群聊戳一戳
                            napcat_action_name = "group_poke" # <--- 修改点1：使用正确的群聊戳一戳 action
                            params_poke["group_id"] = int(target_gid_str)
                        else: # 如果是私聊戳一戳
                            napcat_action_name = "friend_poke" # <--- 修改点2：使用正确的私聊戳一戳 action
                            # 私聊戳一戳不需要 group_id，params_poke 中已正确只包含 user_id
                        
                        logger.debug(
                            f"AIcarus Adapter Send: Executing poke with action '{napcat_action_name}' and params: {params_poke}"
                        )
                        # 调用 Napcat API，传入修正后的 action 名称
                        response = await self._send_to_napcat_api(napcat_action_name, params_poke) 
                        success = response and response.get("status") == "ok"
                        if not success:
                            error_message = (
                                response.get("message", f"Napcat API error for {napcat_action_name}") # type: ignore
                                if response
                                else "No response from Napcat API"
                            )
                    else:
                        error_message = "Missing target_user_id for action.user.poke."
                        logger.warning(f"AIcarus Adapter Send: {error_message}")
                
                elif specific_action_type_from_seg == "action.request.friend.approve" or \
                     specific_action_type_from_seg == "action.request.friend.reject":
                    request_flag = str(action_data_from_seg.get("request_flag", ""))
                    approve_action = specific_action_type_from_seg == "action.request.friend.approve"
                    remark = action_data_from_seg.get("remark") # Optional

                    if request_flag:
                        params_fh = {"flag": request_flag, "approve": approve_action}
                        if approve_action and remark:
                            params_fh["remark"] = remark
                        response = await self._send_to_napcat_api(
                            "set_friend_add_request", params_fh
                        )
                        success = response and response.get("status") == "ok"
                        if not success:
                            error_message = (
                                response.get("message", "Napcat API error for set_friend_add_request") # type: ignore
                                if response
                                else "No response from Napcat API"
                            )
                    else:
                        error_message = f"Missing request_flag for {specific_action_type_from_seg}."

                elif specific_action_type_from_seg == "action.request.conversation.approve" or \
                     specific_action_type_from_seg == "action.request.conversation.reject":
                    request_flag = str(action_data_from_seg.get("request_flag", ""))
                    # Core 应该在 action_data_from_seg 中提供原始请求的类型，例如 "join_application" 或 "invite_received"
                    # 这个字段可以命名为 "original_request_sub_type" 或类似的
                    core_original_request_sub_type = action_data_from_seg.get("original_request_sub_type") 
                    
                    napcat_sub_type_for_api = ""
                    if core_original_request_sub_type == "join_application": # 用户申请加群
                        napcat_sub_type_for_api = "add"
                    elif core_original_request_sub_type == "invite_received": # Bot被邀请入群
                        napcat_sub_type_for_api = "invite"
                    else:
                        error_message = f"Unknown original_request_sub_type '{core_original_request_sub_type}' for {specific_action_type_from_seg}."
                        logger.warning(f"AIcarus Adapter Send: {error_message}")
                    
                    if not error_message and request_flag:
                        approve_action = specific_action_type_from_seg == "action.request.conversation.approve"
                        reason = action_data_from_seg.get("reason") # Optional, for rejection

                        params_gh: Dict[str, Any] = {
                            "flag": request_flag,
                            "sub_type": napcat_sub_type_for_api,
                            "approve": approve_action,
                        }
                        if not approve_action and reason:
                            params_gh["reason"] = reason
                        
                        response = await self._send_to_napcat_api(
                            "set_group_add_request", params_gh
                        )
                        success = response and response.get("status") == "ok"
                        if not success:
                            error_message = (
                                response.get("message", "Napcat API error for set_group_add_request") # type: ignore
                                if response
                                else "No response from Napcat API"
                            )
                    elif not error_message: # request_flag was missing
                        error_message = f"Missing request_flag for {specific_action_type_from_seg}."
                
                # 在这里添加更多 elif 块来处理其他特定动作类型
                # 例如：action.conversation.kick_user, action.conversation.mute_user 等。
                # 确保 specific_action_type_from_seg 字符串与 Seg 的 type 字段匹配。

                else:
                    logger.warning(
                        f"AIcarus Adapter Send: Unsupported specific action type from Seg: '{specific_action_type_from_seg}'."
                    )
                    error_message = f"Unsupported specific action type from Seg: {specific_action_type_from_seg}"
            else:
                # 如果 event_main_type 不是 "action.message.send"，并且 content 无效
                logger.error(
                    f"AIcarus Adapter Send: Invalid action event format. Event type '{event_main_type}' "
                    f"but content is empty, not a list, or does not contain a valid action definition Seg."
                )
                error_message = "Invalid action event content for non-send_message action."

        except Exception as e:
            logger.error(
                f"AIcarus Adapter Send: Error processing action event '{aicarus_event.event_type}': {e}",
                exc_info=True,
            )
            error_message = str(e)
            success = False  # 确保在异常时 success 为 false

        # 记录每个动作的结果
        if success:
            logger.info(
                f"AIcarus Adapter Send: Action '{original_action_type_for_response}' executed successfully. Details: {details_for_response}"
            )
        else:
            logger.error(
                f"AIcarus Adapter Send: Action '{original_action_type_for_response}' failed. Error: {error_message}"
            )

        # TODO: 可选: 将 action_response 发送回 Core
        # 这将涉及构造一个新的 Event，其 event_type="action_response.adapter.napcat"
        # 并且 content 包含一个 Seg(type="action_result", data=...)
        # 目前，我们只是在适配器中记录结果。
        # action_results.append(...) 逻辑可以根据需要添加回来，如果决定发送聚合响应。

    async def _aicarus_seglist_to_napcat_array(
        self,
        aicarus_segments: List[Any],  # Segments can be dicts or Seg objects
    ) -> List[Dict[str, Any]]:
        """将 AIcarus 的 Seg 列表转换为 Napcat 消息段数组"""
        napcat_message_array: List[Dict[str, Any]] = []

        for aicarus_seg_obj in aicarus_segments:
            aicarus_seg: Seg
            if isinstance(aicarus_seg_obj, dict):
                aicarus_seg = Seg.from_dict(aicarus_seg_obj)
            elif isinstance(aicarus_seg_obj, Seg):
                aicarus_seg = aicarus_seg_obj
            else:
                logger.warning(f"AIcarus Adapter Send: Invalid segment object type in list: {type(aicarus_seg_obj)}")
                continue # 跳过无效的段类型

            aicarus_type = aicarus_seg.type
            aicarus_data = aicarus_seg.data

            logger.debug(
                f"AIcarus Adapter Send: Converting AIcarus seg: type='{aicarus_type}', data='{aicarus_data}'"
            )

            # 跳过消息元数据段，因为它们不直接发送给Napcat作为消息内容
            if aicarus_type == "message_metadata": # 协议中为 "message_metadata"
                logger.debug("AIcarus Adapter Send: Skipping message_metadata segment as it's not part of sendable content.")
                continue
            
            # 新增：处理回复段 (reply Seg)
            if aicarus_type == "reply":
                reply_message_id = aicarus_data.get("message_id")
                if reply_message_id:
                    napcat_message_array.append(
                        {
                            "type": NapcatSegType.reply, # Napcat 的回复类型
                            "data": {"id": str(reply_message_id)},
                        }
                    )
                else:
                    logger.warning(f"AIcarus Adapter Send: reply segment missing message_id: {aicarus_data}")
                continue # 回复段处理完毕，继续下一个 aicarus_seg

            if aicarus_type == "text":
                text_to_send = str(aicarus_data.get("text", "")) # 确保总是字符串
                napcat_message_array.append(
                    {"type": NapcatSegType.text, "data": {"text": text_to_send}}
                )

            elif aicarus_type == "image":
                # Napcat 的图片段通常需要 'file' 字段，可以是本地路径、URL或Base64
                # AIcarus 的 image Seg 有 url, file_id, base64 等
                # 我们需要决定优先使用哪个，或者如何组合
                # 假设 Napcat 的 'file' 字段可以接受 URL 或 base64 (前缀 "base64://")
                image_file_source: Optional[str] = None
                if "base64" in aicarus_data and aicarus_data["base64"]:
                    image_file_source = f"base64://{aicarus_data['base64']}"
                elif "url" in aicarus_data and aicarus_data["url"]:
                    image_file_source = aicarus_data["url"]
                elif "file_id" in aicarus_data and aicarus_data["file_id"]: # 如果是平台文件ID
                    image_file_source = aicarus_data["file_id"] # Napcat 可能可以直接用
                
                if image_file_source:
                    napcat_img_data: Dict[str, Any] = {"file": image_file_source}
                    # Napcat 可能有其他可选字段，如 type (flash), subType 等，AIcarus Seg 中没有直接对应
                    # 如果 AIcarus Seg 的 data 中有额外兼容 Napcat 的字段，可以添加
                    if "is_flash" in aicarus_data and aicarus_data["is_flash"]:
                         napcat_img_data["type"] = "flash" # 示例，具体看Napcat API

                    napcat_message_array.append(
                        {"type": NapcatSegType.image, "data": napcat_img_data}
                    )
                else:
                    logger.warning(
                        f"AIcarus Adapter Send: image segment missing a usable source (url, base64, or file_id): {aicarus_data}"
                    )

            elif aicarus_type == "at":
                user_id = aicarus_data.get("user_id", "")
                if user_id:
                    napcat_message_array.append(
                        {
                            "type": NapcatSegType.at,
                            "data": {"qq": str(user_id)},  # Napcat 使用 'qq' 字段
                        }
                    )
                else:
                    logger.warning(
                        f"AIcarus Adapter Send: at segment missing user_id: {aicarus_data}"
                    )

            elif aicarus_type == "face":
                # AIcarus Seg 的 face data 中可能有 'id' 或 'face_id'
                face_id_val = aicarus_data.get("id") or aicarus_data.get("face_id")
                if face_id_val is not None:
                    napcat_message_array.append(
                        {
                            "type": NapcatSegType.face,
                            "data": {"id": str(face_id_val)},
                        }
                    )
                else:
                    logger.warning(
                        f"AIcarus Adapter Send: face segment missing id/face_id: {aicarus_data}"
                    )

            elif aicarus_type == "record": # AIcarus 使用 "record" 表示语音
                # 类似图片，需要确定 Napcat record 段的 'file' 字段接受什么
                voice_file_source: Optional[str] = None
                if "base64" in aicarus_data and aicarus_data["base64"]:
                    voice_file_source = f"base64://{aicarus_data['base64']}"
                elif "url" in aicarus_data and aicarus_data["url"]:
                    voice_file_source = aicarus_data["url"]
                elif "file_id" in aicarus_data and aicarus_data["file_id"]:
                    voice_file_source = aicarus_data["file_id"]

                if voice_file_source:
                    napcat_voice_data: Dict[str, Any] = {"file": voice_file_source}
                    if "magic" in aicarus_data: # Napcat 可能支持变声
                        napcat_voice_data["magic"] = aicarus_data["magic"]
                    napcat_message_array.append(
                        {"type": NapcatSegType.record, "data": napcat_voice_data}
                    )
                else:
                    logger.warning(
                        f"AIcarus Adapter Send: record (voice) segment missing a usable source: {aicarus_data}"
                    )
            
            # 确保与协议文档中的 Seg 类型名称一致
            elif aicarus_type == "video": # 假设 AIcarus Seg type 是 "video"
                video_file_source: Optional[str] = None
                if "base64" in aicarus_data and aicarus_data["base64"]:
                    video_file_source = f"base64://{aicarus_data['base64']}"
                elif "url" in aicarus_data and aicarus_data["url"]:
                    video_file_source = aicarus_data["url"]
                elif "file_id" in aicarus_data and aicarus_data["file_id"]:
                    video_file_source = aicarus_data["file_id"]
                
                if video_file_source:
                    napcat_video_data: Dict[str, Any] = {"file": video_file_source}
                    napcat_message_array.append(
                        {"type": NapcatSegType.video, "data": napcat_video_data}
                    )
                else:
                    logger.warning(
                        f"AIcarus Adapter Send: video segment missing a usable source: {aicarus_data}"
                    )

            elif aicarus_type == "json_card": # 协议中使用 "json_card"
                json_content = aicarus_data.get("content", "{}") # content 应为JSON字符串
                napcat_message_array.append(
                    {"type": NapcatSegType.json, "data": {"data": json_content}}
                )

            elif aicarus_type == "xml_card": # 协议中使用 "xml_card"
                xml_content = aicarus_data.get("content", "") # content 应为XML字符串
                napcat_message_array.append(
                    {"type": NapcatSegType.xml, "data": {"data": xml_content}}
                )

            elif aicarus_type == "share": # 协议中使用 "share"
                share_data_napcat = {
                    "url": aicarus_data.get("url", ""),
                    "title": aicarus_data.get("title", ""),
                }
                if "content" in aicarus_data: # 对应 Napcat 的 content (可选描述)
                    share_data_napcat["content"] = aicarus_data["content"]
                if "image_url" in aicarus_data: # 对应 Napcat 的 image (可选图片URL)
                    share_data_napcat["image"] = aicarus_data["image_url"]
                napcat_message_array.append(
                    {"type": NapcatSegType.share, "data": share_data_napcat}
                )

            else:
                logger.warning(
                    f"AIcarus Adapter Send: Unsupported AIcarus seg type '{aicarus_type}' for sending. Data: {aicarus_data}"
                )
                # 可以选择将不支持的段转换为文本或直接忽略
                napcat_message_array.append(
                    {
                        "type": NapcatSegType.text,
                        "data": {"text": f"[适配器不支持的段类型: {aicarus_type}]"},
                    }
                )
                continue # 跳到下一个 aicarus_seg

        logger.debug(
            f"AIcarus Adapter Send: Converted {len(aicarus_segments)} AIcarus segments to {len(napcat_message_array)} Napcat segments"
        )
        return napcat_message_array

    async def _send_to_napcat_api(self, action: str, params: dict) -> Optional[dict]:
        """发送API请求到Napcat，并等待响应"""
        if not self.server_connection:
            logger.error(
                f"AIcarus Adapter Send: Cannot send {action} - Napcat connection not available."
            )
            return {
                "status": "error",
                "retcode": -100,
                "message": "Napcat connection not available",
                "data": None,
            }

        request_uuid = str(uuid.uuid4())
        payload = {"action": action, "params": params, "echo": request_uuid}
        payload_str = json.dumps(payload)

        logger.debug(f"AIcarus Adapter Send: Sending request to Napcat: {payload_str}")

        try:
            await self.server_connection.send(payload_str)
        except websockets.exceptions.ConnectionClosed:
            logger.error(
                f"AIcarus Adapter Send: Napcat connection closed while trying to send API call {action}."
            )
            return {
                "status": "error",
                "retcode": -101,
                "message": "Connection closed during send",
                "data": None,
            }
        except Exception as e_send:
            logger.error(
                f"AIcarus Adapter Send: Exception while sending API call {action} to Napcat: {e_send}",
                exc_info=True,
            )
            return {
                "status": "error",
                "retcode": -102,
                "message": f"Send exception: {e_send}",
                "data": None,
            }

        try:
            # 增加超时时间，例如15秒
            response = await get_napcat_api_response(request_uuid, timeout_seconds=15.0)
            logger.debug(
                f"AIcarus Adapter Send: Response from Napcat API for {action} (echo: {request_uuid}): {response}"
            )
            if not isinstance(response, dict):  # 确保响应是字典
                logger.error(
                    f"AIcarus Adapter Send: Napcat API response for {action} is not a dict: {response}"
                )
                return {
                    "status": "error",
                    "retcode": -103,
                    "message": "Invalid response format from Napcat",
                    "data": None,
                }
            return response  # 返回完整的响应字典
        except asyncio.TimeoutError: # get_napcat_api_response 内部会处理超时并抛出 TimeoutError
            logger.error(
                f"AIcarus Adapter Send: Timeout waiting for Napcat response for action {action} (echo: {request_uuid})."
            )
            return {
                "status": "error",
                "retcode": -2,  # 与 message_queue 中的超时错误代码一致
                "message": "Timeout waiting for Napcat response",
                "data": None,
            }
        except Exception as e:  # 捕获 get_napcat_api_response 或处理过程中的其他异常
            logger.error(
                f"AIcarus Adapter Send: Exception during Napcat API call {action} (echo: {request_uuid}): {e}",
                exc_info=True,
            )
            return {
                "status": "error",
                "retcode": -3, # 通用异常代码
                "message": f"Exception: {e}",
                "data": None,
            }


# 全局实例
send_handler_aicarus = SendHandlerAicarus()
