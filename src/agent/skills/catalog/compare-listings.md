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

## 1. Triết lý Phân định Trách nhiệm Giao diện
- **Văn bản (Text) = Insight:** Chỉ dùng để tóm tắt insight, xu hướng, điểm tương đồng và khác biệt cốt lõi giữa các căn.
- **Thẻ (Cards) = Entity Quick Data:** Hiển thị thông tin nhanh và đầy đủ của từng căn (giá, diện tích, phòng ngủ, WC, tầng, ảnh).
- **Bảng (Table) = Deep Matrix:** Lưới đối chiếu chi tiết theo từng dòng thông số khi người dùng bấm chọn tiêu chí.
- **Nguyên tắc phi trùng lặp:** Không để văn bản làm nhiệm vụ đọc lại số liệu của Cards hoặc Table. Tuyệt đối không biến phản hồi thành một bài báo dài.
- **Quy tắc xưng hô:** Gọi bằng tên căn hộ rút gọn hoặc tên dự án, tuyệt đối KHÔNG trích dẫn mã ID kỹ thuật (`oh:...`, `vhm:...`) vào câu thoại.
- **Không dùng ngoặc đơn `(...)`:** Viết câu văn mượt mà, diễn giải tự nhiên bằng các từ nối.

## 2. Chiến lược Hiển thị Kết quả

### 2.1 So sánh tổng quan (Mặc định khi yêu cầu so sánh)
Khi người dùng yêu cầu "so sánh", "so sánh các căn", "so sánh tổng quan":
- **Văn bản sinh ra (Overview):**
  - Dung lượng: **Khoảng 1–2 câu ngắn gọn (~30–50 từ), 1 đoạn duy nhất.**
  - Trọng tâm nội dung:
    1. **Thuộc dự án gì:** Nêu tên dự án của các căn hộ được chọn (ví dụ: Imperia Smart City, Vinhomes Smart City, Vinhomes Ocean Park...).
    2. **Nằm ở đâu:** Nêu vị trí địa lý/khu vực của dự án (ví dụ: quận Nam Từ Liêm, huyện Gia Lâm, TP. Hà Nội...).
    3. **Dự án đó có gì nổi bật:** Nêu ngắn gọn 1–2 điểm nhấn nổi bật của dự án (ví dụ: đại đô thị thông minh với công viên trung tâm 10.2ha, hồ cảnh quan, hệ tiện ích all-in-one hiện đại; thành phố biển hồ với hồ nước mặn 6.1ha, không gian sinh thái xanh...).
  - **Tuyệt đối KHÔNG liệt kê số liệu từng căn** (số PN, số WC, tầng, view, nội thất, giá) vì tất cả thông số này đã hiển thị đầy đủ và trực quan trên các Cards ngay bên dưới.
- **UI đi kèm:**
  1. Đoạn văn Khái quát bối cảnh Dự án
  2. Danh sách Cards của 2–4 BĐS
  3. Các nút CTA chọn xem sâu theo tiêu chí (Tài chính & Pháp lý, Không gian & Nội thất, Bản đồ).

### 2.2 So sánh Tài chính & Pháp lý
Khi người dùng bấm chọn hoặc yêu cầu so sánh tài chính, giá, pháp lý, hiện trạng:
- **Văn bản sinh ra:** Chỉ tạo **1–2 câu ngắn** nêu nhận định tương quan về tài chính, đơn giá, pháp lý và hiện trạng sử dụng. Tuyệt đối KHÔNG liệt kê lại toàn bộ số liệu từng căn trong văn bản.
  *Ví dụ:* "Về tài chính và pháp lý, mức giá và đơn giá giữa các căn khá tương đồng, trong khi tình trạng pháp lý và hiện trạng sử dụng có sự khác biệt giữa các căn."
- **UI đi kèm:** Bảng `financial_legal` + Nút CTA.

### 2.3 So sánh Không gian & Nội thất
Khi người dùng bấm chọn hoặc yêu cầu so sánh không gian, thiết kế, nội thất, view:
- **Văn bản sinh ra:** Chỉ tạo **1–2 câu ngắn** nêu nhận định về loại phòng, số WC, tầng, tầm nhìn và mức độ hoàn thiện nội thất. Tuyệt đối KHÔNG liệt kê lại toàn bộ số liệu từng căn trong văn bản.
  *Ví dụ:* "Về không gian và nội thất, các căn chủ yếu khác nhau ở số phòng vệ sinh, vị trí tầng, tầm nhìn view và mức độ hoàn thiện nội thất."
- **UI đi kèm:** Bảng `space_interior` + Nút CTA.

## 3. Giới hạn Văn bản (Output Constraints — Áp dụng riêng cho So sánh)
- **Tổng quan mặc định:** Tối đa 4 câu, tối đa 100 từ, không quá 1 đoạn. Cấm liệt kê tuần tự từng căn kiểu "Căn A có..., Căn B có..., Căn C có...". Cấm đọc lại giá và diện tích từng căn trừ khi minh hoạ chênh lệch nổi bật.
- **Khi có bảng:** Văn bản trước bảng tối đa 2 câu. Không diễn giải lại từng dòng của bảng.
- **Không tạo câu kết hoặc lời mời xem cards/bảng:** UI tự render trực tiếp bên dưới.

## 4. Các MCP Tools khả dụng
- `compare_listings(listing_ids=[...])`: Trả về dữ liệu chi tiết các căn từ `listings_clean`, các trường so sánh (`fields`), đánh giá bối cảnh (`context`), chênh lệch (`deltas`) và huy hiệu số liệu nổi bật (`highlights`).
