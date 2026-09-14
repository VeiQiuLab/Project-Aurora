import assert from "node:assert/strict";
import test from "node:test";

import { ConversationStore, initialConversations } from "./conversation_store.ts";

test("new conversations become active without removing existing conversations", () => {
  const store = new ConversationStore(initialConversations());
  const previousCount = store.conversations.length;
  store.create("new-conversation");
  assert.equal(store.active.id, "new-conversation");
  assert.equal(store.active.title, "新对话");
  assert.equal(store.conversations.length, previousCount + 1);
});

test("conversation selection preserves independent message histories", () => {
  const store = new ConversationStore(initialConversations());
  const firstId = store.active.id;
  store.addMessage(firstId, {
    id: "first-user-message",
    role: "user",
    content: "第一段内容",
    state: "normal",
  });
  const secondId = store.conversations[1].id;
  assert.equal(store.select(secondId), true);
  store.addMessage(secondId, {
    id: "second-user-message",
    role: "user",
    content: "第二段内容",
    state: "normal",
  });
  assert.equal(store.active.messages.at(-1)?.content, "第二段内容");
  store.select(firstId);
  assert.equal(store.active.messages.at(-1)?.content, "第一段内容");
});

test("message updates and summaries remain scoped to their owner", () => {
  const store = new ConversationStore(initialConversations());
  const owner = store.active.id;
  store.addMessage(owner, {
    id: "assistant-stream",
    role: "assistant",
    content: "开始",
    state: "normal",
  });
  store.updateMessage(owner, "assistant-stream", {
    content: "完整内容",
    state: "failed",
  });
  store.updateSummary(owner, "新的标题", "新的摘要");
  assert.deepEqual(store.active.messages.at(-1), {
    id: "assistant-stream",
    role: "assistant",
    content: "完整内容",
    state: "failed",
  });
  assert.equal(store.active.title, "新的标题");
  assert.equal(store.active.preview, "新的摘要");
});

test("production metadata can be replaced without eagerly loading history", () => {
  const store = new ConversationStore(initialConversations());
  store.replace([{ id: "persisted", title: "已保存", preview: "2 条消息", messages: [] }]);
  assert.equal(store.activeId, "");
  assert.deepEqual(store.active.messages, []);
  assert.equal(store.select("persisted"), true);
  store.setMessages("persisted", [{ id: "m", role: "user", content: "历史", state: "normal" }]);
  assert.equal(store.active.messages[0].content, "历史");
});
