# Auto Video Editor

Mot cua so dong ung dung desktop giup tao video tu file am thanh (mp3, m4a, wav, aac) va phu de SRT, bang cach:

- **Chon ngau nhien** mot video nen tu thu muc
- **Ghep am thanh + SRT** thanh cap video + phu de
- **Render** bang FFmpeg (ho tro GPU NVENC hoac CPU)
- **Chinh sua style phu de** truc tiep trong giao dien: font, mau sac, duong vien, nen, bong

Ung dung duoc viet bang **Python 3 + PyQt6**, goi FFmpeg tu thu muc `bin/` hoac tu PATH he thong.

---

## Cau truc du an

```
auto_video_editor/
├── bin/                    # FFmpeg & FFprobe (neu co)
│   ├── ffmpeg.exe
│   └── ffprobe.exe
├── core/                   # Logic xu ly chinh
│   ├── video_processor.py  # Render pipeline, FFmpeg wrapper
│   ├── srt_service.py       # Doc/ghi/sua file SRT
│   ├── subtitle_model.py    # Kieu du lieu phu de
│   ├── style_preset_service.py  # Luu/tai preset style
│   └── worker.py            # Qt worker thread cho render
├── ui/                     # Giao dien PyQt6
│   ├── main_window.py      # Cua so chinh (3-panel)
│   ├── subtitle_preview_widget.py  # Preview phu de
│   └── subtitle_editor_widget.py    # Widget chinh sua
├── presets/
│   └── subtitle_presets.json  # Cac preset style phu de
├── utils/
│   ├── gpu_detect.py       # Phat hien GPU & NVENC
│   └── settings.py         # Cau hinh luu tru
├── main.py                 # Entry point
└── README.md
```

---

## Tinh nang chinh

### Chen phu de vao video

- Chon thu muc chua file am thanh va thu muc chua file SRT
- Tu dong ghep cap audio + SRT theo ten file
- Chon video nen ngau nhien tu thu muc (hoac video co dinh)
- Dieu chinh toc do video (lam cham/chay nhanh)

### Chinh sua style phu de

| Thanh phan    | Tuy chon                                      |
|---------------|-----------------------------------------------|
| Font          | Arial, Roboto, Montserrat, Open Sans, ...     |
| Kich thuoc    | 12 - 100 px                                   |
| Mau chu       | Mau sac tuy chon (HEX)                        |
| Duong vien    | Mau + do rong                                 |
| Nen           | Mau nen + do trong + bo goc + padding         |
| Bong           | Mau + do trong + goc + khoang cach + blur   |
| Vi tri        | Giua man hinh / duoi giua / tren giua         |

Co san **5 preset** style: Mac dinh, Sang, To, newpreset, tbn1. Co the luu/tai preset tuy y.

### Render

- **Codec**: H.265 HEVC (GPU/CPU), H.264 AVC (GPU/CPU)
- **GPU**: Tu dong phat hien NVIDIA GPU & NVENC
- **Dieu khien**: Tam dung, tiep tuc, dung render
- **Log**: Xem FFmpeg log truc tiep trong giao dien
- **Xep hang**: Render nhieu cap video/audio theo thu tu

---

## Cai dat

### Yeu cau

- Python 3.8+
- PyQt6
- FFmpeg & FFprobe (trong `bin/` hoac PATH)

### Cau lenh cai dat

```bash
pip install PyQt6
```

### Khoi dong

```bash
python main.py
```

### FFmpeg

Neu FFmpeg chua co trong PATH, copy `ffmpeg.exe` va `ffprobe.exe` vao thu muc `bin/`. Ung dung se uu tien su dung cac file nay.

---

## Giao dien

Giao dien gom **3 panel ngang**:

| Panel trai                     | Panel giua                         | Panel phai                        |
|---------------------------------|-------------------------------------|-----------------------------------|
| Chon thu muc audio / SRT / video nen | Chinh sua style phu de + Preview | Cau hinh render + Log + Nut render |

---

## Giao dien phu de (Preview)

Widget preview hien thi phu de voi day du cac thuoc tinh: fill, stroke, background, shadow. Thu muc `presets/subtitle_presets.json` luu cac preset style, co the chinh sua truc tiep bang giao dien.

---

## Tu khoa

PyQt6, FFmpeg, NVENC, subtitle, SRT, video editor, GPU encoding, HEVC, H.264
