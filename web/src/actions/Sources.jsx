/**
 * action.type === "sources" — trích dẫn của US3 (RAG).
 *
 * Hiện `score` vì quy tắc trong project-policy-rag.md: retrieval dưới ngưỡng thì
 * agent PHẢI từ chối. Cho người dùng thấy độ khớp giúp kiểm chứng agent có tuân
 * thủ hay không, thay vì tin lời nó.
 */
export default function Sources({ action }) {
  const items = action.items || [];
  if (!items.length) return null;

  return (
    <details className="sources">
      <summary>{items.length} nguồn tham chiếu</summary>
      <ul>
        {items.map((s, i) => (
          <li key={s.doc_id || i}>
            <b>{s.doc_id}</b>
            {typeof s.score === "number" && (
              <span className="muted"> · khớp {(s.score * 100).toFixed(0)}%</span>
            )}
            {s.chunk && <blockquote>{s.chunk}</blockquote>}
          </li>
        ))}
      </ul>
    </details>
  );
}
