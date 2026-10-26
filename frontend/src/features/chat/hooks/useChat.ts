import { useCallback, useState } from "react";
import { APP } from "../../../config";
import { ChatApiError, rateMessage, sendMessage } from "../api/chatClient";
import type { ChatMessage, Rating } from "../types";

const STORAGE_KEY = `${APP.storagePrefix}.conversationId`;
const VISITOR_KEY = `${APP.storagePrefix}.visitorId`;

function readConversationId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Anonymous id kept across conversations so Langfuse can group traces per visitor. */
function readOrCreateVisitorId(): string | null {
  try {
    let id = localStorage.getItem(VISITOR_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(VISITOR_KEY, id);
    }
    return id;
  } catch {
    return null; // private mode: traces just won't be tied to a visitor
  }
}

const GREETING: ChatMessage = {
  id: "greeting",
  role: "assistant",
  content: APP.greeting,
};

/** All chat state and side effects live here; components only render. */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([GREETING]);
  const [conversationId, setConversationId] = useState<string | null>(readConversationId);
  const [visitorId] = useState<string | null>(readOrCreateVisitorId);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || pending) return;
      setError(null);
      setMessages((m) => [...m, { id: crypto.randomUUID(), role: "user", content }]);
      setPending(true);
      try {
        const res = await sendMessage({
          conversation_id: conversationId,
          visitor_id: visitorId,
          message: content,
        });
        setConversationId(res.conversation_id);
        try {
          localStorage.setItem(STORAGE_KEY, res.conversation_id);
        } catch {
          /* private mode: conversation just won't survive a reload */
        }
        setMessages((m) => [
          ...m,
          { id: res.message_id, role: "assistant", content: res.reply, rateable: true, rating: null },
        ]);
      } catch (e) {
        setError(e instanceof ChatApiError ? e.message : "Network error. Check your connection.");
      } finally {
        setPending(false);
      }
    },
    [conversationId, visitorId, pending],
  );

  /** Optimistic: the thumb toggles at once and reverts if the server rejects the vote. */
  const rate = useCallback(async (message: ChatMessage, rating: Rating | null) => {
    const previous = message.rating ?? null;
    const setRating = (value: Rating | null) =>
      setMessages((m) => m.map((msg) => (msg.id === message.id ? { ...msg, rating: value } : msg)));
    setError(null);
    setRating(rating);
    try {
      await rateMessage(message.id, rating);
    } catch (e) {
      setRating(previous);
      setError(e instanceof ChatApiError ? e.message : "Network error. Check your connection.");
    }
  }, []);

  return { messages, pending, error, send, rate };
}
