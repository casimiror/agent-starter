import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Role } from "../types";

// Links leave the chat in a new tab. react-markdown never renders raw HTML, so model output
// can't inject markup; the backend's output guardrail already limits which URLs appear.
const components: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
};

interface Props {
  role: Role;
  content: string;
}

/** Assistant replies are Markdown; user text is shown exactly as typed. */
export function MessageContent({ role, content }: Props) {
  if (role === "user") return <>{content}</>;
  return (
    <div className="markdown">
      <Markdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </Markdown>
    </div>
  );
}
