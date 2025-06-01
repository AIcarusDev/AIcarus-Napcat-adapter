# 定义 Napcat 特有的常量，以便 recv_handler_aicarus.py 引用


class MetaEventType:
    lifecycle = "lifecycle"
    heartbeat = "heartbeat"

    class Lifecycle:
        connect = "connect"
        # ... 其他生命周期子类型


class MessageType:
    private = "private"
    group = "group"

    class Private:
        friend = "friend"
        group = "group"  # 群临时会话
        # ... 其他私聊子类型

    class Group:
        normal = "normal"
        anonymous = "anonymous"
        # ... 其他群聊子类型


class NoticeType:
    friend_recall = "friend_recall"
    group_recall = "group_recall"
    group_increase = "group_increase"  # 群成员增加
    group_decrease = "group_decrease"  # 群成员减少
    group_admin = "group_admin"  # 群管理员变动
    group_upload = "group_upload"  # 群文件上传
    group_ban = "group_ban"  # 群禁言
    friend_add = "friend_add"  # 好友添加（通常这是一个请求，但有时平台也作为通知）
    group_card = "group_card"  # 群名片变更
    notify = "notify"  # 一些特殊通知的父类型

    class Notify:  # 特殊通知的子类型
        poke = "poke"
        lucky_king = "lucky_king"
        honor = "honor"
        # ... 其他特殊通知子类型 (如 OneBot 的 title, essence)


class RequestType:  # Napcat 可能没有直接的请求类型，需要从 notice 或特定事件中判断
    friend = "friend"  # 好友请求
    group = "group"  # 加群请求/邀请


# Napcat 消息段类型 (real_message_type)
class NapcatSegType:
    text = "text"
    face = "face"  # QQ 表情
    image = "image"  # 图片或表情包 (通过 sub_type 区分)
    record = "record"  # 语音
    video = "video"
    at = "at"
    rps = "rps"  # 猜拳
    dice = "dice"  # 骰子
    shake = "shake"  # 窗口抖动 (戳一戳的前身)
    poke = "poke"  # 戳一戳 (某些实现可能用这个)
    share = "share"  # 分享链接
    forward = "forward"  # 合并转发
    node = "node"  # 合并转发的节点 (通常内部使用)
    xml = "xml"
    json = "json"
    cardimage = "cardimage"  # 未在你的代码中看到，但某些 gocq 版本有
    tts = "tts"  # 文本转语音
    reply = "reply"  # 回复


# AIcarus 协议版本
AICARUS_PROTOCOL_VERSION = "1.2.0"
