import { Fragment, useEffect, useRef } from "react";
import type { ChatMessage, Rating } from "../types";
import { FeedbackButtons } from "./FeedbackButtons";
import { MessageContent } from "./MessageContent";

interface Props {
  messages: ChatMessage[];
  pending: boolean;
  onRate: (message: ChatMessage, rating: Rating | null) => void;
}

export function MessageList({ messages, pending, onRate }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  // Braces matter: newer Chrome returns a Promise from scrollIntoView, and an effect must not
  // return anything but a cleanup function (React would call the Promise and crash).
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pending]);

  return (
    <div className="chat__messages" aria-live="polite">
      {messages.map((m) => (
        <Fragment key={m.id}>
          <div className={`bubble bubble--${m.role}`}>
            <MessageContent role={m.role} content={m.content} />
          </div>
          {m.rateable && (
            <FeedbackButtons rating={m.rating ?? null} onRate={(rating) => onRate(m, rating)} />
          )}
        </Fragment>
      ))}
      {pending && <div className="bubble bubble--assistant bubble--typing">…</div>}
      <div ref={endRef} />
    </div>
  );
}
