from dataclasses import dataclass


@dataclass
class QQConfig:
    ws_endpoint: str = "ws://127.0.0.1:3001"
    http_endpoint: str = "http://127.0.0.1:3000"
    access_token: str = ""
    private_replies: bool = False
    group_mentions_only: bool = True


@dataclass(frozen=True)
class QQMessage:
    source: str
    conversation_id: str
    sender_id: str
    sender_name: str
    message_type: str
    text: str
    is_group: bool
    group_id: str = ""
    mentioned_self: bool = False
    event_id: str = ""
    self_id: str = ""
    allow_memory: bool = False

