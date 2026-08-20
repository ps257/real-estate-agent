/** Định dạng dùng chung. Tách riêng để test được và không lặp trong component. */

/** VNĐ -> "4,2 tỷ" / "800 triệu". null-safe. */
export function vnd(n) {
  if (n == null || Number.isNaN(n)) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(1).replace(/[.,]0$/, "")} tỷ`;
  if (n >= 1e6) return `${Math.round(n / 1e6)} triệu`;
  return n.toLocaleString("vi-VN");
}

/** m2 -> "84,5 m²". */
export const area = (n) => (n == null ? "—" : `${n} m²`);

/**
 * Nhãn loại hình. MCP dùng mã tiếng Việt không dấu (can_ho, lien_ke, ...) —
 * xem VALID_PROPERTY_TYPES trong agent/entities_llm.py.
 * Mã lạ thì trả nguyên, không nuốt dữ liệu.
 */
const PROPERTY_TYPES = {
  can_ho: "Căn hộ",
  lien_ke: "Liền kề",
  nha_pho: "Nhà phố",
  shophouse: "Shophouse",
  thuong_mai_dich_vu: "Thương mại dịch vụ",
  biet_thu_don_lap: "Biệt thự đơn lập",
  biet_thu_song_lap: "Biệt thự song lập",
  biet_thu_tu_lap: "Biệt thự tứ lập",
};
export const propertyType = (code) => PROPERTY_TYPES[code] || code || "—";

/**
 * price_type là QUY TẮC NGHIỆP VỤ, không phải chi tiết hiển thị: PRD bắt buộc
 * phân biệt giá chào bán với giá ước tính trước khi quote. Hiện giá ước tính
 * như giá bán là sai lệch thông tin.
 */
export const isEstimate = (priceType) => priceType === "estimate";
