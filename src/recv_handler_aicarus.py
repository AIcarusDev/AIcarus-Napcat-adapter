# aicarus_napcat_adapter/src/recv_handler_aicarus.py
import time
import asyncio
import json
from typing import List, Optional, Dict, Any
import uuid
import websockets  # 添加导入

# 项目内部模块
from .logger import logger
from .config import global_config  # 或者 get_config() 后获取实例
from .qq_emoji_list import qq_face

# 修正 utils.py 的导入
from .utils import (
    napcat_get_group_info,  # 直接使用 napcat_ 前缀的名称
    napcat_get_member_info,
    napcat_get_self_info,
    napcat_get_forward_msg_content,  # 如果用到了
)
from .napcat_definitions import (
    MetaEventType,
    MessageType,
    NoticeType,
    NapcatSegType,
    AICARUS_PROTOCOL_VERSION,
)

# AIcarus 协议库
from aicarus_protocols import (
    UserInfo as AicarusUserInfo,
    GroupInfo as AicarusGroupInfo,
    Seg as AicarusSeg,
    BaseMessageInfo as AicarusBaseMessageInfo,
    MessageBase as AicarusMessageBase,
)


class RecvHandlerAicarus:
    maibot_router: Any  # Type hint for Router, will be set by main
    server_connection: Optional[websockets.WebSocketServerProtocol] = None
    last_heart_beat: float = 0.0
    napcat_bot_id: Optional[str] = None  # 存储机器人自身的QQ号

    def __init__(self):
        # 确保从 config 模块获取配置实例
        cfg = global_config  # 或者 cfg = get_config()
        self.interval = cfg.napcat_heartbeat_interval_seconds

    async def _get_bot_id(self) -> Optional[str]:
        """获取并缓存机器人自身的ID"""
        if self.napcat_bot_id:
            return self.napcat_bot_id
        if self.server_connection:
            # 使用正确的函数名
            self_info = await napcat_get_self_info(self.server_connection)
            if self_info and self_info.get("user_id"):
                self.napcat_bot_id = str(self_info.get("user_id"))
                return self.napcat_bot_id
        return None

    async def _napcat_to_aicarus_userinfo(
        self, napcat_user_obj: dict, group_id: Optional[str] = None
    ) -> AicarusUserInfo:
        """将 Napcat 用户对象转换为 AIcarus UserInfo"""
        user_id = str(napcat_user_obj.get("user_id", ""))
        nickname = napcat_user_obj.get("nickname")
        cardname = napcat_user_obj.get("card")

        permission_level = None
        role = None
        title = None

        if group_id and user_id and self.server_connection:
            # 使用正确的函数名
            member_data = await napcat_get_member_info(
                self.server_connection, group_id, user_id
            )
            if member_data:
                cardname = member_data.get("card") or cardname
                nickname = member_data.get("nickname") or nickname
                title = member_data.get("title")
                napcat_role = member_data.get("role")
                if napcat_role == "owner":
                    permission_level = "owner"
                    role = "owner"
                elif napcat_role == "admin":
                    permission_level = "admin"
                    role = "admin"
                else:
                    permission_level = "member"
                    role = "member"

        cfg = global_config  # 或者 cfg = get_config()
        return AicarusUserInfo(
            platform=cfg.core_platform_id,  # 或者一个更通用的平台名如 "qq"
            user_id=user_id,
            user_nickname=nickname,
            user_cardname=cardname,
            user_titlename=title,
            permission_level=permission_level,
            role=role,
            additional_data=napcat_user_obj.get("additional_data", {}),
        )

    async def _napcat_to_aicarus_groupinfo(
        self, napcat_group_id: str
    ) -> Optional[AicarusGroupInfo]:
        """将 Napcat 群ID 转换为 AIcarus GroupInfo (如果需要群名)"""
        if not self.server_connection:
            cfg = global_config
            return AicarusGroupInfo(
                platform=cfg.core_platform_id, group_id=napcat_group_id
            )

        # 使用正确的函数名
        group_data = await napcat_get_group_info(
            self.server_connection, napcat_group_id
        )
        group_name = group_data.get("group_name") if group_data else None
        cfg = global_config
        return AicarusGroupInfo(
            platform=cfg.core_platform_id,  # 或者 "qq"
            group_id=napcat_group_id,
            group_name=group_name,
        )

    async def handle_meta_event(self, napcat_event: dict) -> None:
        event_type = napcat_event.get("meta_event_type")
        bot_id = (
            str(napcat_event.get("self_id"))
            or await self._get_bot_id()
            or "unknown_bot"
        )
        cfg = global_config
        aicarus_message_info = AicarusBaseMessageInfo(
            platform=cfg.core_platform_id,
            bot_id=bot_id,
            interaction_purpose="platform_meta",
            time=napcat_event.get("time", time.time()) * 1000.0,
            message_id=f"meta_{event_type}_{uuid.uuid4()}",
            additional_config={"protocol_version": AICARUS_PROTOCOL_VERSION},
        )

        meta_seg_data: Dict[str, Any] = {}
        meta_seg_type: str = "meta:unknown"

        if event_type == MetaEventType.lifecycle:
            sub_type = napcat_event.get("sub_type")
            meta_seg_type = "meta:lifecycle"
            meta_seg_data = {"lifecycle_type": sub_type}
            if sub_type == MetaEventType.Lifecycle.connect:
                self.napcat_bot_id = bot_id
                self.last_heart_beat = time.time()
                logger.info(f"AIcarus Adapter: Bot {bot_id} connected to Napcat.")
                asyncio.create_task(self.check_heartbeat(bot_id))
            meta_seg_data["details"] = {"adapter_platform": "napcat"}

        elif event_type == MetaEventType.heartbeat:
            meta_seg_type = "meta:heartbeat"
            status_obj = napcat_event.get("status", {})
            meta_seg_data = {
                "status_object": status_obj,
                "interval_ms": napcat_event.get("interval"),
                "is_online": status_obj.get("online", False)
                and status_obj.get("good", False),
            }
            if meta_seg_data["is_online"]:
                self.last_heart_beat = time.time()
                if napcat_event.get("interval"):
                    self.interval = napcat_event.get("interval") / 1000.0
            else:
                logger.warning(
                    f"AIcarus Adapter: Bot {bot_id} Napcat heartbeat status is not good."
                )
        else:
            logger.warning(
                f"AIcarus Adapter: Unknown Napcat meta_event_type: {event_type}"
            )
            meta_seg_type = f"meta:napcat_unknown_{event_type}"
            meta_seg_data = {"raw_napcat_event": napcat_event}

        aicarus_seg = AicarusSeg(type=meta_seg_type, data=meta_seg_data)
        aicarus_message = AicarusMessageBase(
            message_info=aicarus_message_info,
            message_segment=AicarusSeg(type="seglist", data=[aicarus_seg]),
            raw_message=json.dumps(napcat_event),
        )
        await self.dispatch_to_core(aicarus_message)

    async def check_heartbeat(self, bot_id: str) -> None:
        cfg = global_config
        while True:
            await asyncio.sleep(self.interval)
            if time.time() - self.last_heart_beat > self.interval + 5:
                logger.warning(
                    f"AIcarus Adapter: Bot {bot_id} Napcat connection might be lost (heartbeat timeout)."
                )
                disconnect_event_info = AicarusBaseMessageInfo(
                    platform=cfg.core_platform_id,
                    bot_id=bot_id,
                    interaction_purpose="platform_meta",
                    time=time.time() * 1000.0,
                    message_id=f"meta_disconnect_{uuid.uuid4()}",
                    additional_config={"protocol_version": AICARUS_PROTOCOL_VERSION},
                )
                disconnect_seg = AicarusSeg(
                    type="meta:lifecycle",
                    data={
                        "lifecycle_type": "disconnect",
                        "reason": "heartbeat_timeout",
                    },
                )
                disconnect_message = AicarusMessageBase(
                    message_info=disconnect_event_info,
                    message_segment=AicarusSeg(type="seglist", data=[disconnect_seg]),
                )
                await self.dispatch_to_core(disconnect_message)
                break
            else:
                logger.debug(f"AIcarus Adapter: Bot {bot_id} heartbeat check passed.")

    async def handle_message_event(self, napcat_event: dict) -> None:
        bot_id = (
            str(napcat_event.get("self_id"))
            or await self._get_bot_id()
            or "unknown_bot"
        )
        napcat_message_type = napcat_event.get("message_type")
        napcat_sub_type = napcat_event.get("sub_type")
        napcat_message_id = str(napcat_event.get("message_id", ""))

        aicarus_user_info: Optional[AicarusUserInfo] = None
        aicarus_group_info: Optional[AicarusGroupInfo] = None

        napcat_sender = napcat_event.get("sender", {})
        cfg = global_config

        if napcat_message_type == MessageType.private:
            aicarus_user_info = await self._napcat_to_aicarus_userinfo(napcat_sender)
            if napcat_sub_type == MessageType.Private.group:
                temp_group_id = str(napcat_event.get("group_id")) or str(
                    napcat_sender.get("group_id", "")
                )
                if temp_group_id:
                    aicarus_group_info = await self._napcat_to_aicarus_groupinfo(
                        temp_group_id
                    )
                else:
                    logger.warning(
                        "AIcarus Adapter: Group temporary chat missing group_id."
                    )
        elif napcat_message_type == MessageType.group:
            group_id = str(napcat_event.get("group_id", ""))
            aicarus_user_info = await self._napcat_to_aicarus_userinfo(
                napcat_sender, group_id=group_id
            )
            aicarus_group_info = await self._napcat_to_aicarus_groupinfo(group_id)
        else:
            logger.warning(
                f"AIcarus Adapter: Unknown Napcat message_type: {napcat_message_type}"
            )
            return

        aicarus_base_info = AicarusBaseMessageInfo(
            platform=cfg.core_platform_id,  # 使用配置中的 platform_id
            bot_id=bot_id,
            message_id=napcat_message_id,
            time=napcat_event.get("time", time.time()) * 1000.0,
            group_info=aicarus_group_info,
            user_info=aicarus_user_info,
            interaction_purpose="user_message",
            message_type=napcat_message_type,
            sub_type=napcat_sub_type,
            font=str(napcat_event.get("font"))
            if napcat_event.get("font") is not None
            else None,
            additional_config={"protocol_version": AICARUS_PROTOCOL_VERSION},
        )

        if napcat_sub_type == MessageType.Group.anonymous and napcat_event.get(
            "anonymous"
        ):
            aicarus_base_info.anonymity_info = napcat_event.get("anonymous")

        aicarus_seg_list = await self._napcat_to_aicarus_seglist(
            napcat_event.get("message", []), napcat_event
        )
        if not aicarus_seg_list:
            logger.warning(
                f"AIcarus Adapter: Message {napcat_message_id} content is empty or unparseable, skipping."
            )
            return

        aicarus_message = AicarusMessageBase(
            message_info=aicarus_base_info,
            message_segment=AicarusSeg(type="seglist", data=aicarus_seg_list),
            raw_message=napcat_event.get("raw_message") or json.dumps(napcat_event),
        )
        await self.dispatch_to_core(aicarus_message)

    async def _napcat_to_aicarus_seglist(
        self, napcat_message_array: list, full_napcat_event: dict
    ) -> List[AicarusSeg]:
        aicarus_segments: List[AicarusSeg] = []
        _bot_id = (
            str(full_napcat_event.get("self_id"))
            or await self._get_bot_id()
            or "unknown_bot"
        )

        for napcat_seg_obj in napcat_message_array:
            seg_type = napcat_seg_obj.get("type")
            seg_data = napcat_seg_obj.get("data", {})
            aicarus_s: Optional[AicarusSeg] = None

            if seg_type == NapcatSegType.text:
                aicarus_s = AicarusSeg(type="text", data=seg_data.get("text", ""))

            elif seg_type == NapcatSegType.face:
                face_id = str(seg_data.get("id", ""))
                face_name = qq_face.get(face_id, f"[未知表情:{face_id}]")
                aicarus_s = AicarusSeg(
                    type="face", data={"face_id": face_id, "name": face_name}
                )

            elif seg_type == NapcatSegType.image:
                image_url = seg_data.get("url")
                file_id = seg_data.get("file")
                is_flash = seg_data.get("type") == "flash"

                img_data_dict: Dict[str, Any] = {}
                if image_url:
                    img_data_dict["url"] = image_url
                    # 如果需要 base64，在这里调用 get_image_base64_from_url
                    # try:
                    #     img_data_dict["base64"] = await get_image_base64_from_url(image_url)
                    # except Exception as e_img:
                    #     logger.warning(f"Failed to get base64 for image {image_url}: {e_img}")
                if file_id:
                    img_data_dict["file_id"] = file_id
                if is_flash:
                    img_data_dict["is_flash"] = True

                if seg_data.get("subType") == 1 or seg_data.get("sub_type") == 1:
                    img_data_dict["is_sticker"] = True

                aicarus_s = AicarusSeg(type="image", data=img_data_dict)

            elif seg_type == NapcatSegType.at:
                at_user_id = str(seg_data.get("qq", ""))
                display_name = None
                if at_user_id == "all":
                    display_name = "@全体成员"
                elif (
                    full_napcat_event.get("message_type") == MessageType.group
                    and self.server_connection
                ):
                    group_id = str(full_napcat_event.get("group_id", ""))
                    # 使用正确的函数名
                    member_info = await napcat_get_member_info(
                        self.server_connection, group_id, at_user_id
                    )
                    if member_info:
                        display_name = f"@{member_info.get('card') or member_info.get('nickname') or at_user_id}"

                aicarus_s = AicarusSeg(
                    type="at",
                    data={"user_id": at_user_id, "display_name": display_name},
                )

            elif seg_type == NapcatSegType.reply:
                reply_msg_id = str(seg_data.get("id", ""))
                aicarus_s = AicarusSeg(type="reply", data={"message_id": reply_msg_id})

            elif seg_type == NapcatSegType.record:
                voice_data: Dict[str, Any] = {"file_id": seg_data.get("file")}
                if seg_data.get("url"):
                    voice_data["url"] = seg_data.get("url")
                aicarus_s = AicarusSeg(type="voice", data=voice_data)

            elif seg_type == NapcatSegType.forward:
                forward_id = seg_data.get("id")
                if forward_id and self.server_connection:
                    logger.info(
                        f"AIcarus Adapter: Fetching forward message content for id: {forward_id}"
                    )
                    # 使用正确的函数名
                    napcat_forward_messages = await napcat_get_forward_msg_content(
                        self.server_connection, forward_id
                    )
                    if napcat_forward_messages:
                        combined_forward_segs: List[AicarusSeg] = []
                        for fwd_msg_node in napcat_forward_messages:
                            sender_name = fwd_msg_node.get("sender", {}).get(
                                "nickname", "未知用户"
                            )
                            node_content_preview = ""
                            if fwd_msg_node.get("message"):
                                first_node_seg = fwd_msg_node["message"][0]
                                if first_node_seg.get("type") == "text":
                                    node_content_preview = first_node_seg.get(
                                        "data", {}
                                    ).get("text", "")[:30]
                                elif first_node_seg.get("type") == "image":
                                    node_content_preview = "[图片]"
                            combined_forward_segs.append(
                                AicarusSeg(
                                    type="text",
                                    data=f"\n-- {sender_name}: {node_content_preview} --\n",
                                )
                            )
                        if combined_forward_segs:
                            aicarus_s = AicarusSeg(
                                type="seglist", data=combined_forward_segs
                            )
                        else:
                            aicarus_s = AicarusSeg(
                                type="text",
                                data="[合并转发消息(内容为空或解析失败)]",
                            )
                    else:
                        aicarus_s = AicarusSeg(
                            type="text", data="[合并转发消息(无法获取内容)]"
                        )
                else:
                    aicarus_s = AicarusSeg(type="text", data="[合并转发消息]")

            elif seg_type == NapcatSegType.json:
                aicarus_s = AicarusSeg(
                    type="json_card", data={"content": seg_data.get("data", "{}")}
                )
            elif seg_type == NapcatSegType.xml:
                aicarus_s = AicarusSeg(
                    type="xml_card", data={"content": seg_data.get("data", "")}
                )
            elif seg_type == NapcatSegType.share:
                aicarus_s = AicarusSeg(
                    type="share",
                    data={
                        "url": seg_data.get("url", ""),
                        "title": seg_data.get("title", ""),
                        "content": seg_data.get("content"),
                        "image_url": seg_data.get("image"),
                    },
                )
            else:
                logger.warning(
                    f"AIcarus Adapter: Unsupported Napcat segment type '{seg_type}', data: {seg_data}"
                )
                aicarus_s = AicarusSeg(
                    type="text", data=f"[不支持的消息段: {seg_type}]"
                )

            if aicarus_s:
                aicarus_segments.append(aicarus_s)

        return aicarus_segments

    async def handle_notice_event(self, napcat_event: dict) -> None:
        bot_id = (
            str(napcat_event.get("self_id"))
            or await self._get_bot_id()
            or "unknown_bot"
        )
        napcat_notice_type = napcat_event.get("notice_type")
        cfg = global_config

        aicarus_interaction_purpose = "platform_notification"
        aicarus_seg_type_prefix = "notification"

        if napcat_notice_type == NoticeType.friend_add:
            aicarus_interaction_purpose = "platform_request"
            aicarus_seg_type_prefix = "request"
        elif (
            napcat_notice_type == NoticeType.group_increase
            and napcat_event.get("sub_type") == "invite"
        ):
            aicarus_interaction_purpose = "platform_request"
            aicarus_seg_type_prefix = "request"
        elif napcat_event.get("request_type"):
            aicarus_interaction_purpose = "platform_request"
            aicarus_seg_type_prefix = "request"

        aicarus_base_info = AicarusBaseMessageInfo(
            platform=cfg.core_platform_id,
            bot_id=bot_id,
            message_id=f"{aicarus_interaction_purpose}_{napcat_notice_type}_{uuid.uuid4()}",
            time=napcat_event.get("time", time.time()) * 1000.0,
            interaction_purpose=aicarus_interaction_purpose,
            additional_config={"protocol_version": AICARUS_PROTOCOL_VERSION},
        )

        napcat_group_id = (
            str(napcat_event.get("group_id")) if napcat_event.get("group_id") else None
        )
        napcat_user_id = (
            str(napcat_event.get("user_id")) if napcat_event.get("user_id") else None
        )
        napcat_operator_id = (
            str(napcat_event.get("operator_id"))
            if napcat_event.get("operator_id")
            else None
        )

        if napcat_group_id:
            aicarus_base_info.group_info = await self._napcat_to_aicarus_groupinfo(
                napcat_group_id
            )

        if napcat_user_id and self.server_connection:
            user_data_from_napcat = {"user_id": napcat_user_id}
            aicarus_base_info.user_info = await self._napcat_to_aicarus_userinfo(
                user_data_from_napcat, group_id=napcat_group_id
            )

        seg_data_dict: Dict[str, Any] = {"raw_napcat_event_fields": napcat_event.copy()}
        aicarus_final_seg_type = f"{aicarus_seg_type_prefix}:unknown"

        if napcat_notice_type == NoticeType.group_increase:
            aicarus_final_seg_type = f"{aicarus_seg_type_prefix}:group_member_increase"
            if napcat_user_id and self.server_connection:
                seg_data_dict[
                    "target_user_info"
                ] = await self._napcat_to_aicarus_userinfo(
                    {"user_id": napcat_user_id}, napcat_group_id
                )
            if napcat_operator_id and self.server_connection:
                seg_data_dict[
                    "operator_user_info"
                ] = await self._napcat_to_aicarus_userinfo(
                    {"user_id": napcat_operator_id}, napcat_group_id
                )
            seg_data_dict["join_type"] = napcat_event.get("sub_type")
            if (
                napcat_event.get("sub_type") == "invite"
                and aicarus_interaction_purpose == "platform_request"
            ):
                aicarus_final_seg_type = "request:group_invite_received"
                if napcat_operator_id and self.server_connection:
                    seg_data_dict[
                        "inviter_user_info"
                    ] = await self._napcat_to_aicarus_userinfo(
                        {"user_id": napcat_operator_id}, napcat_group_id
                    )
                seg_data_dict["request_flag"] = str(
                    napcat_event.get("message_id")
                    or napcat_event.get("event_id")
                    or f"napcat_invite_{uuid.uuid4()}"
                )
        elif (
            napcat_notice_type == NoticeType.notify
            and napcat_event.get("sub_type") == NoticeType.Notify.poke
        ):
            aicarus_final_seg_type = "notification:poke_received"
            target_id = str(napcat_event.get("target_id", ""))
            if napcat_user_id and self.server_connection:
                seg_data_dict[
                    "sender_user_info"
                ] = await self._napcat_to_aicarus_userinfo(
                    {"user_id": napcat_user_id}, napcat_group_id
                )
            if target_id and self.server_connection:
                seg_data_dict[
                    "target_user_info"
                ] = await self._napcat_to_aicarus_userinfo(
                    {"user_id": target_id}, napcat_group_id
                )
            seg_data_dict["context_type"] = "group" if napcat_group_id else "private"
        elif (
            napcat_notice_type == NoticeType.friend_add
            and aicarus_interaction_purpose == "platform_request"
        ):
            aicarus_final_seg_type = "request:friend_add"
            if napcat_user_id and self.server_connection:
                seg_data_dict[
                    "source_user_info"
                ] = await self._napcat_to_aicarus_userinfo({"user_id": napcat_user_id})
            seg_data_dict["comment"] = napcat_event.get("comment")
            seg_data_dict["request_flag"] = str(
                napcat_event.get("flag")
                or napcat_event.get("message_id")
                or f"napcat_friend_req_{uuid.uuid4()}"
            )
            if not napcat_event.get("flag") and not napcat_event.get("message_id"):
                logger.warning(
                    f"AIcarus Adapter: friend_add request from Napcat is missing a 'flag' or 'message_id'. Response might not work. Event: {napcat_event}"
                )
        else:
            aicarus_final_seg_type = (
                f"{aicarus_seg_type_prefix}:napcat_unmapped_{napcat_notice_type}"
            )
            if napcat_event.get("sub_type"):
                aicarus_final_seg_type += f"_{napcat_event.get('sub_type')}"
            logger.warning(
                f"AIcarus Adapter: Unmapped Napcat notice_type: {napcat_notice_type}, sub_type: {napcat_event.get('sub_type')}. Seg type set to {aicarus_final_seg_type}"
            )

        if "raw_napcat_event_fields" in seg_data_dict and len(seg_data_dict) > 1:
            del seg_data_dict["raw_napcat_event_fields"]

        aicarus_seg = AicarusSeg(type=aicarus_final_seg_type, data=seg_data_dict)
        aicarus_message = AicarusMessageBase(
            message_info=aicarus_base_info,
            message_segment=AicarusSeg(type="seglist", data=[aicarus_seg]),
            raw_message=json.dumps(napcat_event),
        )
        await self.dispatch_to_core(aicarus_message)

    async def dispatch_to_core(self, message_base: AicarusMessageBase):
        if self.maibot_router:
            try:
                await self.maibot_router.send_message_to_core(
                    message_base.to_dict()
                )  # 确保调用 send_message_to_core
                logger.debug(
                    f"AIcarus Adapter: Dispatched message to Core: {message_base.message_info.interaction_purpose} / {message_base.message_segment.data[0].type if message_base.message_segment.data else 'empty_seglist'}"
                )
            except Exception as e:
                logger.error(
                    f"AIcarus Adapter: Failed to send message to Core via router: {e}"
                )
                logger.error(f"Message content: {message_base.to_dict()}")
        else:
            logger.error(
                "AIcarus Adapter: Maibot router (CoreConnectionClient) not available. Cannot send message to Core."
            )


recv_handler_aicarus = RecvHandlerAicarus()
