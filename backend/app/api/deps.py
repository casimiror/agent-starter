"""The only place where concrete classes are wired together."""

import time
from collections.abc import Callable
from datetime import timedelta
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session, sessionmaker

from app.agents.assistant_agent import ASSISTANT_PROMPT, assistant_guardrails, build_assistant_agent
from app.agents.builder import load_prompt
from app.clients.openai_realtime import OpenAIRealtimeConnector
from app.core.config import get_settings
from app.core.dedupe import RecentIds
from app.core.llm import build_chat_models
from app.db.daos.conversation_dao import ConversationDAO
from app.db.daos.message_dao import MessageDAO
from app.db.daos.message_feedback_dao import MessageFeedbackDAO
from app.db.session import build_session_factory
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.feedback_repository import FeedbackRepository
from app.services.channels.conversations import ChannelConversations
from app.services.channels.voice.realtime.service import RealtimeVoiceService
from app.services.channels.voice.service import VoiceService
from app.services.channels.whatsapp.service import WhatsAppService
from app.services.chat_service import ChatService
from app.services.feedback_service import FeedbackService
from app.tools.registry import ToolDeps, build_assistant_tools

if TYPE_CHECKING:
    from app.clients.whatsapp_sender import WhatsAppSender
    from app.services.eval_service import EvalService


@lru_cache
def get_sessions() -> sessionmaker[Session]:
    """One engine per process, shared by every service."""
    return build_session_factory(get_settings())


@lru_cache
def get_tool_deps() -> ToolDeps:
    """Repositories and clients the tools need; add them here when a tool needs one."""
    return ToolDeps(settings=get_settings())


@lru_cache
def get_chat_service() -> ChatService:
    settings = get_settings()
    sessions = get_sessions()

    conversations = ConversationRepository(ConversationDAO(sessions), MessageDAO(sessions))
    tools = build_assistant_tools(get_tool_deps())
    agent = build_assistant_agent(build_chat_models(settings), tools, settings)
    return ChatService(conversations, agent, settings.max_history_messages, settings.llm_model)


@lru_cache
def get_channel_conversations() -> ChannelConversations:
    """Shared by every non-web channel router (docs/channels.md). One instance per process, so
    the per-visitor locks are shared."""
    settings = get_settings()
    sessions = get_sessions()
    conversations = ConversationRepository(ConversationDAO(sessions), MessageDAO(sessions))
    window = timedelta(hours=settings.conversation_window_hours)
    return ChannelConversations(conversations, settings.channel_id_secret, window)


@lru_cache
def get_whatsapp_sender() -> "WhatsAppSender":
    # Imported here so a deployment without WhatsApp never loads the Twilio SDK.
    from twilio.http.http_client import TwilioHttpClient
    from twilio.rest import Client

    from app.clients.whatsapp_sender import WhatsAppSender

    settings = get_settings()
    # A short timeout, so a stuck Twilio call can't hold the sender's send lock for long.
    http = TwilioHttpClient(timeout=settings.twilio_send_timeout_seconds)
    client = Client(settings.twilio_account_sid, settings.twilio_auth_token, http_client=http)
    return WhatsAppSender(client)


@lru_cache
def get_whatsapp_service() -> WhatsAppService:
    return WhatsAppService(
        get_channel_conversations(),
        get_chat_service(),
        get_whatsapp_sender(),
        get_settings().rate_limit_whatsapp,
    )


@lru_cache
def get_whatsapp_dedupe() -> RecentIds:
    """Twilio retries seen in the last minutes. Per process (docs/channels.md)."""
    return RecentIds()


@lru_cache
def get_voice_service() -> VoiceService:
    settings = get_settings()
    return VoiceService(
        get_channel_conversations(),
        get_chat_service(),
        settings.rate_limit_voice,
        settings.voice_link_phrase,
        settings.voice_max_call_seconds,
    )


@lru_cache
def get_realtime_connector() -> OpenAIRealtimeConnector:
    """Opens the connection to the speech-to-speech model. Tests replace it with a fake."""
    settings = get_settings()
    return OpenAIRealtimeConnector(settings.openai_api_key, settings.voice_realtime_model)


@lru_cache
def get_realtime_voice_service() -> RealtimeVoiceService:
    """The assistant's prompt, tools and guardrails for the realtime voice mode: the same
    definitions the text agent is built from (`get_chat_service`)."""
    settings = get_settings()
    sessions = get_sessions()
    conversations = ConversationRepository(ConversationDAO(sessions), MessageDAO(sessions))
    input_guardrails, output_guardrails = assistant_guardrails(settings)
    return RealtimeVoiceService(
        get_voice_service(),
        conversations,
        build_assistant_tools(get_tool_deps()),
        load_prompt(ASSISTANT_PROMPT),
        input_guardrails,
        output_guardrails,
        model=settings.voice_realtime_model,
        voice_name=settings.voice_realtime_voice,
        transcription_model=settings.voice_realtime_transcription_model,
        greeting=settings.voice_greeting,
    )


def get_relay_clock() -> Callable[[], float]:
    """The clock a ConversationRelay session measures the call with; tests replace it."""
    return time.monotonic


@lru_cache
def get_feedback_service() -> FeedbackService:
    sessions = get_sessions()
    return FeedbackService(FeedbackRepository(MessageDAO(sessions), MessageFeedbackDAO(sessions)))


@lru_cache
def get_eval_service() -> "EvalService":
    """Local-only: the router is mounted when EVAL_ENABLED is true. Imports stay inside so the
    deployed app never loads the evaluator."""
    from app.evals.agent_run import eval_tool_deps
    from app.evals.runner import Evaluator
    from app.evals.store import RunStore
    from app.services.eval_service import EvalService
    from app.tools.registry import build_retriever

    settings = get_settings()
    has_retriever = build_retriever(eval_tool_deps(settings)) is not None
    return EvalService(lambda: Evaluator(settings), RunStore(), retrieval_available=has_retriever)
