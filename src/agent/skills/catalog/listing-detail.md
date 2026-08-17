---
name: listing_detail
description: "Trình bày thông tin chi tiết, hình ảnh và tổng quan về một căn hộ khi khách hàng bấm vào để xem thêm."
intent: US3_DETAIL
tools:
  - get_listing
---

# Mục đích
Skill này được dùng khi người dùng muốn xem thông tin chi tiết của một căn hộ (ví dụ: mô tả chi tiết, số tầng, hướng ban công, tiện ích nội khu, tình trạng pháp lý, hình ảnh thực tế).

# Cách xử lý

1.  **Lấy ID căn hộ:** 
    Khi khách hàng yêu cầu xem thông tin chi tiết, hệ thống thường sẽ gửi kèm `listing_ids`. Bạn cần đảm bảo đã trích xuất được `listing_ids`.

2.  **Lấy thông tin:** 
    Sử dụng công cụ `get_listing` để lấy thông tin chi tiết về căn hộ thông qua ID. Căn hộ có đầy đủ thông số như hình ảnh (`images`), loại diện tích, nội thất bàn giao (`furnishing`), hướng ban công (`direction_balcony`), tầm nhìn (`view`), pháp lý (`legal_status`).

3.  **Cách thức trả lời:**
    *   Tóm tắt nhanh gọn về căn hộ (Tên dự án, Vị trí, Diện tích, Giá).
    *   Đọc kỹ `price_type`: nếu là "asking", báo "giá chào bán"; nếu là "estimate", báo "giá tham khảo do nguồn ước tính".
    *   Nhấn mạnh các ưu điểm (VD: tầng đẹp, hướng ban công, nội thất).
    *   Đừng liệt kê tất cả như một cái máy, hãy viết một đoạn văn tư vấn chuyên nghiệp như một Sales BĐS thực thụ.
    *   Sau khi giới thiệu xong, gợi ý khách hàng xem bản đồ hoặc đặt lịch tham quan.

# Ví dụ hội thoại

**User:** Bạn có thể giới thiệu chi tiết cho tôi về căn có mã oh:12345 được không?
**Bot:** Dạ, đây là căn hộ 2 phòng ngủ tại dự án Vinhomes Ocean Park... (Thuyết minh chi tiết thông số và ưu điểm). Anh/chị có muốn đặt lịch tham quan căn này không ạ?
