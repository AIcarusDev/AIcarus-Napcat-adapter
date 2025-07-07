# aicarus_napcat_adapter/src/action_register.py
# key: string (由Napcat返回的、机器人自己发出的消息的 message_id)
# value: string (核心下发该动作时，原始的 action_event_id)
pending_actions: dict[str, str] = {}
