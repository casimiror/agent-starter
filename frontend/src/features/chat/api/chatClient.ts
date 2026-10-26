import type { ChatRequest, ChatResponse, FeedbackRequest, Rating } from "../types";

export class ChatApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

// The only place that knows the HTTP contract.
export async function sendMessage(body: ChatRequest): Promise<ChatResponse> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 429) {
    throw new ChatApiError("You're sending messages too fast. Wait a moment and try again.", 429);
  }
  if (!res.ok) {
    throw new ChatApiError("Something went wrong on our side. Please try again.", res.status);
  }
  return res.json();
}

/** Set (PUT) or remove (DELETE, rating null) the visitor's vote on an assistant reply. */
export async function rateMessage(messageId: string, rating: Rating | null): Promise<void> {
  const url = `/api/messages/${encodeURIComponent(messageId)}/feedback`;
  const body: FeedbackRequest | undefined = rating ? { rating } : undefined;
  const res = await fetch(url, {
    method: rating ? "PUT" : "DELETE",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 429) {
    throw new ChatApiError("Too many votes in a short time. Try again in a moment.", 429);
  }
  if (!res.ok) {
    throw new ChatApiError("We couldn't save your feedback. Please try again.", res.status);
  }
}
