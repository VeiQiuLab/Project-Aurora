"""Translate OneBot 11 events into Aurora's small external-message model."""

from .models import QQMessage


def _sender_name(event):
    sender = event.get("sender") or {}
    return str(sender.get("card") or sender.get("nickname") or sender.get("user_id") or "QQ user")


def _segments(event):
    message = event.get("message", event.get("raw_message", ""))
    if message is None:
        message = event.get("raw_message", "")
    if isinstance(message, str) and message.startswith("["):
        try:
            import json
            decoded = json.loads(message)
            if isinstance(decoded, list):
                message = decoded
        except (TypeError, ValueError):
            pass
    if isinstance(message, str):
        return [{"type": "text", "data": {"text": message}}]
    return message if isinstance(message, list) else []


def parse_event(event):
    if not isinstance(event, dict):
        return None, "not_message_event"
    if event.get("post_type") == "message_sent":
        return None, "self_message"
    if event.get("post_type") != "message":
        return None, "not_message_event"
    message_type = str(event.get("message_type", ""))
    if message_type not in {"private", "group"}:
        return None, "unsupported_message_type"
    self_id = str(event.get("self_id", "") or "")
    sender = event.get("sender") or {}
    sender_id = str(sender.get("user_id", event.get("user_id", "")) or "")
    if self_id and sender_id and sender_id == self_id:
        return None, "self_message"
    group_id = str(event.get("group_id", "") or "") if message_type == "group" else ""
    conversation_id = f"qq:{'group' if group_id else 'private'}:{group_id or sender_id}"
    text_parts = []
    mentioned = False
    unsupported = False
    for segment in _segments(event):
        if not isinstance(segment, dict):
            unsupported = True
            continue
        kind = segment.get("type")
        data = segment.get("data") or {}
        if kind == "text":
            text_parts.append(str(data.get("text", "")))
        elif kind == "at" and message_type == "group" and str(data.get("qq", "")) == self_id:
            mentioned = True
        else:
            unsupported = True
    if unsupported:
        return None, "unsupported_segment"
    if not str("".join(text_parts)).strip():
        return None, "empty_text"
    return QQMessage(
        source="qq",
        conversation_id=conversation_id,
        sender_id=sender_id,
        sender_name=_sender_name(event),
        message_type=message_type,
        text="".join(text_parts).strip(),
        is_group=message_type == "group",
        group_id=group_id,
        mentioned_self=mentioned,
        event_id=str(event.get("message_id", event.get("time", "")) or ""),
        self_id=self_id,
        allow_memory=False,
    ), "parsed"


def adapt_event(event):
    message, _reason = parse_event(event)
    return message
