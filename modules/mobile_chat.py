"""Mobile LAN chat bridge for Project Aurora.

This module does not implement a separate AI stack. It builds the same
context layers used by desktop Chat and sends them through the existing
Ollama chat module.
"""

import threading
from datetime import datetime
import json
import socket
import time
import urllib.error
import urllib.request

from modules.authentication import AuthenticationManager
from modules.chat import ChatError, DEFAULT_SYSTEM_CONTEXT, ChatSession, assemble_final_prompt, chat_with_messages
from modules.conversation import ConversationManager
from modules.health import check_ollama_diagnostics
from modules.knowledge import KnowledgeStore
from modules.memory import MemoryStore
from modules.models import infer_model_capability, model_supports_chat
from modules.persona import PersonaStore
from modules.remote import RemoteAccessManager
from modules.retrieval import format_knowledge_context
from modules.settings import settings


MAX_MOBILE_MESSAGE_LENGTH = 2000
DEFAULT_MOBILE_CHAT_TIMEOUT = 60
MAX_MOBILE_RESPONSE_LENGTH = 12000
DEFAULT_MOBILE_RESPONSE_LIMIT = 12000


ERROR_MESSAGES = {
    "Remote Disabled": {
        "error": "Remote Disabled",
        "message": "Remote Access Disabled / 远程访问未启用。"
    },
    "LAN Chat Disabled": {
        "error": "LAN Chat Disabled",
        "message": "LAN Chat Disabled / 局域网聊天已关闭。"
    },
    "Server Starting": {
        "error": "Server Starting",
        "message": "Server is starting. Please try again. / 服务正在启动，请稍后重试。"
    },
    "Server Stopped": {
        "error": "Server Stopped",
        "message": "Server stopped. / 服务已停止。"
    },
    "Request Timeout": {
        "error": "Request Timeout",
        "message": "AI response timeout. / AI 回复超时。"
    },
    "Ollama Unavailable": {
        "error": "Ollama unavailable",
        "message": "Ollama service unavailable / Ollama 不可用"
    },
    "Context Build Failed": {
        "error": "Context build failed",
        "message": "Context build failed / 上下文构建失败"
    },
    "Chat Generation Failed": {
        "error": "Chat generation failed",
        "message": "Chat generation failed / AI 生成失败"
    },
    "Model Unavailable": {
        "error": "Model unavailable",
        "message": "Model unavailable / \u6a21\u578b\u4e0d\u53ef\u7528"
    },
    "Model Cannot Chat": {
        "error": "Model cannot chat",
        "message": "Model cannot chat. Please select a chat model. / \u5f53\u524d\u6a21\u578b\u4e0d\u652f\u6301\u804a\u5929\uff0c\u8bf7\u9009\u62e9\u804a\u5929\u6a21\u578b\u3002"
    },
    "Invalid Response": {
        "error": "Invalid response",
        "message": "Invalid response / 返回格式错误"
    },
    "AI Response Failed": {
        "error": "Unknown error",
        "message": "Unknown error / 未知错误"
    },
    "Invalid Request": {
        "error": "Invalid Request",
        "message": "Invalid request. / 请求无效。"
    }
}


class MobileChatService:
    """Handle one-at-a-time local LAN mobile chat requests."""

    def __init__(
        self,
        model_provider=None,
        remote_manager=None,
        memory_store=None,
        knowledge_store=None,
        persona_store=None,
        event_callback=None
    ):
        self.model_provider = model_provider or (lambda: "")
        self.remote_manager = remote_manager or RemoteAccessManager()
        self.authentication_manager = AuthenticationManager(self.remote_manager.file_path)
        self.memory_store = memory_store or MemoryStore()
        self.knowledge_store = knowledge_store or KnowledgeStore()
        self.persona_store = persona_store or PersonaStore()
        self.conversation_manager = ConversationManager()
        self.event_callback = event_callback
        self.session = ChatSession(DEFAULT_SYSTEM_CONTEXT)
        self._lock = threading.Lock()

    def _emit(self, event):
        if callable(self.event_callback):
            try:
                self.event_callback(event)
            except Exception:
                pass

    def enabled(self):
        config = self.remote_manager.load()
        return bool(config.get("lan_chat_enabled", False))

    def access_status(self):
        config = self.remote_manager.load()
        auth = self.authentication_manager.status()
        return {
            "remote_enabled": bool(config.get("enabled", False)),
            "lan_chat_enabled": bool(config.get("lan_chat_enabled", False)),
            "authentication_status": auth.get("status", "Not Configured"),
            "authentication_configured": bool(auth.get("configured", False))
        }

    def check_ollama_ready(self, model=None, timeout=3):
        host = str(settings.get("ollama.host", "") or "").strip().rstrip("/")
        selected_model = str(model or settings.get("chat_model", "qwen3:8b") or "").strip()
        capability = infer_model_capability(selected_model)
        if not host:
            return {
                "ok": False,
                "running": False,
                "api_available": False,
                "model_available": False,
                "ollama_url": "",
                "model": selected_model,
                "chat_model": selected_model,
                "embedding_model": str(settings.get("embedding_model", "nomic-embed-text:latest") or ""),
                "model_capability": capability,
                "chat_support": capability == "Chat Supported",
                "available_models": [],
                "http_status": None,
                "connection_status": "Unavailable",
                "error_detail": "Ollama host is not configured.",
                "reason": "Ollama host is not configured."
            }

        diagnostics = check_ollama_diagnostics(host, model=selected_model, timeout=timeout)
        names = set(diagnostics.get("available_models", []))
        api_available = bool(diagnostics.get("api_available", False))
        model_available = bool(selected_model and selected_model in names)
        diagnostics["model_available"] = bool(model_available)
        diagnostics["model_capability"] = infer_model_capability(selected_model)
        diagnostics["chat_support"] = model_supports_chat(selected_model)
        if not diagnostics["chat_support"]:
            diagnostics["ok"] = False
            diagnostics["reason"] = "Model cannot chat. Please select a chat model."
            diagnostics["error_detail"] = diagnostics["reason"]
            return diagnostics
        if not api_available:
            diagnostics["ok"] = False
            diagnostics["reason"] = diagnostics.get("error_detail") or "Ollama unavailable"
            return diagnostics
        if selected_model and not model_available:
            diagnostics["ok"] = False
            diagnostics["reason"] = f"Model unavailable: {selected_model}"
            diagnostics["error_detail"] = diagnostics["reason"]
            return diagnostics
        diagnostics["ok"] = True
        diagnostics["reason"] = ""
        return diagnostics

    def _record_mobile_debug(self, status, stage, error="", duration_ms=0, model="", ollama_status=None, client="iPhone Safari"):
        try:
            config = self.remote_manager.update(
                last_mobile_error=str(error or ""),
                last_mobile_stage=str(stage or ""),
                last_mobile_status=str(status or ""),
                last_mobile_duration_ms=duration_ms,
                last_mobile_model=str(model or ""),
                last_mobile_capability=str((ollama_status or {}).get("model_capability") or infer_model_capability(model)),
                last_mobile_ollama_url=str((ollama_status or {}).get("ollama_url") or settings.get("ollama.host", "")),
                last_mobile_client=client,
                last_mobile_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            return config
        except Exception:
            return {}

    @staticmethod
    def _debug_detail_payload(ollama_status):
        if not isinstance(ollama_status, dict):
            return {}
        return {
            "ollama_url": ollama_status.get("ollama_url"),
            "model": ollama_status.get("model"),
            "connection_status": ollama_status.get("connection_status"),
            "http_status": ollama_status.get("http_status"),
            "error_detail": ollama_status.get("error_detail"),
            "available_models": ollama_status.get("available_models", [])
        }

    def mobile_status(self):
        status = self.access_status()
        config = self.remote_manager.load()
        network = self.remote_manager.network_info()
        model = str(self.model_provider() or settings.get("chat_model", "qwen3:8b") or "").strip()
        embedding_model = str(settings.get("embedding_model", "nomic-embed-text:latest") or "").strip()
        ollama = self.check_ollama_ready(model)
        model_capability = infer_model_capability(model)
        chat_ready = bool(ollama.get("ok", False) and model_capability == "Chat Supported")
        context_ready = True
        context_reason = ""
        try:
            self.build_context_sections("")
        except Exception as error:
            context_ready = False
            context_reason = str(error)
        return {
            "remote": bool(status.get("remote_enabled", False)),
            "lan_chat": bool(status.get("lan_chat_enabled", False)),
            "lan_ip": network.get("selected_lan_ip") or network.get("lan_address", ""),
            "port": int(config.get("lan_chat_port", 8765) or 8765),
            "ollama": bool(ollama.get("ok", False)),
            "ollama_status": ollama,
            "context": context_ready,
            "model": model,
            "chat_model": model,
            "embedding_model": embedding_model,
            "model_capability": model_capability,
            "chat_ready": chat_ready,
            "ai_ready": bool(status.get("remote_enabled", False) and status.get("lan_chat_enabled", False) and chat_ready and context_ready),
            "reason": ollama.get("reason") or context_reason,
            "status": status
        }

    def validate_message(self, message):
        text = str(message or "").strip()
        if not text:
            raise ValueError("Message is empty. / 消息不能为空。")
        if len(text) > MAX_MOBILE_MESSAGE_LENGTH:
            raise ValueError(f"Message is too long. Limit: {MAX_MOBILE_MESSAGE_LENGTH} characters. / 消息过长。")
        return text

    @staticmethod
    def _error(key, status=None, detail="", stage="", reason=""):
        payload = dict(ERROR_MESSAGES.get(key, ERROR_MESSAGES["AI Response Failed"]))
        if detail:
            payload["detail"] = str(detail)
        if stage:
            payload["stage"] = stage
        if reason:
            payload["reason"] = str(reason)
        payload["ok"] = False
        payload["status"] = status or {}
        return payload

    @staticmethod
    def _mobile_response_limit():
        try:
            configured = settings.get("mobile_response_limit", settings.get("remote.mobile_response_limit", DEFAULT_MOBILE_RESPONSE_LIMIT))
            return max(1000, int(configured))
        except (TypeError, ValueError):
            return DEFAULT_MOBILE_RESPONSE_LIMIT

    def _limit_response(self, text):
        content = str(text or "")
        limit = self._mobile_response_limit()
        if len(content) <= limit:
            return content
        return content[:limit] + "\n\n[Response truncated for mobile display]"

    @staticmethod
    def _debug_enabled():
        return bool(settings.get("mobile_debug_mode", settings.get("remote.mobile_debug_mode", False)))

    def build_context_sections(self, prompt):
        self._emit("Mobile context build started")
        self._emit("Context building started")
        memories = self.memory_store.retrieve(
            prompt,
            max_results=settings.get("memory.max_injection", 5),
            min_importance=settings.get("memory.min_importance", 0)
        )
        self._emit("Memory loaded")
        knowledge_items = []
        if settings.get("knowledge.enabled", True):
            knowledge_items = self.knowledge_store.retrieve(
                prompt,
                max_results=settings.get("knowledge.max_results", 3)
            )
        self._emit("Knowledge loaded")
        persona_text = ""
        if settings.get("persona.enabled", True):
            persona_text = self.persona_store.build_context(self.persona_store.load(update_timestamp=False))
        self._emit("Persona loaded")
        memory_text = self.memory_store.format_context(memories)
        knowledge_text = format_knowledge_context(knowledge_items)
        conversation_text = self._conversation_context()
        return [
            {"name": "System Context", "enabled": True, "content": DEFAULT_SYSTEM_CONTEXT},
            {"name": "Persona", "enabled": bool(persona_text), "content": persona_text},
            {"name": "Memory", "enabled": bool(memory_text), "content": memory_text},
            {"name": "Knowledge", "enabled": bool(knowledge_text), "content": knowledge_text},
            {"name": "Conversation Context", "enabled": bool(conversation_text), "content": conversation_text}
        ]

    def _conversation_context(self):
        lines = []
        for message in self.session.snapshot():
            role = message.get("role", "")
            if role == "system":
                continue
            content = str(message.get("content", "")).strip()
            if content:
                lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    def _load_session(self, conversation_id):
        if not conversation_id:
            session = ChatSession(DEFAULT_SYSTEM_CONTEXT)
            return session, None
        data = self.conversation_manager.load(str(conversation_id))
        session = ChatSession(DEFAULT_SYSTEM_CONTEXT)
        session.replace(data.get("messages", []))
        return session, data

    @staticmethod
    def _conversation_title(existing=None):
        title = str(existing or "").strip()
        return title or "New Conversation"

    def _conversation_metadata(self, sections):
        persona = self.persona_store.status(
            settings.get("persona.enabled", True),
            self.persona_store.load(update_timestamp=False)
        )
        return {
            "source": "mobile",
            "persona": {
                "enabled": bool(persona.get("enabled", False)),
                "name": persona.get("name", ""),
                "rules_count": persona.get("rules_count", 0)
            },
            "context": {
                "persona": any(item["name"] == "Persona" and item["enabled"] for item in sections),
                "memory": any(item["name"] == "Memory" and item["enabled"] for item in sections),
                "knowledge": any(item["name"] == "Knowledge" and item["enabled"] for item in sections),
                "conversation": any(item["name"] == "Conversation Context" and item["enabled"] for item in sections)
            }
        }

    @staticmethod
    def _conversation_payload(data):
        metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}
        messages = data.get("messages", []) if isinstance(data, dict) else []
        if not isinstance(messages, list):
            messages = []
        return {
            "ok": True,
            "id": str(data.get("id", "")),
            "conversation_id": str(data.get("id", "")),
            "title": str(data.get("title", "New Conversation")),
            "created_at": str(data.get("created_at", "")),
            "updated_at": str(data.get("updated_at", "")),
            "model": str(data.get("model", "")),
            "source": str(metadata.get("source", "desktop")),
            "metadata": metadata,
            "messages": messages
        }

    def list_conversations(self):
        records = []
        for record in self.conversation_manager.list_conversations():
            metadata = record.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            records.append({
                "id": record.get("id", ""),
                "conversation_id": record.get("id", ""),
                "title": record.get("title", "New Conversation"),
                "created_at": record.get("created_at", ""),
                "updated_at": record.get("updated_at", ""),
                "model": record.get("model", ""),
                "source": str(metadata.get("source", "desktop")),
                "metadata": metadata
            })
        return {
            "ok": True,
            "conversations": records
        }

    def load_conversation(self, conversation_id):
        if not str(conversation_id or "").strip():
            return self._error("Invalid Request", detail="Missing conversation id.", stage="conversation_load")
        try:
            data = self.conversation_manager.load(str(conversation_id).strip())
        except (OSError, ValueError, json.JSONDecodeError, TypeError) as error:
            return self._error("Invalid Request", detail=error, stage="conversation_load")
        return self._conversation_payload(data)

    def new_conversation(self):
        return {
            "ok": True,
            "conversation_id": "",
            "title": "New Conversation",
            "messages": [],
            "metadata": {
                "source": "mobile",
                "persona": {},
                "context": {}
            },
            "deferred": True
        }

    def handle_request(self, message, conversation_id=None):
        started_at = time.perf_counter()
        model = ""
        ollama_status = {}
        self._emit("Mobile request stage")
        status = self.access_status()
        if not status["remote_enabled"]:
            self._record_mobile_debug("Failed", "remote_check", "Remote Disabled")
            self._emit("Mobile chat failed")
            self._emit("Failure stage: remote_check")
            self._emit("Failure reason: Remote Disabled")
            return self._error("Remote Disabled", status, stage="remote_check", reason="Remote Disabled")
        self._emit("Remote check passed")
        if not status["lan_chat_enabled"]:
            self._record_mobile_debug("Failed", "lan_chat_check", "LAN Chat Disabled")
            self._emit("Mobile chat failed")
            self._emit("Failure stage: lan_chat_check")
            self._emit("Failure reason: LAN Chat Disabled")
            return self._error("LAN Chat Disabled", status, stage="lan_chat_check", reason="LAN Chat Disabled")
        self._emit("LAN Chat check passed")

        try:
            prompt = self.validate_message(message)
        except ValueError as error:
            self._record_mobile_debug("Failed", "request_validation", error)
            self._emit("Mobile chat failed")
            self._emit("Failure stage: request_validation")
            self._emit(f"Failure reason: {error}")
            result = self._error("Invalid Request", status, error, stage="request_validation", reason=error)
            result["message"] = str(error)
            return result

        model = str(self.model_provider() or settings.get("chat_model", "qwen3:8b") or "").strip()
        if not model:
            self._record_mobile_debug("Failed", "model_check", "Model not configured")
            self._emit("Mobile chat failed")
            self._emit("Failure stage: model_check")
            self._emit("Failure reason: Model not configured")
            return self._error("Ollama Unavailable", status, "Model not configured.", stage="model_check", reason="Model not configured.")

        self._emit("Mobile Ollama check started")
        self._emit("Ollama check started")
        ollama_status = self.check_ollama_ready(model)
        if not ollama_status.get("ok"):
            failure_key = (
                "Model Cannot Chat"
                if not ollama_status.get("chat_support", True)
                else "Model Unavailable"
                if not ollama_status.get("model_available") and ollama_status.get("api_available")
                else "Ollama Unavailable"
            )
            if failure_key == "Model Cannot Chat":
                self._emit("Embedding model blocked from chat")
            if failure_key == "Model Unavailable":
                self._emit("Model check failed")
            self._emit("Mobile Ollama failed")
            self._emit("Mobile Ollama check failed")
            self._record_mobile_debug(
                "Failed",
                "ollama_check",
                ollama_status.get("reason", "Ollama unavailable"),
                int((time.perf_counter() - started_at) * 1000),
                model,
                ollama_status
            )
            self._emit("Mobile chat failed")
            self._emit("Failure stage: model_capability" if failure_key == "Model Cannot Chat" else "ollama_connection")
            self._emit(f"Failure reason: {ollama_status.get('reason', 'Ollama unavailable')}")
            return self._error(
                failure_key,
                status,
                self._debug_detail_payload(ollama_status) if self._debug_enabled() else ollama_status.get("reason", "Ollama unavailable"),
                stage="model_capability" if failure_key == "Model Cannot Chat" else "ollama_connection",
                reason=ollama_status.get("reason", "Ollama unavailable")
            )
        self._emit("Mobile Ollama request started")
        self._emit("Ollama request started")

        try:
            request_timeout = max(1, int(settings.get("mobile_chat_timeout", DEFAULT_MOBILE_CHAT_TIMEOUT)))
        except (TypeError, ValueError):
            request_timeout = DEFAULT_MOBILE_CHAT_TIMEOUT

        with self._lock:
            try:
                loaded_conversation = None
                try:
                    self.session, loaded_conversation = self._load_session(conversation_id)
                except (OSError, ValueError, json.JSONDecodeError, TypeError):
                    self.session = ChatSession(DEFAULT_SYSTEM_CONTEXT)
                    loaded_conversation = None
                    conversation_id = None

                try:
                    sections = self.build_context_sections(prompt)
                except Exception as error:
                    self._record_mobile_debug(
                        "Failed",
                        "context_build",
                        error,
                        int((time.perf_counter() - started_at) * 1000),
                        model,
                        ollama_status
                    )
                    self._emit("Mobile chat failed")
                    self._emit("Failure stage: context_build")
                    self._emit(f"Failure reason: {error}")
                    return self._error("Context Build Failed", status, error, stage="context_build", reason=error)

                final_context = assemble_final_prompt(sections)
                messages = [{"role": "system", "content": final_context or DEFAULT_SYSTEM_CONTEXT}]
                messages.extend(
                    item for item in self.session.snapshot()
                    if item.get("role") in {"user", "assistant"}
                )
                messages.append({"role": "user", "content": prompt})
                response = chat_with_messages(model, messages, timeout=request_timeout)
                self._emit("Ollama response received")
                self.session.add_user(prompt)
                self.session.add_assistant(response)
                saved_conversation = self.conversation_manager.save(
                    conversation_id,
                    model,
                    self.session.snapshot(),
                    title=self._conversation_title((loaded_conversation or {}).get("title")),
                    created_at=(loaded_conversation or {}).get("created_at"),
                    metadata=self._conversation_metadata(sections)
                )
                conversation_id = saved_conversation.get("id")
            except (socket.timeout, TimeoutError) as error:
                self._record_mobile_debug(
                    "Failed",
                    "ollama_request",
                    error,
                    int((time.perf_counter() - started_at) * 1000),
                    model,
                    ollama_status
                )
                self._emit("Mobile request timeout")
                self._emit("Mobile chat failed")
                self._emit("Failure stage: ollama_request")
                self._emit(f"Failure reason: {error}")
                return self._error("Request Timeout", status, error, stage="ollama_request", reason=error)
            except ChatError as error:
                category = getattr(error, "category", "chat_generation_failed")
                stage = getattr(error, "stage", "ollama_request")
                if category == "timeout":
                    key = "Request Timeout"
                elif category == "model_capability":
                    key = "Model Cannot Chat"
                elif category in {"ollama_unavailable", "model_unavailable"}:
                    key = "Model Unavailable" if category == "model_unavailable" else "Ollama Unavailable"
                elif category == "invalid_response":
                    key = "Invalid Response"
                else:
                    key = "Chat Generation Failed"
                if key == "Ollama Unavailable":
                    self._emit("Mobile Ollama failed")
                if key == "Model Unavailable":
                    self._emit("Model check failed")
                if key == "Model Cannot Chat":
                    self._emit("Embedding model blocked from chat")
                self._record_mobile_debug(
                    "Failed",
                    stage,
                    error,
                    int((time.perf_counter() - started_at) * 1000),
                    model,
                    ollama_status
                )
                self._emit("Mobile chat failed")
                self._emit(f"Failure stage: {stage}")
                self._emit(f"Failure reason: {error}")
                return self._error(key, status, error, stage=stage, reason=error)
            except Exception as error:
                self._record_mobile_debug(
                    "Failed",
                    "unknown",
                    error,
                    int((time.perf_counter() - started_at) * 1000),
                    model,
                    ollama_status
                )
                self._emit("Mobile chat failed")
                self._emit("Failure stage: unknown")
                self._emit(f"Failure reason: {error}")
                return self._error("AI Response Failed", status, error, stage="unknown", reason=error)

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        self._record_mobile_debug("Success", "completed", "", duration_ms, model, ollama_status)
        self._emit("Mobile debug updated")
        result = {
            "ok": True,
            "response": self._limit_response(response),
            "model": model,
            "conversation_id": conversation_id,
            "duration_ms": duration_ms,
            "generated_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": status,
            "context": {
                "persona": any(item["name"] == "Persona" and item["enabled"] for item in sections),
                "memory": any(item["name"] == "Memory" and item["enabled"] for item in sections),
                "knowledge": any(item["name"] == "Knowledge" and item["enabled"] for item in sections),
                "conversation": any(item["name"] == "Conversation Context" and item["enabled"] for item in sections)
            }
        }
        if self._debug_enabled():
            result["debug"] = {
                "stage": "completed",
                "ollama": ollama_status,
                "context_sections": [
                    {
                        "name": item.get("name"),
                        "enabled": item.get("enabled"),
                        "characters": len(str(item.get("content", "") or ""))
                    }
                    for item in sections
                ]
            }
        return result
