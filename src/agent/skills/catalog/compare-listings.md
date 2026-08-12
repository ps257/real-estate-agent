---
name: compare-listings
intent: US6_COMPARE
description: So sánh chi tiết 2-4 BĐS trong cùng dự án hoặc khác khu vực/tỉnh thành
tools:
  - compare_listings
  - compare_nearby_amenities
  - calculate_commute_matrix
required_slots:
  - listing_ids
clarify_prompt: >
  Dạ anh/chị muốn so sánh những căn nào ạ? Vui lòng chọn từ 2 đến 4 căn giúp em nhé.
---

# US6 — So sánh Bất Động Sản (Compare Listings)

Kỹ năng này phục vụ nhu cầu so sánh trực quan từ 2 đến 4 bất động sản cụ thể (dựa trên danh sách `listing_ids`).

## 1. Mục tiêu & Nguyên tắc Nghiệp vụ
- **Số lượng so sánh:** Bắt buộc tối thiểu 2 căn và tối đa 4 căn.
- **Tính khách quan:** Tuyệt đối KHÔNG đưa ra kết luận chủ quan ("căn nào đáng mua hơn", "nên mua căn nào"). Chỉ trình bày số liệu và chênh lệch khách quan.
- **Phân biệt loại giá (`price_type`):**
  - "asking": Giá chào bán thật từ người bán / chủ đầu tư.
  - "estimate": Giá tham khảo do nguồn phân tích ước tính (không phải giá chào bán thực tế).
- **Thứ tự trình bày:** Sắp xếp danh sách căn theo thứ tự **giá tăng dần (`price_vnd`)**.

## 2. Các MCP Tools khả dụng
- `compare_listings(listing_ids=[...])`: Trả về dữ liệu chi tiết các căn, các trường so sánh (`fields`), đánh giá bối cảnh (`context`), chênh lệch (`deltas`) và huy hiệu số liệu nổi bật (`highlights`).
- `compare_nearby_amenities(listing_ids=[...])`: (Tùy chọn) So sánh khoảng cách tới các tiện ích lân cận (trường học, bệnh viện, TTTM, công viên).

## 3. Cấu trúc Action sinh ra cho Mobile UI
1. `action: {"type": "compare", "data": {...}}`:
   - `listings`: Danh sách chi tiết các căn hộ đã sắp xếp giá tăng dần.
   - `context`: `{ same_project: bool, same_province: bool }` (để UI ẩn các hàng trùng lặp).
   - `deltas`: Chênh lệch giá tổng, đơn giá/m², diện tích.
   - `highlights`: Huy hiệu nổi bật khách quan (`cheapest_price`, `largest_area`, `lowest_price_per_m2`, `most_bedrooms`).
2. `action: {"type": "cta", "items": [...]}`: Các nút CTA thao tác nhanh (Đặt lịch xem căn, Nhận tư vấn chi tiết).
