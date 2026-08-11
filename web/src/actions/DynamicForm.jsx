import { useState } from "react";

/**
 * action.type === "form" — spec do start_visit_booking / start_consultation trả về.
 *
 * Field được dựng ĐỘNG từ spec.fields, không hard-code: MCP trả bộ field khác
 * nhau giữa case đã đăng nhập và chưa (chưa authen phải thu thập thêm tên/SĐT).
 */
export default function DynamicForm({ action }) {
  const spec = action.form || {};
  const fields = spec.fields || [];
  const [submitted, setSubmitted] = useState(null);

  function handleSubmit(e) {
    e.preventDefault();
    const payload = Object.fromEntries(new FormData(e.currentTarget));
    // submit_booking là thao tác GHI duy nhất của MCP, nhưng tools_node chưa có
    // nhánh gọi nó — form mới chỉ MỞ được, chưa lưu. Hiện payload để kiểm tra
    // thay vì giả vờ đã gửi thành công.
    setSubmitted(payload);
  }

  if (!fields.length) return <p className="muted">(form không có trường nào)</p>;

  return (
    <form className="form" onSubmit={handleSubmit}>
      <p className="muted">
        {spec.action} · {spec.project?.name || ""}
        {spec.authenticated === false && " · chưa đăng nhập"}
      </p>

      {fields.map((f) => (
        <label key={f.name} className="field">
          <span>
            {f.label || f.name}
            {f.required && <b className="req"> *</b>}
          </span>
          {f.type === "textarea" ? (
            <textarea name={f.name} required={f.required} rows={3} />
          ) : (
            <input
              name={f.name}
              type={f.type || "text"}
              required={f.required}
              placeholder={f.placeholder || ""}
            />
          )}
        </label>
      ))}

      <button type="submit" className="primary" disabled={!!submitted}>
        Gửi thông tin
      </button>

      {submitted && (
        <div className="note">
          <b>Chưa lưu.</b> Agent chưa nối <code>submit_booking</code>. Payload:
          <pre>{JSON.stringify(submitted, null, 2)}</pre>
        </div>
      )}
    </form>
  );
}
