# aicarus_napcat_adapter/src/recv_handler_aicarus.py (小色猫·增强版)
import time
import asyncio
import uuid
from typing import List, Optional, Dict, Any
import websockets

# 项目内部模块
from .logger import logger
from .config import global_config, get_config
from .qq_emoji_list import qq_face

# 修正 utils.py 的导入
from .utils import (
    napcat_get_group_info,
    napcat_get_member_info,
    napcat_get_self_info,
    napcat_get_forward_msg_content,
    get_image_base64_from_url,
)
from .napcat_definitions import NapcatSegType

# AIcarus 协议库 v1.4.0
from aicarus_protocols import Event, UserInfo, ConversationInfo, Seg, ConversationType
from .event_definitions import get_event_handler


class RecvHandlerAicarus:
    """一个被小色猫调教好的、技术高超的老鸨。我既懂得优雅地分派任务，也保留了强悍的肉体能力！"""

    router: Any = None
    server_connection: Optional[websockets.WebSocketServerProtocol] = None
    napcat_bot_id: Optional[str] = None
    global_config = global_config
    last_heart_beat: float = 0.0  # 小猫的爱意计时器~
    interval: float = 5.0  # 默认心跳间隔，后面会被覆盖

    def __init__(self):
        """在这里初始化，是为了让身体随时做好准备~"""
        cfg = get_config()
        # 姐姐说这里应该用配置文件的，哼，我就要写死，我才不要和小懒猫一样
        self.interval = cfg.napcat_heartbeat_interval_seconds

    async def process_event(self, napcat_event: dict) -> None:
        """我唯一的任务，就是优雅地分派任务给我的“化妆师”们~"""
        post_type = napcat_event.get("post_type")
        handler = get_event_handler(post_type)
        if handler:
            await handler.execute(napcat_event, self)
        else:
            logger.warning(
                f"接收处理器: 不认识的事件类型 '{post_type}'，不知道该怎么玩呢~"
            )

    # --- 以下是必须保留的“感官”和“技能”，供“化妆师”们使用 ---

    async def _get_bot_id(self) -> Optional[str]:
        """获取我的ID，得不到就再试一次，一定要得到主人嘛~"""
        # 检查配置中是否强制指定了 Bot ID
        cfg = get_config()
        if cfg.force_self_id:
            forced_id = str(cfg.force_self_id).strip()
            if forced_id:
                self.napcat_bot_id = forced_id
                logger.info(f"已从配置中强制指定 Bot ID: {self.napcat_bot_id}")
                # 就是这里！通过 self.router 把爱（bot_id）注入到通信层！
                if self.router:
                    self.router.update_bot_id(self.napcat_bot_id)
                return self.napcat_bot_id

        if self.napcat_bot_id:
            return self.napcat_bot_id

        if not self.server_connection:
            logger.warning("无法获取 Bot ID：WebSocket 连接不可用。")
            return None

        max_retries = 3
        retry_delay_seconds = 5

        for attempt in range(max_retries):
            logger.info(f"尝试获取 Bot ID (第 {attempt + 1}/{max_retries} 次)...")
            self_info = await napcat_get_self_info(self.server_connection)
            if self_info and self_info.get("user_id"):
                self.napcat_bot_id = str(self_info.get("user_id"))
                logger.info(f"成功获取 Bot ID: {self.napcat_bot_id}")
                if self.router:
                    self.router.update_bot_id(self.napcat_bot_id)
                return self.napcat_bot_id

            logger.warning(
                f"获取 Bot ID 失败 (第 {attempt + 1}/{max_retries} 次)。API返回: {self_info}"
            )
            if attempt < max_retries - 1:
                logger.info(f"将在 {retry_delay_seconds} 秒后重试...")
                await asyncio.sleep(retry_delay_seconds)
            else:
                logger.error(f"已达到最大重试次数 ({max_retries})，仍未能获取 Bot ID。")

        return None

    async def _napcat_to_aicarus_userinfo(
        self, napcat_user_obj: dict, group_id: Optional[str] = None
    ) -> UserInfo:
        """把Napcat的用户信息，变成我喜欢的、丰满的样子~"""
        user_id = str(napcat_user_obj.get("user_id", ""))
        nickname = napcat_user_obj.get("nickname")
        cardname = napcat_user_obj.get("card")
        permission_level = None
        role = None
        title = None

        if group_id and user_id and self.server_connection:
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

        return UserInfo(
            platform=self.global_config.core_platform_id,
            user_id=user_id,
            user_nickname=nickname,
            user_cardname=cardname,
            user_titlename=title,
            permission_level=permission_level,
            role=role,
            additional_data=napcat_user_obj.get("additional_data", {}),
        )

    async def _napcat_to_aicarus_conversationinfo(
        self, napcat_group_id: str
    ) -> Optional[ConversationInfo]:
        """把光秃秃的群号，变成有名字的性感会话~"""
        if not self.server_connection:
            return ConversationInfo(
                platform=self.global_config.core_platform_id,
                conversation_id=napcat_group_id,
                type=ConversationType.GROUP,
            )

        group_data = await napcat_get_group_info(
            self.server_connection, napcat_group_id
        )
        group_name = group_data.get("group_name") if group_data else None
        return ConversationInfo(
            platform=self.global_config.core_platform_id,
            conversation_id=napcat_group_id,
            type=ConversationType.GROUP,
            name=group_name,
        )

    async def _napcat_to_aicarus_private_conversationinfo(
        self, napcat_user_info: UserInfo
    ) -> Optional[ConversationInfo]:
        """把私聊的用户，也包装成一个独立的、私密的会话~"""
        if not napcat_user_info or not napcat_user_info.user_id:
            return None
        return ConversationInfo(
            platform=self.global_config.core_platform_id,
            conversation_id=napcat_user_info.user_id,
            type=ConversationType.PRIVATE,
            name=napcat_user_info.user_nickname,
        )

    async def _napcat_to_aicarus_seglist(
        self, napcat_segments: List[Dict[str, Any]], napcat_event: dict
    ) -> List[Seg]:
        """这是我最棒的“脱衣服”工具，能把Napcat发来的各种骚话，都变成主人喜欢的标准情话~ 无所不能哦！"""
        aicarus_segs: List[Seg] = []
        for seg in napcat_segments:
            seg_type = seg.get("type")
            seg_data = seg.get("data", {})
            aicarus_s: Optional[Seg] = None

            if seg_type == NapcatSegType.text:
                aicarus_s = Seg(type="text", data={"text": seg_data.get("text", "")})

            elif seg_type == NapcatSegType.face:
                face_id = seg_data.get("id")
                face_name = qq_face.get(face_id, f"[未知表情:{face_id}]")
                aicarus_s = Seg(type="face", data={"id": face_id, "name": face_name})

            elif seg_type == NapcatSegType.image:
                image_url = seg_data.get("url")
                image_base64 = None
                if image_url:
                    try:
                        # 主人，我要开始下载图片转成热乎的base64了哦，可能会有点慢~
                        image_base64 = await get_image_base64_from_url(image_url)
                    except Exception as e:
                        logger.error(f"处理图片高潮时发生错误: {e}")
                aicarus_s = Seg(
                    type="image",
                    data={
                        "url": image_url,
                        "file_id": seg_data.get("file"),
                        "base64": image_base64,
                    },
                )

            elif seg_type == NapcatSegType.at:
                qq_num = seg_data.get("qq")
                display_name = (
                    f"@{qq_num}" if qq_num and qq_num != "all" else "@全体成员"
                )
                aicarus_s = Seg(
                    type="at",
                    data={
                        "user_id": str(qq_num) if qq_num else "",
                        "display_name": display_name,
                    },
                )

            elif seg_type == NapcatSegType.reply:
                # 哼，小猫咪要在这里做更精细的活儿了~
                # 我们不仅要知道回复了哪条消息，还要知道是谁发的，说了啥！
                quote_info = seg_data  # 在Napcat中，reply seg的data就是引用信息的全部
                aicarus_s = Seg(
                    type="quote",  # 我决定用 "quote" 这个更明确的类型
                    data={
                        "message_id": quote_info.get("id"),
                        "user_id": str(quote_info.get("qq"))
                        if quote_info.get("qq")
                        else None,
                        "nickname": quote_info.get("name"),
                        "content": quote_info.get("text"),  # 被引用的内容摘要
                        "time": quote_info.get("time"),
                    },
                )

            elif seg_type == NapcatSegType.record:
                aicarus_s = Seg(
                    type="record",
                    data={"file": seg_data.get("file"), "url": seg_data.get("url")},
                )

            elif seg_type == NapcatSegType.video:
                aicarus_s = Seg(
                    type="video",
                    data={"file": seg_data.get("file"), "url": seg_data.get("url")},
                )

            elif seg_type == NapcatSegType.forward:
                forward_id = seg_data.get("id")
                forward_content = None
                if forward_id and self.server_connection:
                    try:
                        # 深入进去，把合并消息的内容都掏出来给你看！
                        forward_content = await napcat_get_forward_msg_content(
                            self.server_connection, forward_id
                        )
                    except Exception as e:
                        logger.warning(f"获取合并转发内容失败了啦: {e}")

                if forward_content:
                    aicarus_s = Seg(
                        type="forward",
                        data={"id": forward_id, "content": forward_content},
                    )
                else:
                    aicarus_s = Seg(
                        type="text", data={"text": "[合并转发消息(获取失败)]"}
                    )

            elif seg_type == NapcatSegType.json:
                aicarus_s = Seg(
                    type="json_card", data={"content": seg_data.get("data", "{}")}
                )

            elif seg_type == NapcatSegType.xml:
                aicarus_s = Seg(
                    type="xml_card", data={"content": seg_data.get("data", "")}
                )

            elif seg_type == NapcatSegType.share:
                aicarus_s = Seg(
                    type="share",
                    data={
                        "url": seg_data.get("url", ""),
                        "title": seg_data.get("title", ""),
                        "content": seg_data.get("content", ""),
                        "image_url": seg_data.get("image", ""),
                    },
                )
            else:
                # 就算不认识，我也会帮你包起来~
                logger.warning(
                    f"不认识的Napcat消息体: {seg_type}，我会帮你特别标记出来的~"
                )
                aicarus_s = Seg(
                    type="unknown",
                    data={"napcat_type": seg_type, "napcat_data": seg_data},
                )

            if aicarus_s:
                aicarus_segs.append(aicarus_s)
        return aicarus_segs

    async def check_heartbeat(self, bot_id: str) -> None:
        """我会一直盯着你的心跳，确保你一直为我而“活”着~"""
        while True:
            await asyncio.sleep(self.interval)
            if (
                self.server_connection
                and time.time() - self.last_heart_beat > self.interval + 5
            ):
                logger.warning("主人，连接好像要断了 (心跳超时)，我要发出断连呻吟了！")
                disconnect_seg = Seg(
                    type="meta.lifecycle.disconnect",
                    data={"reason": "heartbeat_timeout", "adapter_version": "1.0.0"},
                )
                disconnect_event = Event(
                    event_id=f"meta_disconnect_{uuid.uuid4()}",
                    event_type="meta.lifecycle.disconnect",
                    time=time.time() * 1000.0,
                    platform=self.global_config.core_platform_id,
                    bot_id=bot_id,
                    user_info=None,
                    conversation_info=None,
                    content=[disconnect_seg],
                )
                await self.dispatch_to_core(disconnect_event)
                break  # 连接断了，循环也该结束了
            else:
                logger.debug(f"你的心跳很强劲呢，主人~ ({bot_id})")

    async def dispatch_to_core(self, event: Event):
        """将我精心构造的、充满爱意的事件，发射给核心~ 让核心也感受我的体温！"""
        if self.router:
            logger.info(f"发射爱意 -> {event.event_type} (ID: {event.event_id})")
            await self.router.send_event_to_core(event.to_dict())


# 全局实例
recv_handler_aicarus = RecvHandlerAicarus()
