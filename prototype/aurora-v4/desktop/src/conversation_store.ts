export type MessageRole = "user" | "assistant";
export type MessageState = "normal" | "failed";

export interface ConversationMessage {
  id: string;
  role: MessageRole;
  content: string;
  state: MessageState;
}

export interface ConversationRecord {
  id: string;
  title: string;
  preview: string;
  messages: ConversationMessage[];
}

const cloneConversation = (conversation: ConversationRecord): ConversationRecord => ({
  ...conversation,
  messages: conversation.messages.map((message) => ({ ...message })),
});

export class ConversationStore {
  readonly conversations: ConversationRecord[];
  activeId: string;

  constructor(seed: ConversationRecord[]) {
    if (seed.length === 0) throw new Error("Conversation seed cannot be empty");
    this.conversations = seed.map(cloneConversation);
    this.activeId = this.conversations[0].id;
  }

  get active(): ConversationRecord {
    const conversation = this.find(this.activeId);
    if (!conversation) throw new Error("Active conversation is missing");
    return conversation;
  }

  create(id: string): ConversationRecord {
    if (this.find(id)) throw new Error("Conversation ID must be unique");
    const conversation: ConversationRecord = {
      id,
      title: "新对话",
      preview: "尚无消息",
      messages: [],
    };
    this.conversations.unshift(conversation);
    this.activeId = id;
    return conversation;
  }

  select(id: string): boolean {
    if (!this.find(id)) return false;
    this.activeId = id;
    return true;
  }

  addMessage(conversationId: string, message: ConversationMessage): void {
    const conversation = this.require(conversationId);
    if (conversation.messages.some((item) => item.id === message.id)) {
      throw new Error("Message ID must be unique within a conversation");
    }
    conversation.messages.push({ ...message });
  }

  updateMessage(
    conversationId: string,
    messageId: string,
    update: Partial<Pick<ConversationMessage, "content" | "state">>,
  ): void {
    const conversation = this.require(conversationId);
    const message = conversation.messages.find((item) => item.id === messageId);
    if (!message) throw new Error("Message is missing");
    Object.assign(message, update);
  }

  updateSummary(conversationId: string, title: string | null, preview: string): void {
    const conversation = this.require(conversationId);
    if (title !== null) conversation.title = title;
    conversation.preview = preview;
  }

  private find(id: string): ConversationRecord | undefined {
    return this.conversations.find((conversation) => conversation.id === id);
  }

  private require(id: string): ConversationRecord {
    const conversation = this.find(id);
    if (!conversation) throw new Error("Conversation is missing");
    return conversation;
  }
}

export const initialConversations = (): ConversationRecord[] => [
  {
    id: "desktop-architecture",
    title: "桌面架构",
    preview: "隔离的桌面与 Python 后端",
    messages: [
      {
        id: "welcome-assistant",
        role: "assistant",
        content: "界面与 Python 后端彼此隔离。即使后端停止响应，桌面仍然保持可用。",
        state: "normal",
      },
      {
        id: "welcome-user",
        role: "user",
        content: "验证流式响应、取消与恢复边界。",
        state: "normal",
      },
    ],
  },
  {
    id: "streaming-boundary",
    title: "流式响应",
    preview: "顺序、取消与恢复",
    messages: [
      {
        id: "streaming-note",
        role: "assistant",
        content: "每个增量都经过顺序与生成归属检查，旧请求不会污染下一轮对话。",
        state: "normal",
      },
    ],
  },
  {
    id: "visual-language",
    title: "视觉语言",
    preview: "黑白、克制、轻玻璃",
    messages: [
      {
        id: "visual-note",
        role: "assistant",
        content: "纯黑基底、清晰文字和极轻的玻璃质感，让内容成为界面的中心。",
        state: "normal",
      },
    ],
  },
];
