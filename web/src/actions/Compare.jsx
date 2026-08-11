import { vnd, area, propertyType, isEstimate } from "../format";

/**
 * action.type === "compare" — kết quả compare_listings:
 *   {listings: [detail...], fields: ["price", "area", "bedrooms", ...]}
 *
 * `fields` do MCP quyết định hàng nào hiển thị. CỐ Ý không tô màu "căn tốt hơn"
 * hay xếp hạng: tư vấn "căn nào đáng mua hơn" nằm trong Out of scope của PRD,
 * và guardrail cũng chặn ở đầu vào — UI không được lách qua cửa sau.
 */
export default function Compare({ action }) {
  const { listings = [], fields = [] } = action.comparison || {};
  if (!listings.length) return <p className="muted">(không có gì để so sánh)</p>;

  return (
    <div className="scroll-x">
      <table className="grid">
        <thead>
          <tr>
            <th />
            {listings.map((l) => (
              <th key={l.id}>{l.title || l.id}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fields.map((f) => (
            <tr key={f}>
              <th>{FIELD_LABELS[f] || f}</th>
              {listings.map((l) => (
                <td key={l.id}>{cell(l, f)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const FIELD_LABELS = {
  price: "Giá",
  area: "Diện tích",
  bedrooms: "Phòng ngủ",
  bathrooms: "Phòng tắm",
  property_type: "Loại hình",
  direction: "Hướng",
  view: "View",
  legal_status: "Pháp lý",
  furnishing: "Nội thất",
};

/** `fields` dùng tên rút gọn ("price"), card dùng tên đầy đủ ("price_vnd"). */
function cell(l, field) {
  if (field === "price") {
    return `${vnd(l.price_vnd)}${isEstimate(l.price_type) ? " (ước tính)" : ""}`;
  }
  if (field === "area") return area(l.area_m2);
  if (field === "property_type") return propertyType(l.property_type);
  const v = l[field];
  if (v == null || v === "") return "—";
  return typeof v === "boolean" ? (v ? "Có" : "Không") : String(v);
}
