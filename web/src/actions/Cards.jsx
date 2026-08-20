import { useState } from "react";
import { vnd, area, propertyType, isEstimate } from "../format";

/** action.type === "cards" — kết quả search_listings / search_listings_by_province. */
export default function Cards({ action }) {
  const items = action.items || [];
  if (!items.length) return <p className="muted">Không có căn nào khớp tiêu chí.</p>;

  return (
    <div className="cards">
      {items.map((it) => (
        <Card key={it.id} it={it} />
      ))}
    </div>
  );
}

function Card({ it }) {
  // Ảnh từ nguồn ngoài (market.vinhomes.vn) có thể 404 hoặc bị chặn — hạ xuống
  // placeholder thay vì để icon ảnh vỡ.
  const [broken, setBroken] = useState(false);
  const facts = [
    propertyType(it.property_type),
    it.bedrooms ? `${it.bedrooms} PN` : null,
    it.bathrooms ? `${it.bathrooms} WC` : null,
    it.area_m2 ? area(it.area_m2) : null,
  ].filter(Boolean);

  return (
    <article className="card">
      <div className="thumb">
        {it.thumbnail && !broken ? (
          <img
            src={it.thumbnail}
            alt=""
            loading="lazy"
            onError={() => setBroken(true)}
          />
        ) : (
          <div className="ph">🏢</div>
        )}
        {it.status && <span className="badge">{it.status}</span>}
      </div>

      <div className="body">
        <h4>{it.title || it.id}</h4>

        <p className="price">
          {vnd(it.price_vnd)}
          {/* PRD: luôn đọc price_type trước khi quote price_vnd */}
          {isEstimate(it.price_type) && <span className="est"> ước tính</span>}
        </p>

        <p className="facts">
          {facts.map((f) => (
            <span className="fact" key={f}>{f}</span>
          ))}
        </p>

        <div className="foot">
          <span className="muted">
            {it.price_per_m2_vnd ? `${vnd(it.price_per_m2_vnd)}/m²` : ""}
          </span>
          {it.url && (
            <a href={it.url} target="_blank" rel="noopener noreferrer">
              Chi tiết ↗
            </a>
          )}
        </div>
      </div>
    </article>
  );
}
