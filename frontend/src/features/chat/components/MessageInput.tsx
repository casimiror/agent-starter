import { useState, type FormEvent } from "react";
import { APP } from "../../../config";

interface Props {
  disabled: boolean;
  onSend: (text: string) => void;
}

export function MessageInput({ disabled, onSend }: Props) {
  const [text, setText] = useState("");

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    onSend(text);
    setText("");
  }

  return (
    <form className="chat__input" onSubmit={submit}>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={APP.placeholder}
        maxLength={2000}
        aria-label="Message"
      />
      <button type="submit" disabled={disabled || !text.trim()}>
        Send
      </button>
    </form>
  );
}
