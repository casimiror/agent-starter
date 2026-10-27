"""The only place where concrete classes are wired together."""

from datetime import timedelta
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session, sessionmaker

from app.agents.assistant_agent import build_assistant_agent
from app.core.config import get_settings
from app.core.dedupe import RecentIds
from app.core.llm import build_chat_models
from app.db.daos.conversation_dao import ConversationDAO
from app.db.daos.message_dao import MessageDAO
from app.db.daos.message_feedback_dao import MessageFeedbackDAO
from app.db.session import build_session_factory
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.feedback_repository import FeedbackRepository
from app.services.channel_conversations import ChannelConversations
from app.services.chat_service import ChatService
from app.services.feedback_service import FeedbackService
from app.services.whatsapp_service import WhatsAppService
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
    # A timeout, so a stuck Twilio call can't hold the per-visitor lock forever.
    http = TwilioHttpClient(timeout=15)
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
