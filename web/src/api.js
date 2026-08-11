/** Lớp gọi agent. Chỉ một endpoint — POST /chat. */

/**
 * Gửi một lượt chat.
 *
 * Dùng /chat (non-stream) chứ không /v1/chat/completions: endpoint /v1 tồn tại
 * để tương thích OpenAI SDK, ở đó `actions` bị chôn trong field mở rộng
 * `delta.agent` và khó lấy hơn hẳn mà không được gì.
 *
 * @param {string} message
 * @param {string} threadId  Khoá hội thoại — cùng giá trị thì agent nhớ slot
 *                           của lượt trước (checkpointer key theo đây).
 * @returns {Promise<{thread_id, intent, text, reasoning, tool_calls, actions}>}
 */
export async function sendChat(message, threadId, { signal } = {}) {
  const res = await fetch("/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, thread_id: threadId }),
    signal,
  });
  if (!res.ok) {
    // Agent trả 500 khi MCP chết hoặc node ném exception — hiện nguyên trạng
    // thay vì nuốt, để còn chẩn đoán được.
    throw new Error(`Agent trả HTTP ${res.status}`);
  }
  return res.json();
}
