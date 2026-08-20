import { vnd, propertyType } from "../format";

/**
 * action.type === "overview" — kết quả project_overview:
 *   {project: {...}, stats: {count, price_vnd, price_per_m2_vnd, area_m2,
 *                            bedrooms_range, by_property_type}}
 *
 * Các khoá thống kê là dict lồng (min/max/avg/median tuỳ tool), nên render
 * theo cấu trúc thay vì đoán tên field cụ thể.
 */
export default function Overview({ action }) {
  const { project, stats } = action.overview || {};
  if (!stats) return <p className="muted">(không có số liệu)</p>;

  const mix = stats.by_property_type || {};
  const total = Object.values(mix).reduce((a, b) => a + (Number(b) || 0), 0);

  return (
    <div className="panel">
      <h4>
        {project?.name || "Dự án"}
        {project?.province && <span className="muted"> · {project.province}</span>}
      </h4>

      <p className="big">
        {stats.count ?? "—"} <span className="muted">căn</span>
      </p>

      <div className="stat-grid">
        <StatBlock label="Giá" data={stats.price_vnd} fmt={vnd} />
        <StatBlock label="Giá / m²" data={stats.price_per_m2_vnd} fmt={vnd} />
        <StatBlock label="Diện tích (m²)" data={stats.area_m2} />
        <StatBlock label="Phòng ngủ" data={stats.bedrooms_range} />
      </div>

      {total > 0 && (
        <>
          <h5>Cơ cấu loại hình</h5>
          {Object.entries(mix)
            .sort((a, b) => b[1] - a[1])
            .map(([code, n]) => (
              <div className="bar-row" key={code}>
                <span className="bar-label">{propertyType(code)}</span>
                <span className="bar-track">
                  <span className="bar-fill" style={{ width: `${(n / total) * 100}%` }} />
                </span>
                <span className="bar-num">{n}</span>
              </div>
            ))}
        </>
      )}
    </div>
  );
}

/** Một cụm thống kê (min/max/avg/...) — không giả định trước tên khoá. */
function StatBlock({ label, data, fmt = (x) => x }) {
  if (!data || typeof data !== "object") return null;
  const rows = Object.entries(data).filter(([, v]) => v != null && typeof v !== "object");
  if (!rows.length) return null;
  return (
    <div className="stat">
      <div className="muted">{label}</div>
      {rows.map(([k, v]) => (
        <div key={k}>
          <span className="muted">{k}: </span>
          {typeof v === "number" ? fmt(v) : String(v)}
        </div>
      ))}
    </div>
  );
}
