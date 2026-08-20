/**
 * Hai action cùng dạng "hàng nút bấm", khác nhau ở CHỖ LẤY NHÃN và CHỖ LẤY
 * GIÁ TRỊ GỬI ĐI:
 *
 *   cta      items[].label       -> gửi chính label. Node intent có rule khớp
 *                                   chính xác 4 nhãn CTA nên không tốn LLM call.
 *   clarify  suggestions[].label -> gửi suggestions[].value (label có kèm tên
 *                                   tỉnh cho khách dễ phân biệt; value mới là
 *                                   thứ agent resolve được).
 */

export function Cta({ action, onSend }) {
  const items = action.items || [];
  if (!items.length) return null;
  return (
    <div className="chips">
      {items.map((b, i) => (
        <button key={b.action || i} className="chip" onClick={() => onSend(b.label)}>
          {b.label}
        </button>
      ))}
    </div>
  );
}

export function Clarify({ action, onSend }) {
  const items = action.suggestions || [];
  if (!items.length) return null;   // prompt đã nằm trong bubble text rồi
  return (
    <div className="chips">
      {items.map((s, i) => (
        <button
          key={s.project_id || s.value || i}
          className="chip"
          onClick={() => onSend(s.value || s.label)}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}
