import { APP } from "../../../config";
import { useChat } from "../hooks/useChat";
import { MessageInput } from "./MessageInput";
import { MessageList } from "./MessageList";

// Container: wires the hook to presentational components.
export function ChatWindow() {
  const { messages, pending, error, send, rate } = useChat();
  return (
    <section className="chat">
      <header className="chat__header">{APP.name}</header>
      <MessageList messages={messages} pending={pending} onRate={rate} />
      {error && <p className="chat__error" role="alert">{error}</p>}
      <MessageInput disabled={pending} onSend={send} />
    </section>
  );
}
