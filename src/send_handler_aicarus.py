# aicarus_napcat_adapter/src/send_handler_aicarus.py
import asyncio
import json
import websockets  # 添加导入
import uuid
from typing import List, Dict, Any, Optional

# 项目内部模块
from .logger import logger

# 修正：从 .message_queue 导入 get_napcat_api_response
from .message_queue import get_napcat_api_response

# AIcarus 协议库
from aicarus_protocols import MessageBase, Seg  # 确保你从你的协议库导入这些
from .napcat_definitions import NapcatSegType  # Napcat 消息段类型定义


class SendHandlerAicarus:
    server_connection: Optional[websockets.WebSocketServerProtocol] = None

    async def handle_aicarus_action(self, raw_aicarus_message_dict: dict) -> None:
        """处理从 Core 收到的 AIcarus MessageBase (应为 core_action)"""
        if not self.server_connection:
            logger.error(
                "AIcarus Adapter Send: Napcat server_connection is not available."
            )
            return

        try:
            aicarus_message = MessageBase.from_dict(raw_aicarus_message_dict)
        except Exception as e:
            logger.error(
                f"AIcarus Adapter Send: Failed to parse MessageBase from dict: {e}"
            )
            logger.error(f"Received dict: {raw_aicarus_message_dict}")
            return

        if aicarus_message.message_info.interaction_purpose != "core_action":
            logger.warning(
                f"AIcarus Adapter Send: Received non-core_action message, ignoring. Purpose: {aicarus_message.message_info.interaction_purpose}"
            )
            return

        logger.info(
            f"AIcarus Adapter Send: Received core_action from Core. Message ID: {aicarus_message.message_info.message_id}"
        )
        logger.debug(f"AIcarus Adapter Send: Full action message: {aicarus_message.to_dict()}")


        if not (
            aicarus_message.message_segment
            and aicarus_message.message_segment.type == "seglist"
            and isinstance(aicarus_message.message_segment.data, list)
        ):
            logger.error(
                "AIcarus Adapter Send: Invalid core_action format. message_segment should be a seglist of actions."
            )
            return

        action_results: List[Dict[str, Any]] = [] # 用于未来可能的 action_response

        for action_seg_obj in aicarus_message.message_segment.data:
            action_seg_dict = (
                action_seg_obj
                if isinstance(action_seg_obj, dict)
                else action_seg_obj.to_dict()
            )

            action_type = action_seg_dict.get("type", "")
            action_data = action_seg_dict.get("data", {})

            logger.info(f"AIcarus Adapter Send: Processing action seg: type='{action_type}', data='{action_data}'")

            original_action_type_for_response = action_type
            success = False
            details_for_response: Dict[str, Any] = {}
            error_message = ""

            try:
                if action_type == "action:send_message":
                    target_user_id = action_data.get("target_user_id")
                    target_group_id = action_data.get("target_group_id")

                    # 如果 action_data 中没有明确指定，则尝试从 message_info 的上下文中获取
                    if not target_user_id and not target_group_id:
                        logger.debug("action:send_message did not have explicit target, using context from message_info")
                        if (
                            aicarus_message.message_info.user_info
                            and aicarus_message.message_info.user_info.user_id
                        ):
                            target_user_id = (
                                aicarus_message.message_info.user_info.user_id
                            )
                        if (
                            aicarus_message.message_info.group_info
                            and aicarus_message.message_info.group_info.group_id
                        ):
                            target_group_id = (
                                aicarus_message.message_info.group_info.group_id
                            )
                            # 如果有群目标，通常私聊目标会被忽略或不适用
                            if target_group_id:
                                target_user_id = None


                    napcat_segments_to_send = (
                        await self._aicarus_seglist_to_napcat_array(
                            action_data.get("segments", [])
                        )
                    )

                    if not napcat_segments_to_send:
                        logger.warning(
                            "AIcarus Adapter Send: No segments to send for action:send_message."
                        )
                        error_message = "No valid segments to send."
                    elif target_group_id:
                        napcat_action = "send_group_msg"
                        params = {
                            "group_id": int(target_group_id), # Napcat 通常需要 int
                            "message": napcat_segments_to_send,
                        }
                        # 处理回复 (如果 action_data 中有 reply_to_message_id)
                        if action_data.get("reply_to_message_id"):
                            # Napcat 的回复段通常放在消息数组的开头
                            napcat_segments_to_send.insert(
                                0,
                                {
                                    "type": NapcatSegType.reply, # 使用 Napcat 定义的 reply 类型
                                    "data": {
                                        "id": str( # Napcat 的 reply id 通常是字符串形式的消息ID
                                            action_data.get("reply_to_message_id")
                                        )
                                    },
                                },
                            )
                        logger.debug(f"AIcarus Adapter Send: Calling Napcat API '{napcat_action}' with params: {params}")
                        response = await self._send_to_napcat_api(napcat_action, params)
                        if response and response.get("status") == "ok":
                            success = True
                            details_for_response["sent_message_id"] = str(
                                response.get("data", {}).get("message_id", "")
                            )
                        else:
                            error_message = response.get("message", "Napcat API error for send_group_msg") if response else "No response from Napcat API"
                    elif target_user_id:
                        napcat_action = "send_private_msg"
                        params = {
                            "user_id": int(target_user_id), # Napcat 通常需要 int
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
                        logger.debug(f"AIcarus Adapter Send: Calling Napcat API '{napcat_action}' with params: {params}")
                        response = await self._send_to_napcat_api(napcat_action, params)
                        if response and response.get("status") == "ok":
                            success = True
                            details_for_response["sent_message_id"] = str(
                                response.get("data", {}).get("message_id", "")
                            )
                        else:
                            error_message = response.get("message", "Napcat API error for send_private_msg") if response else "No response from Napcat API"
                    else:
                        logger.error(
                            "AIcarus Adapter Send: action:send_message missing target_user_id or target_group_id even after checking context."
                        )
                        error_message = "Missing target_user_id or target_group_id."

                elif action_type == "action:delete_message":
                    target_message_id = str(action_data.get("target_message_id", ""))
                    if target_message_id:
                        # Napcat 的 message_id 通常是整数
                        response = await self._send_to_napcat_api(
                            "delete_msg", {"message_id": int(target_message_id)}
                        )
                        success = response and response.get("status") == "ok"
                        if not success:
                            error_message = response.get("message", "Failed to delete message") if response else "No response from Napcat API"
                    else:
                        error_message = "Missing target_message_id for delete_message."

                # 修改这里的 action_type 判断
                elif action_type == "action:send_poke": 
                    target_uid_str = action_data.get("target_user_id")
                    target_gid_str = action_data.get("target_group_id") # May be None

                    if target_uid_str:
                        target_uid = int(target_uid_str)  # Napcat API needs int
                        params = {"user_id": target_uid}

                        if target_gid_str:  # Group poke
                            target_gid = int(target_gid_str)
                            params["group_id"] = target_gid

                        logger.debug(f"AIcarus Adapter Send: Executing poke with params: {params}")
                        response = await self._send_to_napcat_api("send_poke", params)
                        success = response and response.get("status") == "ok"
                        if not success:
                            error_message = response.get("message", "Poke action failed") if response else "No response from Napcat API"
                    else:
                        error_message = "Missing target_user_id for send_poke."
                        logger.warning(f"AIcarus Adapter Send: {error_message}")


                elif action_type == "action:handle_friend_request":
                    request_flag = str(action_data.get("request_flag", ""))
                    approve = bool(action_data.get("approve", False))
                    remark = action_data.get("remark") # Optional
                    if request_flag:
                        params_fh = {"flag": request_flag, "approve": approve}
                        if approve and remark: # Only add remark if approving and remark is provided
                            params_fh["remark"] = remark
                        response = await self._send_to_napcat_api(
                            "set_friend_add_request", params_fh
                        )
                        success = response and response.get("status") == "ok"
                        if not success:
                            error_message = response.get("message", "Failed to handle friend request") if response else "No response from Napcat API"
                    else:
                        error_message = "Missing request_flag for handle_friend_request."

                elif action_type == "action:handle_group_request":
                    request_flag = str(action_data.get("request_flag", ""))
                    # Napcat's API uses 'sub_type' for 'add' or 'invite'
                    # 'request_type' from Aicarus protocol needs to be mapped.
                    aicarus_req_type = action_data.get("request_type") # e.g., "join_application" or "invite_received"
                    
                    napcat_sub_type_for_api = ""
                    if aicarus_req_type == "join_application": # User wants to join group
                        napcat_sub_type_for_api = "add"
                    elif aicarus_req_type == "invite_received": # Bot was invited to group
                        napcat_sub_type_for_api = "invite"
                    else:
                        error_message = f"Unknown request_type '{aicarus_req_type}' for handle_group_request."
                        logger.warning(f"AIcarus Adapter Send: {error_message}")
                        # Fall through to action_results append with success=False

                    if not error_message and request_flag: # Proceed if no error so far
                        approve = bool(action_data.get("approve", False))
                        reason = action_data.get("reason") # Optional, for rejection
                        params_gh = {
                            "flag": request_flag,
                            "sub_type": napcat_sub_type_for_api, # Mapped type
                            "approve": approve,
                        }
                        if not approve and reason: # Only add reason if rejecting and reason is provided
                            params_gh["reason"] = reason
                        response = await self._send_to_napcat_api(
                            "set_group_add_request", params_gh
                        )
                        success = response and response.get("status") == "ok"
                        if not success:
                            error_message = response.get("message", "Failed to handle group request") if response else "No response from Napcat API"
                    elif not error_message: # request_flag was missing
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
                success = False # Ensure success is false on exception

            # Log result of each action
            if success:
                logger.info(f"AIcarus Adapter Send: Action '{original_action_type_for_response}' executed successfully. Details: {details_for_response}")
            else:
                logger.error(f"AIcarus Adapter Send: Action '{original_action_type_for_response}' failed. Error: {error_message}")

            action_results.append(
                {
                    "original_action_type": original_action_type_for_response,
                    "status": "success" if success else "failure",
                    "details": details_for_response if success else None, # Only include details on success
                    "error_message": error_message if not success else None, # Only include error_message on failure
                    "error_code": None, # Napcat doesn't usually provide distinct error codes in this way
                }
            )
        
        # TODO: Optional: Send action_response back to Core
        # This would involve constructing a new AicarusMessageBase with interaction_purpose="action_response"
        # and message_segment containing Seg(type="action_result:[status]", data=...) for each result.
        # For now, we are just logging the results in the adapter.

    async def _aicarus_seglist_to_napcat_array(
        self, aicarus_segments: List[Any] # Segments can be dicts or Seg objects
    ) -> List[Dict[str, Any]]:
        napcat_array: List[Dict[str, Any]] = []
        if not isinstance(aicarus_segments, list):
            logger.warning(
                f"AIcarus Adapter Send: Expected list of segments, got {type(aicarus_segments)}"
            )
            return napcat_array

        for aicarus_s_any in aicarus_segments:
            # Ensure aicarus_s is a dictionary
            if isinstance(aicarus_s_any, Seg):
                aicarus_s = aicarus_s_any.to_dict()
            elif isinstance(aicarus_s_any, dict):
                aicarus_s = aicarus_s_any
            else:
                logger.warning(
                    f"AIcarus Adapter Send: Segment is not a dict or Seg object: {type(aicarus_s_any)}"
                )
                continue # Skip this segment

            napcat_seg_obj: Optional[Dict[str, Any]] = None
            aicarus_type = aicarus_s.get("type", "")
            aicarus_data = aicarus_s.get("data", {})

            if not isinstance(aicarus_data, dict) and aicarus_type not in ["text"]: # Text data can be str
                 logger.warning(f"AIcarus Adapter Send: Segment data for type '{aicarus_type}' is not a dict: {aicarus_data}. Skipping conversion for this segment.")
                 # Optionally, convert to a text representation of the error
                 napcat_array.append({
                     "type": NapcatSegType.text,
                     "data": {"text": f"[Error: Seg data for '{aicarus_type}' not a dict]"}
                 })
                 continue


            if aicarus_type == "text":
                # aicarus_data for text should be like {"text": "Actual text content"}
                # but protocol also allows data to be a direct string for simple text Seg
                text_to_send = ""
                if isinstance(aicarus_data, str): # Direct string in data field (older Seg style)
                    text_to_send = aicarus_data
                elif isinstance(aicarus_data, dict) and "text" in aicarus_data:
                    text_to_send = str(aicarus_data.get("text", ""))
                else: # Fallback or error
                    text_to_send = str(aicarus_data) # Convert whatever is there to string
                    logger.warning(f"AIcarus Adapter Send: Text segment data format unexpected: {aicarus_data}. Converted to string.")

                napcat_seg_obj = {
                    "type": NapcatSegType.text,
                    "data": {"text": text_to_send},
                }
            elif aicarus_type == "image":
                napcat_img_data: Dict[str, Any] = {}
                if aicarus_data.get("base64"): # Prioritize base64 if available
                    napcat_img_data["file"] = f"base64://{aicarus_data['base64']}"
                elif aicarus_data.get("url"):
                    napcat_img_data["file"] = aicarus_data["url"]
                elif aicarus_data.get("file_id"): # Platform-specific file ID
                    napcat_img_data["file"] = aicarus_data["file_id"]
                
                if "file" not in napcat_img_data:
                    logger.warning(f"AIcarus Adapter Send: Image segment missing 'file', 'url', or 'base64': {aicarus_data}")
                    continue # Skip this image segment

                if aicarus_data.get("is_flash"):
                    napcat_img_data["type"] = "flash" # Napcat specific field for flash image
                
                # Napcat uses subType for stickers (0 for normal image, 1 for sticker)
                napcat_img_data["subType"] = 1 if aicarus_data.get("is_sticker") else 0
                
                napcat_seg_obj = {
                    "type": NapcatSegType.image,
                    "data": napcat_img_data,
                }
            elif aicarus_type == "face":
                if "face_id" in aicarus_data:
                    napcat_seg_obj = {
                        "type": NapcatSegType.face,
                        "data": {"id": str(aicarus_data["face_id"])}, # Napcat uses 'id'
                    }
            elif aicarus_type == "at":
                if "user_id" in aicarus_data:
                    napcat_seg_obj = {
                        "type": NapcatSegType.at,
                        "data": {"qq": str(aicarus_data["user_id"])}, # Napcat uses 'qq'
                    }
            elif aicarus_type == "reply":
                # This should ideally be handled at the beginning of the segment list by send_message logic
                # If it appears mid-list, it's unusual for Napcat.
                logger.warning(
                    "AIcarus Adapter Send: 'reply' segment found mid-list during conversion. This is typically handled by send_message logic for Napcat."
                )
                # We could try to convert it, but it might not be placed correctly by Napcat if not first.
                # For now, let's skip it if it's not the first element (which is handled by send_message)
                # or convert it if we decide adapters should be robust to this.
                # if "message_id" in aicarus_data:
                #     napcat_seg_obj = {
                #         "type": NapcatSegType.reply,
                #         "data": {"id": str(aicarus_data["message_id"])},
                #     }
                pass # Let send_message logic handle prepending reply seg
            elif aicarus_type == "voice":
                napcat_voice_data: Dict[str, Any] = {}
                if aicarus_data.get("base64"):
                    napcat_voice_data["file"] = f"base64://{aicarus_data['base64']}"
                elif aicarus_data.get("url"):
                    napcat_voice_data["file"] = aicarus_data["url"]
                elif aicarus_data.get("file_id"):
                    napcat_voice_data["file"] = aicarus_data["file_id"]

                if "file" in napcat_voice_data:
                    napcat_seg_obj = {
                        "type": NapcatSegType.record, # Napcat uses 'record' for voice
                        "data": napcat_voice_data,
                    }
            elif aicarus_type == "json_card":
                napcat_seg_obj = {
                    "type": NapcatSegType.json,
                    "data": {"data": aicarus_data.get("content", "{}")},
                }
            elif aicarus_type == "xml_card":
                napcat_seg_obj = {
                    "type": NapcatSegType.xml,
                    "data": {"data": aicarus_data.get("content", "")},
                }
            elif aicarus_type == "share":
                napcat_share_data = {
                    "url": aicarus_data.get("url", ""),
                    "title": aicarus_data.get("title", "分享"), # Default title if missing
                }
                if aicarus_data.get("content"): # Optional description
                    napcat_share_data["content"] = aicarus_data.get("content")
                if aicarus_data.get("image_url"): # Optional image for the share
                    napcat_share_data["image"] = aicarus_data.get("image_url")
                napcat_seg_obj = {
                    "type": NapcatSegType.share,
                    "data": napcat_share_data,
                }
            else:
                logger.warning(
                    f"AIcarus Adapter Send: Cannot convert Aicarus Seg type '{aicarus_type}' to Napcat segment. Data: {aicarus_data}"
                )
                # Fallback to sending a text representation of the unsupported segment
                unsupported_text = f"[Unsupported Aicarus Seg: {aicarus_type}"
                if isinstance(aicarus_data, dict) and "text" in aicarus_data : # If data itself has text, use it
                     unsupported_text += f" Data: {aicarus_data.get('text')}"
                elif isinstance(aicarus_data, str):
                     unsupported_text += f" Data: {aicarus_data}"
                unsupported_text += "]"
                napcat_seg_obj = {
                    "type": NapcatSegType.text,
                    "data": {"text": unsupported_text},
                }
            
            if napcat_seg_obj:
                napcat_array.append(napcat_seg_obj)
        return napcat_array

    async def _send_to_napcat_api(self, action: str, params: dict) -> Optional[dict]: # Return Optional[dict]
        if not self.server_connection or self.server_connection.closed: # Check for closed connection
            logger.error(
                "AIcarus Adapter Send: Napcat connection not available for API call."
            )
            return { # Return a dict indicating error, consistent with other returns
                "status": "error",
                "retcode": -100, # Custom error code for connection issue
                "message": "Napcat connection unavailable",
                "data": None
            }

        request_uuid = str(uuid.uuid4())
        payload_str = json.dumps(
            {"action": action, "params": params, "echo": request_uuid}
        )
        logger.debug(
            f"AIcarus Adapter Send: Sending to Napcat API -> Action: {action}, Params: {params}, Echo: {request_uuid}"
        )

        try:
            await self.server_connection.send(payload_str)
        except websockets.exceptions.ConnectionClosed:
            logger.error(f"AIcarus Adapter Send: Napcat connection closed while trying to send API call {action}.")
            return {
                "status": "error", "retcode": -101, "message": "Connection closed during send", "data": None
            }
        except Exception as e_send:
            logger.error(f"AIcarus Adapter Send: Exception while sending API call {action} to Napcat: {e_send}", exc_info=True)
            return {
                "status": "error", "retcode": -102, "message": f"Send exception: {e_send}", "data": None
            }


        try:
            response = await get_napcat_api_response(request_uuid) # This function handles its own timeout
            logger.debug(
                f"AIcarus Adapter Send: Response from Napcat API for {action} (echo: {request_uuid}): {response}"
            )
            if not isinstance(response, dict): # Ensure response is a dict
                logger.error(f"AIcarus Adapter Send: Napcat API response for {action} is not a dict: {response}")
                return {"status":"error", "retcode": -103, "message": "Invalid response format from Napcat", "data": None}
            return response # Return the full response dict
        except asyncio.TimeoutError: 
            logger.error(
                f"AIcarus Adapter Send: Timeout waiting for Napcat response for action {action} (echo: {request_uuid})."
            )
            return {
                "status": "error",
                "retcode": -2, # Consistent with message_queue's timeout error
                "message": "Timeout waiting for Napcat response",
                "data": None
            }
        except Exception as e: # Catch other exceptions from get_napcat_api_response or during processing
            logger.error(
                f"AIcarus Adapter Send: Exception during Napcat API call {action} (echo: {request_uuid}): {e}",
                exc_info=True,
            )
            return {"status": "error", "retcode": -3, "message": f"Exception: {e}", "data": None}


send_handler_aicarus = SendHandlerAicarus()
