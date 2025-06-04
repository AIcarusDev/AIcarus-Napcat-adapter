# AIcarus Napcat Adapter - Send Handler for Protocol v1.4.0
# aicarus_napcat_adapter/src/send_handler_aicarus_v1_4_0.py
from typing import List, Dict, Any, Optional
import json
import uuid
import websockets
import asyncio

# 项目内部模块
from .logger import logger

# 修正：从 .message_queue 导入 get_napcat_api_response
from .message_queue import get_napcat_api_response

# AIcarus 协议库 v1.4.0
from aicarus_protocols import (
    Event,
    Seg,
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

        if not aicarus_event.content or not isinstance(aicarus_event.content, list):
            logger.error(
                "AIcarus Adapter Send: Invalid action event format. content should be a list of Seg objects."
            )
            return

        action_results: List[Dict[str, Any]] = []  # 用于未来可能的 action_response

        for content_seg in aicarus_event.content:
            if isinstance(content_seg, dict):
                action_seg = Seg.from_dict(content_seg)
            else:
                action_seg = content_seg

            action_type = action_seg.type
            action_data = action_seg.data

            logger.info(
                f"AIcarus Adapter Send: Processing action seg: type='{action_type}', data='{action_data}'"
            )

            original_action_type_for_response = action_type
            success = False
            details_for_response: Dict[str, Any] = {}
            error_message = ""

            try:
                if action_type == "send_message":
                    target_user_id = action_data.get("target_user_id")
                    target_group_id = action_data.get("target_group_id")

                    # 如果 action_data 中没有明确指定，则尝试从事件上下文中获取
                    if not target_user_id and not target_group_id:
                        logger.debug(
                            "send_message action did not have explicit target, using context from event"
                        )
                        if aicarus_event.user_info and aicarus_event.user_info.user_id:
                            target_user_id = aicarus_event.user_info.user_id
                        if (
                            aicarus_event.conversation_info
                            and aicarus_event.conversation_info.conversation_id
                        ):
                            if (
                                aicarus_event.conversation_info.type
                                == ConversationType.GROUP
                            ):
                                target_group_id = (
                                    aicarus_event.conversation_info.conversation_id
                                )

                    napcat_segments_to_send = (
                        await self._aicarus_seglist_to_napcat_array(
                            action_data.get("segments", [])
                        )
                    )

                    if not napcat_segments_to_send:
                        logger.warning(
                            "AIcarus Adapter Send: No segments to send for send_message action."
                        )
                        error_message = "No valid segments to send."
                    elif target_group_id:
                        napcat_action = "send_group_msg"
                        params = {
                            "group_id": int(target_group_id),  # Napcat 通常需要 int
                            "message": napcat_segments_to_send,
                        }

                        # 处理回复 (如果 action_data 中有 reply_to_message_id)
                        if action_data.get("reply_to_message_id"):
                            # Napcat 的回复段通常放在消息数组的开头
                            napcat_segments_to_send.insert(
                                0,
                                {
                                    "type": NapcatSegType.reply,
                                    "data": {
                                        "id": str(
                                            action_data.get("reply_to_message_id")
                                        )
                                    },
                                },
                            )
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
                                response.get(
                                    "message", "Napcat API error for send_group_msg"
                                )
                                if response
                                else "No response from Napcat API"
                            )
                    elif target_user_id:
                        napcat_action = "send_private_msg"
                        params = {
                            "user_id": int(target_user_id),  # Napcat 通常需要 int
                            "message": napcat_segments_to_send,
                        }
                        if action_data.get("reply_to_message_id"):
                            napcat_segments_to_send.insert(
                                0,
                                {
                                    "type": NapcatSegType.reply,
                                    "data": {
                                        "id": str(
                                            action_data.get("reply_to_message_id")
                                        )
                                    },
                                },
                            )
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
                                response.get(
                                    "message", "Napcat API error for send_private_msg"
                                )
                                if response
                                else "No response from Napcat API"
                            )
                    else:
                        logger.error(
                            "AIcarus Adapter Send: send_message missing target_user_id or target_group_id even after checking context."
                        )
                        error_message = "Missing target_user_id or target_group_id."

                elif action_type == "delete_message":
                    target_message_id = str(action_data.get("target_message_id", ""))
                    if target_message_id:
                        # Napcat 的 message_id 通常是整数
                        response = await self._send_to_napcat_api(
                            "delete_msg", {"message_id": int(target_message_id)}
                        )
                        success = response and response.get("status") == "ok"
                        if not success:
                            error_message = (
                                response.get(
                                    "message", "Napcat API error for delete_msg"
                                )
                                if response
                                else "No response from Napcat API"
                            )
                    else:
                        error_message = "Missing target_message_id for delete_message."

                elif action_type == "send_poke":
                    target_uid_str = action_data.get("target_user_id")
                    target_gid_str = action_data.get("target_group_id")  # May be None

                    if target_uid_str:
                        target_uid = int(target_uid_str)  # Napcat API needs int
                        params = {"user_id": target_uid}

                        if target_gid_str:
                            params["group_id"] = int(target_gid_str)

                        logger.debug(
                            f"AIcarus Adapter Send: Executing poke with params: {params}"
                        )
                        response = await self._send_to_napcat_api("send_poke", params)
                        success = response and response.get("status") == "ok"
                        if not success:
                            error_message = (
                                response.get(
                                    "message", "Napcat API error for send_poke"
                                )
                                if response
                                else "No response from Napcat API"
                            )
                    else:
                        error_message = "Missing target_user_id for send_poke."
                        logger.warning(f"AIcarus Adapter Send: {error_message}")

                elif action_type == "handle_friend_request":
                    request_flag = str(action_data.get("request_flag", ""))
                    approve = bool(action_data.get("approve", False))
                    remark = action_data.get("remark")  # Optional
                    if request_flag:
                        params_fh = {"flag": request_flag, "approve": approve}
                        if approve and remark:
                            params_fh["remark"] = remark
                        response = await self._send_to_napcat_api(
                            "set_friend_add_request", params_fh
                        )
                        success = response and response.get("status") == "ok"
                        if not success:
                            error_message = (
                                response.get(
                                    "message",
                                    "Napcat API error for set_friend_add_request",
                                )
                                if response
                                else "No response from Napcat API"
                            )
                    else:
                        error_message = (
                            "Missing request_flag for handle_friend_request."
                        )

                elif action_type == "handle_group_request":
                    request_flag = str(action_data.get("request_flag", ""))
                    # Napcat's API uses 'sub_type' for 'add' or 'invite'
                    # 'request_type' from Aicarus protocol needs to be mapped.
                    aicarus_req_type = action_data.get(
                        "request_type"
                    )  # e.g., "join_application" or "invite_received"

                    napcat_sub_type_for_api = ""
                    if (
                        aicarus_req_type == "join_application"
                    ):  # User wants to join group
                        napcat_sub_type_for_api = "add"
                    elif (
                        aicarus_req_type == "invite_received"
                    ):  # Bot was invited to group
                        napcat_sub_type_for_api = "invite"
                    else:
                        error_message = f"Unknown request_type '{aicarus_req_type}' for handle_group_request."
                        logger.warning(f"AIcarus Adapter Send: {error_message}")
                        # Fall through to action_results append with success=False

                    if not error_message and request_flag:  # Proceed if no error so far
                        approve = bool(action_data.get("approve", False))
                        reason = action_data.get("reason")  # Optional, for rejection
                        params_gh = {
                            "flag": request_flag,
                            "sub_type": napcat_sub_type_for_api,
                            "approve": approve,
                        }
                        if not approve and reason:
                            params_gh["reason"] = reason
                        response = await self._send_to_napcat_api(
                            "set_group_add_request", params_gh
                        )
                        success = response and response.get("status") == "ok"
                        if not success:
                            error_message = (
                                response.get(
                                    "message",
                                    "Napcat API error for set_group_add_request",
                                )
                                if response
                                else "No response from Napcat API"
                            )
                    elif not error_message:  # request_flag was missing
                        error_message = "Missing request_flag for handle_group_request."

                else:
                    logger.warning(
                        f"AIcarus Adapter Send: Unsupported action_type '{action_type}'."
                    )
                    error_message = f"Unsupported action_type: {action_type}"

            except Exception as e:
                logger.error(
                    f"AIcarus Adapter Send: Error processing action '{action_type}': {e}",
                    exc_info=True,
                )
                error_message = str(e)
                success = False  # Ensure success is false on exception

            # Log result of each action
            if success:
                logger.info(
                    f"AIcarus Adapter Send: Action '{original_action_type_for_response}' executed successfully. Details: {details_for_response}"
                )
            else:
                logger.error(
                    f"AIcarus Adapter Send: Action '{original_action_type_for_response}' failed. Error: {error_message}"
                )

            action_results.append(
                {
                    "original_action_type": original_action_type_for_response,
                    "status": "success" if success else "failure",
                    "details": details_for_response
                    if success
                    else None,  # Only include details on success
                    "error_message": error_message
                    if not success
                    else None,  # Only include error_message on failure
                    "error_code": None,  # Napcat doesn't usually provide distinct error codes in this way
                }
            )

        # TODO: Optional: Send action_response back to Core
        # This would involve constructing a new Event with event_type="action_response.adapter.napcat"
        # and content containing Seg(type="action_result", data=...) for each result.
        # For now, we are just logging the results in the adapter.

    async def _aicarus_seglist_to_napcat_array(
        self,
        aicarus_segments: List[Any],  # Segments can be dicts or Seg objects
    ) -> List[Dict[str, Any]]:
        """将 AIcarus 的 Seg 列表转换为 Napcat 消息段数组"""
        napcat_message_array: List[Dict[str, Any]] = []

        for aicarus_seg_obj in aicarus_segments:
            aicarus_seg_dict = (
                aicarus_seg_obj
                if isinstance(aicarus_seg_obj, dict)
                else aicarus_seg_obj.to_dict()
            )

            aicarus_type = aicarus_seg_dict.get("type", "")
            aicarus_data = aicarus_seg_dict.get("data", {})

            logger.debug(
                f"AIcarus Adapter Send: Converting AIcarus seg: type='{aicarus_type}', data='{aicarus_data}'"
            )

            # Skip message metadata segments as they are not sent to Napcat
            if aicarus_type == "message_metadata":
                logger.debug("AIcarus Adapter Send: Skipping message_metadata segment")
                continue

            if aicarus_type == "text":
                # aicarus_data for text should be like {"text": "Actual text content"}
                # but protocol also allows data to be a direct string for simple text Seg
                text_to_send = ""
                if isinstance(
                    aicarus_data, str
                ):  # Direct string in data field (older Seg style)
                    text_to_send = aicarus_data
                elif isinstance(aicarus_data, dict) and "text" in aicarus_data:
                    text_to_send = str(aicarus_data.get("text", ""))
                else:  # Fallback or error
                    text_to_send = str(
                        aicarus_data
                    )  # Convert whatever is there to string
                    logger.warning(
                        f"AIcarus Adapter Send: Unexpected data format for text segment: {aicarus_data}"
                    )

                napcat_message_array.append(
                    {"type": NapcatSegType.text, "data": {"text": text_to_send}}
                )

            elif aicarus_type == "image":
                image_file = aicarus_data.get("file")
                if image_file:
                    napcat_data = {"file": image_file}
                    # Add optional fields if available
                    if aicarus_data.get("url"):
                        napcat_data["url"] = aicarus_data.get("url")
                    if aicarus_data.get("type"):
                        napcat_data["type"] = aicarus_data.get("type")
                    napcat_message_array.append(
                        {"type": NapcatSegType.image, "data": napcat_data}
                    )
                else:
                    logger.warning(
                        f"AIcarus Adapter Send: image segment missing file field: {aicarus_data}"
                    )

            elif aicarus_type == "at":
                user_id = aicarus_data.get("user_id", "")
                if user_id:
                    napcat_message_array.append(
                        {
                            "type": NapcatSegType.at,
                            "data": {"qq": str(user_id)},  # Napcat uses 'qq' field
                        }
                    )
                else:
                    logger.warning(
                        f"AIcarus Adapter Send: at segment missing user_id: {aicarus_data}"
                    )

            elif aicarus_type == "face":
                face_id = aicarus_data.get("face_id")
                if face_id is not None:
                    napcat_message_array.append(
                        {
                            "type": NapcatSegType.face,
                            "data": {"id": str(face_id)},
                        }
                    )
                else:
                    logger.warning(
                        f"AIcarus Adapter Send: face segment missing face_id: {aicarus_data}"
                    )

            elif aicarus_type == "voice":
                voice_file = aicarus_data.get("file")
                if voice_file:
                    napcat_data = {"file": voice_file}
                    # Add optional fields if available
                    if aicarus_data.get("url"):
                        napcat_data["url"] = aicarus_data.get("url")
                    napcat_message_array.append(
                        {"type": NapcatSegType.record, "data": napcat_data}
                    )
                else:
                    logger.warning(
                        f"AIcarus Adapter Send: voice segment missing file field: {aicarus_data}"
                    )

            elif aicarus_type == "video":
                video_file = aicarus_data.get("file")
                if video_file:
                    napcat_data = {"file": video_file}
                    # Add optional fields if available
                    if aicarus_data.get("url"):
                        napcat_data["url"] = aicarus_data.get("url")
                    napcat_message_array.append(
                        {"type": NapcatSegType.video, "data": napcat_data}
                    )
                else:
                    logger.warning(
                        f"AIcarus Adapter Send: video segment missing file field: {aicarus_data}"
                    )

            elif aicarus_type == "json_card":
                json_content = aicarus_data.get("content", "{}")
                napcat_message_array.append(
                    {"type": NapcatSegType.json, "data": {"data": json_content}}
                )

            elif aicarus_type == "xml_card":
                xml_content = aicarus_data.get("content", "")
                napcat_message_array.append(
                    {"type": NapcatSegType.xml, "data": {"data": xml_content}}
                )

            elif aicarus_type == "share":
                share_data = {
                    "url": aicarus_data.get("url", ""),
                    "title": aicarus_data.get("title", ""),
                }
                if aicarus_data.get("content"):
                    share_data["content"] = aicarus_data.get("content")
                if aicarus_data.get("image_url"):
                    share_data["image"] = aicarus_data.get("image_url")
                napcat_message_array.append(
                    {"type": NapcatSegType.share, "data": share_data}
                )

            else:
                logger.warning(
                    f"AIcarus Adapter Send: Unsupported AIcarus seg type '{aicarus_type}'. Data: {aicarus_data}"
                )
                # Convert unknown segments to text as fallback
                napcat_message_array.append(
                    {
                        "type": NapcatSegType.text,
                        "data": {"text": f"[不支持的段类型: {aicarus_type}]"},
                    }
                )
                continue

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
            response = await get_napcat_api_response(
                request_uuid
            )  # This function handles its own timeout
            logger.debug(
                f"AIcarus Adapter Send: Response from Napcat API for {action} (echo: {request_uuid}): {response}"
            )
            if not isinstance(response, dict):  # Ensure response is a dict
                logger.error(
                    f"AIcarus Adapter Send: Napcat API response for {action} is not a dict: {response}"
                )
                return {
                    "status": "error",
                    "retcode": -103,
                    "message": "Invalid response format from Napcat",
                    "data": None,
                }
            return response  # Return the full response dict
        except asyncio.TimeoutError:
            logger.error(
                f"AIcarus Adapter Send: Timeout waiting for Napcat response for action {action} (echo: {request_uuid})."
            )
            return {
                "status": "error",
                "retcode": -2,  # Consistent with message_queue's timeout error
                "message": "Timeout waiting for Napcat response",
                "data": None,
            }
        except Exception as e:  # Catch other exceptions from get_napcat_api_response or during processing
            logger.error(
                f"AIcarus Adapter Send: Exception during Napcat API call {action} (echo: {request_uuid}): {e}",
                exc_info=True,
            )
            return {
                "status": "error",
                "retcode": -3,
                "message": f"Exception: {e}",
                "data": None,
            }


# 全局实例
send_handler_aicarus = SendHandlerAicarus()
