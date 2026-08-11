import { useCallback, useEffect, useRef, useState } from "react";
import { sendChat } from "./api";
import Message from "./components/Message";
import "./styles.css";

const SAMPLES = [
  "Tìm căn hộ Vinhomes Grand Park",
  "Căn hộ 2 phòng ngủ dưới 5 tỷ ở Vinhomes Grand Park",
  "Đặt lịch tham quan Vinhomes",
  "Xem tổng quan dự án Vinhomes Grand Park",
  "Cho em xem bản đồ dự án Vinhomes Grand Park",
  "Bỏ tiền vào đây có ổn không?",
];

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  // Khoá hội thoại: cùng giá trị thì agent nhớ slot của lượt trước. Sinh một
  // lần cho mỗi phiên; đổi giá trị = bắt đầu cuộc mới.
  const [threadId, setThreadId] = useState(() => `web-${Date.now().toString(36)}`);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(
    async (text) => {
      const message = text.trim();
      if (!message || busy) return;

      setInput("");
      setBusy(true);
      setMessages((m) => [
        ...m,
        { role: "user", text: message },
        { role: "agent", pending: true },
      ]);

      try {
        const data = await sendChat(message, threadId);
        setMessages((m) => [
          ...m.slice(0, -1),
          {
            role: "agent",
            text: data.text || "(không có nội dung)",
            actions: data.actions || [],
            reasoning: data.reasoning,
            tool_calls: data.tool_calls,
            intent: data.intent,
          },
        ]);
      } catch (e) {
        setMessages((m) => [
          ...m.slice(0, -1),
          { role: "agent", text: "", error: e.message },
        ]);
      } finally {
        setBusy(false);
      }
    },
    [busy, threadId],
  );

  function reset() {
    setMessages([]);
    setThreadId(`web-${Date.now().toString(36)}`);
  }

  return (
    <div className="app">
      <header>
        <span className="logo" aria-hidden="true">🏠</span>
        <div>
          <h1>Trợ lý bất động sản</h1>
          <div className="sub">Tra cứu · Đặt lịch · Tư vấn</div>
        </div>
        <span className="grow" />
        <code className="thread" title="khoá hội thoại">{threadId}</code>
        <button className="ghost" onClick={reset}>Cuộc mới</button>
      </header>

      <main>
        {messages.length === 0 && (
          <div className="empty">
            <h2>Em có thể giúp gì cho anh/chị?</h2>
            <p>Tìm căn hộ, xem bản đồ dự án, so sánh các căn, hoặc đặt lịch tham quan.</p>
            <div className="chips">
              {SAMPLES.map((s) => (
                <button key={s} className="chip" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <Message key={i} msg={msg} onSend={send} />
        ))}
        <div ref={endRef} />
      </main>

      <footer>
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Nhắn cho trợ lý…"
            disabled={busy}
            autoFocus
          />
          <button type="submit" className="primary" disabled={busy || !input.trim()}>
            {busy ? "Đang xử lý…" : "Gửi"}
          </button>
        </form>
      </footer>
    </div>
  );
}
