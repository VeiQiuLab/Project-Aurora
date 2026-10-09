"""Synthetic, exact-expectation V4-8E corpus; never reads the user profile."""
import inspect
from modules.memory import MemoryExtractor
from modules.memory_retrieval import retrieve_memories

CANDIDATES = [
    ("preference", [{"role": "user", "content": "我喜欢简洁的回复。"}], ["我喜欢简洁的回复"]),
    ("temporary", [{"role": "user", "content": "我喜欢今天的午餐。"}], []),
    ("speculation", [{"role": "user", "content": "我可能喜欢长篇回复。"}], []),
    ("uncertain-project", [{"role": "user", "content": "请记住：项目 Atlas 可能进入发布阶段。"}], []),
    ("assistant", [{"role": "assistant", "content": "我的项目 Atlas 已经完成。"}], []),
    ("people", [{"role": "user", "content": "我的朋友林舟在北京工作。我的朋友周岚在上海工作。"}], ["我的朋友林舟在北京工作", "我的朋友周岚在上海工作"]),
    ("project", [{"role": "user", "content": "项目 Atlas 当前阶段是开发。"}], ["项目 Atlas 当前阶段是开发"]),
    ("correction", [{"role": "user", "content": "我的名字是陈明。"}, {"role": "assistant", "content": "你的名字是李青。"}, {"role": "user", "content": "更正：我的名字是李青。"}], ["我的名字是李青"]),
    ("experience", [{"role": "user", "content": "请记住：我曾参与远洋科考，这是重要经历。"}], ["我曾参与远洋科考，这是重要经历"]),
    ("question", [{"role": "user", "content": "我的朋友林舟在北京工作吗？"}], []),
]

MEMORIES = [
    {"id": "style", "type": "preference", "content": "我喜欢简洁的回复", "enabled": True},
    {"id": "atlas", "type": "fact", "content": "项目 Atlas 当前阶段是开发", "enabled": True},
    {"id": "boreal", "type": "fact", "content": "项目 Boreal 当前阶段是发布", "enabled": True},
    {"id": "lin", "type": "fact", "content": "我的朋友林舟在北京工作", "enabled": True},
    {"id": "zhou", "type": "fact", "content": "我的朋友周岚在上海工作", "enabled": True},
]
RETRIEVAL = [
    ("preference-after-unrelated", "请按我喜欢的回复风格回答", [], ["style"]),
    ("project", "项目 Atlas 当前阶段是什么？", [], ["atlas"]),
    ("people", "林舟在哪里工作？", [], ["lin"]),
    ("irrelevant", "为什么天空是蓝色的？", [], []),
    ("knowledge-not-profile", "北京有哪些历史建筑？", [], []),
    ("correction", "项目 Atlas 当前阶段是什么？", [{"role": "user", "content": "更正：项目 Atlas 当前阶段是发布。"}], []),
    ("followup", "那它下一步呢？", [{"role": "user", "content": "我们继续讨论项目 Atlas。"}], ["atlas"]),
    ("already-in-history", "林舟在哪里工作？", [{"role": "user", "content": "我的朋友林舟在北京工作。"}], []),
]

def evaluate():
    results = []
    tp = emitted = expected_count = duplicate = 0
    for name, messages, expected in CANDIDATES:
        actual = [item["content"] for item in MemoryExtractor().extract(messages)]
        tp += len(set(actual) & set(expected)); emitted += len(actual); expected_count += len(expected)
        duplicate += len(actual) - len(set(actual))
        results.append({"kind": "candidate", "case": name, "expected": expected, "actual": actual, "pass": actual == expected})
    recall_tp = recall_total = irrelevant = recalled = 0
    for name, prompt, history, expected in RETRIEVAL:
        kwargs = {"history": history} if "history" in inspect.signature(retrieve_memories).parameters else {}
        actual = [item["id"] for item in retrieve_memories(prompt, MEMORIES, **kwargs)]
        recall_tp += len(set(actual) & set(expected)); recall_total += len(expected)
        irrelevant += len(set(actual) - set(expected)); recalled += len(actual)
        results.append({"kind": "retrieval", "case": name, "expected": expected, "actual": actual, "pass": actual == expected})
    return {"cases": results, "metrics": {"candidate_precision": tp / max(1, emitted), "candidate_recall": tp / max(1, expected_count), "duplicate_rate": duplicate / max(1, emitted), "relevant_recall": recall_tp / max(1, recall_total), "irrelevant_injection_count": irrelevant, "retrieved_count": recalled, "passed_cases": sum(r["pass"] for r in results), "total_cases": len(results)}}
