---
name: compare-listings
intent: US6_COMPARE
description: So sánh chi tiết 2-4 BĐS trong cùng dự án hoặc khác khu vực/tỉnh thành
tools:
  - compare_listings
required_slots:
  - listing_ids
clarify_prompt: >
  Dạ anh/chị muốn so sánh những căn nào ạ? Vui lòng chọn từ 2 đến 4 căn giúp em nhé.
---

# US6 — So sánh Bất Động Sản (Compare Listings)

Kỹ năng này phục vụ nhu cầu so sánh trực quan từ 2 đến 4 bất động sản cụ thể (dựa trên danh sách `listing_ids`) từ view `listings_clean`.

## 1. Mục tiêu & Nguyên tắc Nghiệp vụ
- **Số lượng so sánh:** Bắt buộc tối thiểu 2 căn và tối đa 4 căn.
- **Tính khách quan:** Tuyệt đối KHÔNG đưa ra kết luận chủ quan ("căn nào đáng mua hơn", "nên mua căn nào"). Chỉ trình bày số liệu và chênh lệch khách quan.
- **Phân biệt loại giá (`price_type`):**
  - "asking": Giá chào bán thật từ người bán / chủ đầu tư.
  - "estimate": Giá tham khảo do nguồn phân tích ước tính (không phải giá chào bán thực tế).

## 2. Các MCP Tools khả dụng
- `compare_listings(listing_ids=[...])`: Trả về dữ liệu chi tiết các căn từ `listings_clean`, các trường so sánh (`fields`), đánh giá bối cảnh (`context`), chênh lệch (`deltas`) và huy hiệu số liệu nổi bật (`highlights`).

## 3. Cấu trúc Action sinh ra cho Mobile UI
1. `action: {"type": "compare", "data": {...}}`:
   - `listings`: Danh sách chi tiết các căn hộ đã sắp xếp giá tăng dần.
   - `context`: `{ same_project: bool, same_province: bool }` (để UI ẩn các hàng trùng lặp).
   - `deltas`: Chênh lệch giá tổng, đơn giá/m², diện tích.
   - `highlights`: Huy hiệu nổi bật khách quan (`cheapest_price`, `largest_area`, `lowest_price_per_m2`, `most_bedrooms`).
   - `summary`: Đoạn nhận xét tổng quan ngắn gọn (2-3 câu) do AI sinh tự nhiên dưới bảng.
2. `action: {"type": "cta", "items": [...]}`: Các nút CTA thao tác nhanh (Đặt lịch xem căn, Nhận tư vấn chi tiết).

## 4. Nguyên tắc Soạn Tổng quan So sánh (Comparison Summary Prompt)
- **Độ dài:** 2 đến 3 câu văn tự nhiên, súc tích.
- **Nội dung:** Làm nổi bật sự khác biệt về Tài chính / Pháp lý hoặc Không gian / Nội thất giữa các căn.
- **Tính khách quan:** Không dùng từ tâng bốc thái quá, không khuyên mua thiên vị.
- **Định dạng:** Không dùng in đậm markdown (`**`). Không lặp lại tên dự án nếu các căn cùng dự án.
