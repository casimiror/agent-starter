import { ChatWindow } from "./features/chat/components/ChatWindow";
import { EvalDashboard } from "./features/eval/components/EvalDashboard";

// Two pages and no router dependency: FastAPI's SPA fallback serves index.html for /eval.
export function App() {
  if (window.location.pathname.replace(/\/$/, "") === "/eval") {
    return (
      <main className="app app--page">
        <EvalDashboard />
      </main>
    );
  }
  return (
    <main className="app">
      <ChatWindow />
    </main>
  );
}
