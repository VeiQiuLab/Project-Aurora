"""Conservative evidence and entity rules shared by existing Memory paths.

No storage, model calls or inferred relationships. Unknown scope stays unknown.
"""
import re
from collections.abc import Mapping

UNCERTAIN = re.compile(r"可能|也许|不确定|大概|打算|计划|准备|假如|如果|什么|哪里|为何|为什么|怎么|是否|吗[？?]?$|[？?]|\b(?:maybe|probably|perhaps|might|plan to|if|would|could|what|who|where|how|why)\b", re.I)
TEMPORARY = re.compile(r"今天|明天|昨天|今晚|这周|临时|暂时|一次性|\b(?:today|tomorrow|yesterday|tonight|this week|temporary|for now)\b", re.I)
FOLLOWUP = re.compile(r"^(?:那|这个|那个|它|他|她)|\b(?:what next|what about it|what about them|its next)\b", re.I)


def statements(messages):
    """Yield exact user quotes with source indexes; do not truncate facts."""
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    for index, message in enumerate(messages or ()):
        if not isinstance(message, Mapping) or message.get("role") != "user":
            continue
        for quote in re.split(r"(?<=[。！？!?；;])|[\n\r]+|(?<=[a-zA-Z])\.\s+", str(message.get("content", ""))):
            quote = quote.strip()
            if quote:
                yield index, quote


def scope(text):
    """Return only explicitly named subjects and recognizable properties."""
    text = str(text or "").strip()
    project = re.search(r"(?:\bproject\s+|项目\s*)([A-Za-z][\w-]*|[\u4e00-\u9fff]{1,16}?)(?=\s|当前|已|目标|阶段|的|是|，|。|$)", text, re.I)
    person = re.search(r"(?:我的(?:朋友|同事|伴侣|家人)|\bmy (?:friend|colleague|partner)\s*)([A-Za-z][\w-]*|[\u4e00-\u9fff]{1,8}?)(?=\s|在|是|喜欢|偏好|，|。|$)", text, re.I)
    entity = "project:" + project[1].casefold() if project else "person:" + person[1].casefold() if person else "user"
    properties = [
        ("stage", r"阶段|\bstage\b|\bphase\b"), ("goal", r"目标|\bgoal\b"),
        ("decision", r"决定|决策|\bdecid|\bdecision"),
        ("name", r"我的(?:名字|姓名)|\bmy name\b"),
        ("location", r"在.+(?:工作|生活|居住)|\b(?:lives|works) in\b"),
        ("job", r"工作|职业|角色|\b(?:job|role|profession)\b"),
        ("device", r"设备|\bdevice\b"),
        ("reply_style", r"回复|回答|\b(?:replies|reply|responses|response|answers|answer)\b"),
        ("preference", r"喜欢|偏好|习惯|\b(?:prefer|like|love|usually use|always use)\b"),
    ]
    prop = next((name for name, pattern in properties if re.search(pattern, text, re.I)), "")
    return entity, prop


def compatible(first, second):
    left, right = scope(first), scope(second)
    # A named person/project must never update an unidentified or other subject.
    if left[0] != right[0]:
        return False
    if left[0] != "user" or left[1] in {"name", "job", "device"} or right[1] in {"name", "job", "device"}:
        return left[1] == right[1]
    return not (left[1] and right[1] and left[1] != right[1])


def normalized(text):
    text = re.sub(r"^(?:更正|纠正|correction)\s*[:：]\s*", "", str(text), flags=re.I)
    text = re.sub(r"^(?:请记住|记住|please remember|remember that)\s*[:：]?\s*", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" .。,:：;；")


def explicit_candidates(messages, min_score=.75):
    candidates = []
    latest = {}
    seen = set()
    for index, quote in statements(messages):
        text = normalized(quote)
        # Keep punctuation and modal words in the evidence used for filtering.
        if not text or len(text) > 240 or UNCERTAIN.search(quote) or TEMPORARY.search(quote):
            continue
        entity, prop = scope(text)
        preference = re.search(r"^(?:我(?:更喜欢|喜欢|偏好|通常用|一直用)|I (?:prefer|like|love|usually use|always use)\b|My preferred\b)", text, re.I)
        requested = bool(re.search(r"^(?:请记住|记住|please remember|remember that)\b|^(?:请记住|记住)", quote, re.I))
        fact = bool(re.search(r"^(?:我的(?:名字|姓名|工作|角色|项目|公司|设备|朋友|同事|伴侣|家人)|my (?:name|job|role|project|company|device|friend|colleague|partner)\b|项目\s*|project\s+)", text, re.I))
        if not (preference or requested or fact):
            continue
        memory_type, score = ("preference", .86) if preference else ("instruction", .88) if requested and not fact else ("fact", .78)
        if score < min_score:
            continue
        scalar = prop in {"name", "stage", "job", "location", "device", "reply_style"}
        key = text.casefold()
        if key in seen and not scalar:
            continue
        seen.add(key)
        candidate = {"type": memory_type, "content": text, "score": score, "importance": "normal", "source": "rule",
                     "source_detail": {"kind": "user_statement", "message_index": index, "quote": quote,
                                       "entity": entity, "property": prop, "certainty": "explicit"}}
        # Only explicit corrections or scalar current facts supersede earlier
        # evidence in this batch. Multiple hobbies/goals/instructions can coexist.
        if scalar:
            prior = latest.get((entity, prop))
            if prior is not None:
                candidates[prior] = None
            latest[(entity, prop)] = len(candidates)
        candidates.append(candidate)
    return [item for item in candidates if item is not None]


def mentions(entity, text):
    name = entity.split(":", 1)[1]
    if re.fullmatch(r"[a-z][\w-]*", name, re.I):
        return bool(re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", str(text), re.I))
    return name in str(text).casefold()
