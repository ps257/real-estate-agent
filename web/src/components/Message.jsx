import ActionView from "../actions";

/** Một lượt trong hội thoại. `role` là "user" | "agent". */
export default function Message({ msg, onSend }) {
  if (msg.role === "user") {
    return (
      <div className="turn user">
        <div className="bubble">{msg.text}</div>
      </div>
    );
  }

  return (
    <div className="turn agent">
      <div className="avatar" aria-hidden="true">🏠</div>

      <div>
        <div className="bubble">
          {msg.pending ? <Dots /> : msg.text}
          {msg.error && <span className="err">{msg.error}</span>}
        </div>

        {(msg.actions || []).map((a, i) => (
          <ActionView key={`${a.type}-${i}`} action={a} onSend={onSend} />
        ))}

        {/* Chain-of-thought luôn hiện: dấu vết 6 node là thứ chứng minh pipeline
            PRD đang chạy thật. Gấp trong <details> nên không choán chỗ. Nếu đưa
            cho khách hàng thật thì nên bỏ — nó lộ tên tool, project_id, ngưỡng
            confidence. */}
        {msg.reasoning && (
          <details className="cot">
            <summary>
              intent={msg.intent ?? "—"} · {(msg.tool_calls || []).length} tool call
            </summary>
            <pre>{msg.reasoning.join("\n")}</pre>
            {!!(msg.tool_calls || []).length && (
              <pre>{JSON.stringify(msg.tool_calls, null, 2)}</pre>
            )}
          </details>
        )}
      </div>
    </div>
  );
}

/** Mỗi lượt mất ~4-6s (3 LLM call tuần tự + MCP) nên cần tín hiệu chờ rõ ràng. */
function Dots() {
  return (
    <span className="dots" aria-label="đang xử lý">
      <i />
      <i />
      <i />
    </span>
  );
}
