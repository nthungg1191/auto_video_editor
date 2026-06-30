# Auto Video Editor (Bộ Biên Tập Video Tự Động)

**Auto Video Editor** là một ứng dụng Desktop chuyên nghiệp được phát triển bằng **Python + PyQt6** và bộ công cụ **FFmpeg/FFprobe**, hỗ trợ tối ưu tăng tốc phần cứng GPU (NVIDIA NVENC). 

Ứng dụng giúp bạn tự động hóa quy trình sản xuất video bằng cách ghép phụ đề (SRT), chèn logo thương hiệu, chèn nhiều lớp video đè (Video Layers) đè lên một video nền (Background Video) với các công cụ căn chỉnh vị trí trực quan theo thời gian thực.

---

## 🚀 Các Tính Năng Nổi Bật

### 1. Quản lý Bố cục Video Đa lớp (Video Layers)
*   **Hỗ trợ tới 5 lớp video/ảnh đè:** Cho phép xếp chồng nhiều layer lên video nền (ví dụ: video Reaction, chèn khung hình phụ, chèn logo).
*   **Trình xem trước tương tác (Interactive Preview):**
    *   **Kéo/thả:** Di chuyển trực quan các lớp video đến bất kỳ vị trí nào trên khung hình.
    *   **Co giãn 8 hướng (8-directional Resizing):** Hỗ trợ kéo giãn kích thước linh hoạt bằng 8 điểm neo (NW, NE, SW, SE, N, S, W, E) kèm con trỏ chuột chỉ hướng thông minh.
    *   **Cắt cúp nâng cao (Crop Mode):** Cho phép cắt khung hình trực tiếp. Khung chọn co giãn sẽ tự động ôm sát vùng ảnh đã cắt giúp việc thiết kế chính xác tuyệt đối.
    *   **Độ mờ (Opacity):** Hỗ trợ làm mờ dần các lớp video từ 10% đến 100% thay vì bo góc thô cứng.
*   **Snapping & Quy đổi vị trí đè:** Tự động snap lề (Margin) về `20px` khi người dùng thay đổi neo vị trí (Top-Left, Bottom-Right, v.v.), triệt tiêu hoàn toàn lỗi nhảy lệch khung hình.

### 2. Biên tập Phụ đề & Chèn Logo (Edit Subtitles & Logo)
*   **Bộ lọc phụ đề đa dạng:** Tùy biến kiểu chữ (Font), cỡ chữ, màu sắc, đường viền (Stroke), nền chữ (Background), và đổ bóng (Shadow) trực tiếp từ giao diện.
*   **Lưu preset:** Tạo và tải các preset phụ đề nhanh chóng (như mặc định, chữ to, chữ sáng, v.v.).
*   **Độc lập hệ tọa độ:** Hệ thống tự động phân tách tọa độ thiết kế của tab Edit Sub (sử dụng hệ HD `1280x720` thực tế bằng pixel) và tab Edit Video (sử dụng hệ ảo `400x225`), giúp video xuất ra có kích thước logo hoàn hảo và sắc nét.

### 3. Render Hàng Loạt Chọn Lọc (Selective Batch Rendering)
*   **Tích chọn linh hoạt (Checkbox):** Tích hợp Checkbox ở cột đầu tiên của danh sách tệp. Người dùng có thể chủ động chọn những video mong muốn render thay vì bắt buộc chạy toàn bộ.
*   **Chọn nhanh bằng Shift + Click:** Hỗ trợ giữ phím `Shift` (chọn dải liên tục) hoặc `Ctrl` (chọn nhiều hàng riêng lẻ) và click chọn checkbox để bật/tắt hàng loạt dòng bôi đen chỉ trong 1 cú click.
*   **Các nút hỗ trợ nhanh:** Nút "Chọn tất cả" và "Bỏ chọn tất cả" giúp quản lý hàng đợi render lớn dễ dàng.

### 4. Tối ưu hóa Hiệu năng & Trải nghiệm Người dùng
*   **Trích xuất ảnh nền bất đồng bộ (Async Frame Loader):** Khử hoàn toàn hiện tượng đứng hình (UI Freeze) khi chuyển tệp hoặc quét thư mục nhờ đưa tác vụ chạy `ffprobe`/`ffmpeg` xuống luồng nền của `QThreadPool` và chỉ cập nhật lên giao diện khi ảnh đã sẵn sàng.
*   **Tránh đơ máy khi render (CPU Priority Control):** Tiến trình render FFmpeg được chạy dưới quyền ưu tiên thấp (`BELOW_NORMAL_PRIORITY_CLASS` trên Windows). Máy tính của bạn sẽ luôn mượt mà để lướt web, nghe nhạc hay làm việc khác trong suốt quá trình render.

---

## 📂 Cấu Trúc Thư Mục Dự Án

```
auto_video_editor/
├── bin/                    # Chứa ffmpeg.exe & ffprobe.exe (tùy chọn)
├── core/                   # Logic xử lý nghiệp vụ chính
│   ├── video_processor.py  # Pipeline render FFmpeg, tính toán scale/crop/overlay
│   ├── srt_service.py      # Đọc, ghi và sửa đổi file phụ đề SRT
│   ├── subtitle_model.py   # Định nghĩa cấu trúc dữ liệu phụ đề
│   ├── style_preset_service.py # Quản lý các preset style phụ đề
│   └── worker.py           # Qt Worker Thread quản lý tiến trình render
├── ui/                     # Giao diện người dùng PyQt6
│   ├── main_window.py      # Cửa sổ chính (Bố cục 3 panel)
│   ├── subtitle_preview_widget.py # Widget hiển thị preview phụ đề & logo
│   ├── subtitle_editor_widget.py  # Trình biên tập nội dung SRT
│   ├── video_layer_config.py      # Cấu hình thuộc tính của từng video layer
│   └── video_layout_preview.py    # Canvas kéo thả tương tác 8 hướng
├── presets/
│   └── subtitle_presets.json # Lưu trữ cấu hình preset phụ đề
├── utils/
│   ├── gpu_detect.py       # Tự động nhận diện GPU & bộ mã hóa NVENC
│   └── settings.py         # Lưu và phục hồi cài đặt phần mềm (settings.json)
├── main.py                 # File chạy chính của chương trình
└── README.md               # Hướng dẫn sử dụng
```

---

## ⚙️ Hướng Dẫn Cài Đặt & Khởi Chạy

### Yêu cầu hệ thống
*   Python 3.10+
*   FFmpeg và FFprobe (Nên đặt trong thư mục `bin/` ở gốc dự án hoặc thêm vào PATH của hệ thống).

### Các bước cài đặt

1.  Clone thư mục dự án về máy tính của bạn.
2.  Cài đặt thư viện giao diện PyQt6:
    ```bash
    pip install PyQt6
    ```
3.  Tải bộ công cụ FFmpeg (nếu chưa có trong hệ thống) và giải nén `ffmpeg.exe`, `ffprobe.exe` đặt vào thư mục `bin/` của dự án.
4.  Khởi chạy chương trình:
    ```bash
    python main.py
    ```

---

## 📖 Hướng Dẫn Sử Dụng Giao Diện

Giao diện chính được chia thành **3 cột lớn (3-panel)** nằm ngang rất chuyên nghiệp:

1.  **Panel Trái (Dữ liệu & Hàng đợi):** 
    *   Chứa các công cụ chọn thư mục video nguồn, video nền, nhạc và phụ đề SRT.
    *   Bảng hiển thị danh sách video đã được ghép cặp hoặc sẵn sàng scale.
    *   Hỗ trợ checkbox đầu dòng và thao tác giữ `Shift + Click` để chọn nhanh danh sách render.
2.  **Panel Giữa (Xem trước & Biên tập):**
    *   **Tab Subtitle Style & Image Layers:** Tùy biến phông chữ, cỡ chữ, đổ bóng, màu sắc hoặc chèn ảnh logo thương hiệu tương thích với hệ toạ độ 1280x720.
    *   **Tab Preview tương tác:** Cho phép nhấp chọn layer, kéo thả di chuyển vị trí, crop trực tiếp, hoặc co giãn kích thước bằng 8 tay cầm điểm neo trực quan.
3.  **Panel Phải (Cài Đặt Render):**
    *   Lựa chọn bộ giải mã xuất video (H.264 / H.265 bằng CPU hoặc tăng tốc bằng GPU Nvidia NVENC).
    *   Thiết lập khoảng giới hạn tốc độ chạy video nền (Slow motion).
    *   Bảng Log hiển thị luồng thông tin trực tiếp từ FFmpeg để giám sát và gỡ lỗi.
    *   Bộ điều khiển chính: Nút **Bắt đầu Render**, **Tạm dừng/Tiếp tục** và **Dừng hẳn**.
