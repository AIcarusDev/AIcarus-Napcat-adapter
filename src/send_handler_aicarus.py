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

        if not (
            aicarus_message.message_segment
            and aicarus_message.message_segment.type == "seglist"
            and isinstance(aicarus_message.message_segment.data, list)
        ):
            logger.error(
                "AIcarus Adapter Send: Invalid core_action format. message_segment should be a seglist of actions."
            )
            return

        action_results: List[Dict[str, Any]] = []

        for action_seg_obj in aicarus_message.message_segment.data:
            action_seg_dict = (
                action_seg_obj
                if isinstance(action_seg_obj, dict)
                else action_seg_obj.to_dict()
            )

            action_type = action_seg_dict.get("type", "")
            action_data = action_seg_dict.get("data", {})

            original_action_type_for_response = action_type
            success = False
            details_for_response: Dict[str, Any] = {}
            error_message = ""

            try:
                if action_type == "action:send_message":
                    target_user_id = action_data.get("target_user_id")
                    target_group_id = action_data.get("target_group_id")

                    if not target_user_id and not target_group_id:
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
                            "group_id": int(target_group_id),
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
                        response = await self._send_to_napcat_api(napcat_action, params)
                        if response.get("status") == "ok":
                            success = True
                            details_for_response["sent_message_id"] = str(
                                response.get("data", {}).get("message_id", "")
                            )
                        else:
                            error_message = response.get("message", "Napcat API error")
                    elif target_user_id:
                        napcat_action = "send_private_msg"
                        params = {
                            "user_id": int(target_user_id),
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
                        response = await self._send_to_napcat_api(napcat_action, params)
                        if response.get("status") == "ok":
                            success = True
                            details_for_response["sent_message_id"] = str(
                                response.get("data", {}).get("message_id", "")
                            )
                        else:
                            error_message = response.get("message", "Napcat API error")
                    else:
                        logger.error(
                            "AIcarus Adapter Send: action:send_message missing target_user_id or target_group_id."
                        )
                        error_message = "Missing target_user_id or target_group_id."

                elif action_type == "action:delete_message":
                    target_message_id = str(action_data.get("target_message_id", ""))
                    if target_message_id:
                        response = await self._send_to_napcat_api(
                            "delete_msg", {"message_id": int(target_message_id)}
                        )
                        success = response.get("status") == "ok"
                        if not success:
                            error_message = response.get(
                                "message", "Failed to delete message"
                            )
                    else:
                        error_message = "Missing target_message_id for delete_message."

                elif action_type == "action:handle_friend_request":
                    request_flag = str(action_data.get("request_flag", ""))
                    approve = bool(action_data.get("approve", False))
                    remark = action_data.get("remark")
                    if request_flag:
                        params_fh = {"flag": request_flag, "approve": approve}
                        if approve and remark:
                            params_fh["remark"] = remark
                        response = await self._send_to_napcat_api(
                            "set_friend_add_request", params_fh
                        )
                        success = response.get("status") == "ok"
                        if not success:
                            error_message = response.get(
                                "message", "Failed to handle friend request"
                            )
                    else:
                        error_message = (
                            "Missing request_flag for handle_friend_request."
                        )

                elif action_type == "action:handle_group_request":
                    request_flag = str(action_data.get("request_flag", ""))
                    aicarus_req_type = action_data.get("request_type")
                    napcat_sub_type_for_api = (
                        "add" if aicarus_req_type == "join_application" else "invite"
                    )
                    approve = bool(action_data.get("approve", False))
                    reason = action_data.get("reason")
                    if request_flag:
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
                        success = response.get("status") == "ok"
                        if not success:
                            error_message = response.get(
                                "message", "Failed to handle group request"
                            )
                    else:
                        error_message = "Missing request_flag for handle_group_request."

                elif action_type == "action:poke":
                    target_uid = str(action_data.get("target_user_id", ""))
                    target_gid = str(action_data.get("target_group_id"))
                    if target_uid and target_gid:
                        response = await self._send_to_napcat_api(
                            "send_group_poke",
                            {"group_id": int(target_gid), "user_id": int(target_uid)},
                        )
                        success = response.get("status") == "ok"
                        if not success:
                            error_message = response.get("message", "Group poke failed")
                    elif target_uid:
                        response = await self._send_to_napcat_api(
                            "send_friend_poke", {"user_id": int(target_uid)}
                        )
                        success = response.get("status") == "ok"
                        if not success:
                            error_message = response.get(
                                "message", "Friend poke failed"
                            )
                    else:
                        error_message = "Missing target_user_id for poke."
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
                success = False

            action_results.append(
                {
                    "original_action_type": original_action_type_for_response,
                    "status": "success" if success else "failure",
                    "details": details_for_response if success else None,
                    "error_message": error_message if not success else None,
                    "error_code": None,
                }
            )
        # Optional: Send action_response back to Core (code for this would go here)

    async def _aicarus_seglist_to_napcat_array(
        self, aicarus_segments: List[Any]
    ) -> List[Dict[str, Any]]:
        napcat_array: List[Dict[str, Any]] = []
        if not isinstance(aicarus_segments, list):
            logger.warning(
                f"AIcarus Adapter Send: Expected list of segments, got {type(aicarus_segments)}"
            )
            return napcat_array

        for aicarus_s_any in aicarus_segments:
            if isinstance(aicarus_s_any, Seg):
                aicarus_s = aicarus_s_any.to_dict()
            elif isinstance(aicarus_s_any, dict):
                aicarus_s = aicarus_s_any
            else:
                logger.warning(
                    f"AIcarus Adapter Send: Segment is not a dict or Seg object: {type(aicarus_s_any)}"
                )
                continue

            napcat_seg_obj: Optional[Dict[str, Any]] = None
            aicarus_type = aicarus_s.get("type", "")
            aicarus_data = aicarus_s.get("data", {})

            if aicarus_type == "text":
                if isinstance(aicarus_data, str):
                    napcat_seg_obj = {
                        "type": NapcatSegType.text,
                        "data": {"text": aicarus_data},
                    }
                else:
                    napcat_seg_obj = {
                        "type": NapcatSegType.text,
                        "data": {"text": str(aicarus_data)},
                    }
            elif aicarus_type == "image":
                napcat_img_data: Dict[str, Any] = {}
                if isinstance(aicarus_data, dict):
                    if aicarus_data.get("base64"):
                        napcat_img_data["file"] = f"base64://{aicarus_data['base64']}"
                    elif aicarus_data.get("url"):
                        napcat_img_data["file"] = aicarus_data["url"]
                    elif aicarus_data.get("file_id"):
                        napcat_img_data["file"] = aicarus_data["file_id"]
                    if aicarus_data.get("is_flash"):
                        napcat_img_data["type"] = "flash"
                    if aicarus_data.get("is_sticker"):
                        napcat_img_data["subType"] = 1
                    else:
                        napcat_img_data["subType"] = 0
                    if "file" in napcat_img_data:
                        napcat_seg_obj = {
                            "type": NapcatSegType.image,
                            "data": napcat_img_data,
                        }
                else:
                    napcat_seg_obj = {
                        "type": NapcatSegType.image,
                        "data": {"file": f"base64://{aicarus_data}", "subType": 0},
                    }
            elif aicarus_type == "face":
                if isinstance(aicarus_data, dict) and "face_id" in aicarus_data:
                    napcat_seg_obj = {
                        "type": NapcatSegType.face,
                        "data": {"id": str(aicarus_data["face_id"])},
                    }
            elif aicarus_type == "at":
                if isinstance(aicarus_data, dict) and "user_id" in aicarus_data:
                    napcat_seg_obj = {
                        "type": NapcatSegType.at,
                        "data": {"qq": str(aicarus_data["user_id"])},
                    }
            elif aicarus_type == "reply":
                logger.warning(
                    "AIcarus Adapter Send: 'reply' segment found mid-list, usually handled at the start. Ignoring for now."
                )
                pass
            elif aicarus_type == "voice":
                napcat_voice_data: Dict[str, Any] = {}
                if isinstance(aicarus_data, dict):
                    if aicarus_data.get("base64"):
                        napcat_voice_data["file"] = f"base64://{aicarus_data['base64']}"
                    elif aicarus_data.get("url"):
                        napcat_voice_data["file"] = aicarus_data["url"]
                    elif aicarus_data.get("file_id"):
                        napcat_voice_data["file"] = aicarus_data["file_id"]
                    if "file" in napcat_voice_data:
                        napcat_seg_obj = {
                            "type": NapcatSegType.record,
                            "data": napcat_voice_data,
                        }
            elif aicarus_type == "json_card" and isinstance(aicarus_data, dict):
                napcat_seg_obj = {
                    "type": NapcatSegType.json,
                    "data": {"data": aicarus_data.get("content", "{}")},
                }
            elif aicarus_type == "xml_card" and isinstance(aicarus_data, dict):
                napcat_seg_obj = {
                    "type": NapcatSegType.xml,
                    "data": {"data": aicarus_data.get("content", "")},
                }
            elif aicarus_type == "share" and isinstance(aicarus_data, dict):
                napcat_share_data = {
                    "url": aicarus_data.get("url", ""),
                    "title": aicarus_data.get("title", ""),
                }
                if aicarus_data.get("content"):
                    napcat_share_data["content"] = aicarus_data.get("content")
                if aicarus_data.get("image_url"):
                    napcat_share_data["image"] = aicarus_data.get("image_url")
                napcat_seg_obj = {
                    "type": NapcatSegType.share,
                    "data": napcat_share_data,
                }
            else:
                logger.warning(
                    f"AIcarus Adapter Send: Cannot convert Aicarus Seg type '{aicarus_type}' to Napcat segment."
                )
                if isinstance(aicarus_data, str):
                    napcat_seg_obj = {
                        "type": NapcatSegType.text,
                        "data": {
                            "text": f"[Unsupported Aicarus Seg: {aicarus_type} Data: {aicarus_data}]"
                        },
                    }
                elif isinstance(aicarus_data, dict) and "text" in aicarus_data:
                    napcat_seg_obj = {
                        "type": NapcatSegType.text,
                        "data": {
                            "text": f"[Unsupported Aicarus Seg: {aicarus_type} Data: {aicarus_data.get('text')}]"
                        },
                    }
                else:
                    napcat_seg_obj = {
                        "type": NapcatSegType.text,
                        "data": {"text": f"[Unsupported Aicarus Seg: {aicarus_type}]"},
                    }
            if napcat_seg_obj:
                napcat_array.append(napcat_seg_obj)
        return napcat_array

    async def _send_to_napcat_api(self, action: str, params: dict) -> dict:
        if not self.server_connection:
            logger.error(
                "AIcarus Adapter Send: Napcat connection not available for API call."
            )
            return {
                "status": "error",
                "retcode": -1,
                "message": "Napcat connection unavailable",
            }

        request_uuid = str(uuid.uuid4())
        payload_str = json.dumps(
            {"action": action, "params": params, "echo": request_uuid}
        )
        logger.debug(
            f"AIcarus Adapter Send: Sending to Napcat API -> Action: {action}, Params: {params}"
        )

        await self.server_connection.send(payload_str)
        try:
            # 使用修正后的函数名
            response = await get_napcat_api_response(request_uuid)
            logger.debug(
                f"AIcarus Adapter Send: Response from Napcat API for {action} ({request_uuid}): {response}"
            )
            return response
        except asyncio.TimeoutError:  # get_napcat_api_response 会抛出 TimeoutError
            logger.error(
                f"AIcarus Adapter Send: Timeout waiting for Napcat response for action {action} (echo: {request_uuid})."
            )
            return {
                "status": "error",
                "retcode": -2,
                "message": "Timeout waiting for Napcat response",
            }
        except Exception as e:
            logger.error(
                f"AIcarus Adapter Send: Exception during Napcat API call {action}: {e}",
                exc_info=True,
            )
            return {"status": "error", "retcode": -3, "message": f"Exception: {e}"}


send_handler_aicarus = SendHandlerAicarus()
