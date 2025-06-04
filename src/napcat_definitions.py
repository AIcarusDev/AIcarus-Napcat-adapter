# 定义 Napcat 特有的常量，以便 v1.4.0 协议处理器引用


class MetaEventType:
    lifecycle = "lifecycle"
    heartbeat = "heartbeat"

    class Lifecycle:
        enable = "enable"
        disable = "disable"
        connect = "connect"


class MessageType:
    private = "private"
    group = "group"
    guild = "guild"

    class Private:
        friend = "friend"
        group = "group"  # 群临时会话
        guild = "guild"  # 频道私聊
        other = "other"

    class Group:
        normal = "normal"
        anonymous = "anonymous"
        notice = "notice"

    class Guild:
        normal = "normal"


class NoticeType:
    group_upload = "group_upload"
    group_admin = "group_admin"
    group_decrease = "group_decrease"
    group_increase = "group_increase"
    group_ban = "group_ban"
    friend_add = "friend_add"
    group_recall = "group_recall"
    friend_recall = "friend_recall"
    group_card = "group_card"
    offline_file = "offline_file"
    client_status = "client_status"
    essence = "essence"
    notify = "notify"

    class Notify:
        poke = "poke"
        lucky_king = "lucky_king"
        honor = "honor"
        title = "title"


class RequestType:
    friend = "friend"
    group = "group"


# Napcat 消息段类型 (real_message_type)
class NapcatSegType:
    text = "text"
    face = "face"
    image = "image"
    record = "record"  # 语音
    video = "video"
    at = "at"
    rps = "rps"  # 猜拳
    dice = "dice"  # 掷骰子
    shake = "shake"  # 窗口抖动
    poke = "poke"  # 戳一戳
    anonymous = "anonymous"  # 匿名发消息
    share = "share"  # 链接分享
    contact = "contact"  # 推荐好友
    location = "location"  # 位置
    music = "music"  # 音乐分享
    reply = "reply"  # 回复
    forward = "forward"  # 合并转发
    node = "node"  # 合并转发节点
    xml = "xml"  # XML 消息
    json = "json"  # JSON 消息
    cardimage = "cardimage"  # 未在你的代码中看到，但某些 gocq 版本有
    tts = "tts"  # 文本转语音
    reply = "reply"  # 回复


# AIcarus 协议版本 - v1.4.0
AICARUS_PROTOCOL_VERSION = "1.4.0"
