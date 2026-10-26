export type Role = "user" | "assistant";
export type Rating = "up" | "down";

export interface ChatMessage {
  id: string; // the server's message id for replies, so feedback can point at it
  role: Role;
  content: string;
  rateable?: boolean; // stored replies only; not the local greeting
  rating?: Rating | null;
}

// Mirrors backend app/schemas/chat.py
export interface ChatRequest {
  conversation_id: string | null;
  visitor_id: string | null;
  message: string;
}

export interface ChatResponse {
  conversation_id: string;
  message_id: string;
  reply: string;
}

export interface FeedbackRequest {
  rating: Rating;
}
