"""
Core video processing logic.
Handles:
  - Background video random selection & slow-down
  - Audio/SRT pairing
  - FFmpeg GPU-accelerated render pipeline
"""

import os
import re
import json
import random
import subprocess
import shlex
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac"}

LOCAL_BIN_DIR = Path(__file__).parent.parent / "bin"
FFMPEG_PATH = str(LOCAL_BIN_DIR / "ffmpeg.exe") if (LOCAL_BIN_DIR / "ffmpeg.exe").exists() else "ffmpeg"
FFPROBE_PATH = str(LOCAL_BIN_DIR / "ffprobe.exe") if (LOCAL_BIN_DIR / "ffprobe.exe").exists() else "ffprobe"


@dataclass
class FilePair:
    index: str
    audio_path: str
    srt_path: str
    matched: bool = True
    error: str = ""


@dataclass
class SubtitleStyle:
    font_name: str = "Arial"
    font_size: int = 40

    font_color: str = "#FFFFFF"

    stroke_color: str = "#000000"
    stroke_width: float = 2.0
    stroke_enabled: bool = True

    bg_color: str = "#000000"
    bg_opacity: float = 0.6
    bg_padding_x: int = 8
    bg_padding_y: int = 4
    bg_corner_radius: int = 4
    bg_enabled: bool = True

    shadow_color: str = "#000000"
    shadow_opacity: float = 0.8
    shadow_angle: float = 45.0
    shadow_distance: float = 3.0
    shadow_blur: float = 2.0
    shadow_enabled: bool = False

    alignment: int = 2
    margin_v: int = 50
    margin_l: int = 20
    margin_r: int = 20

    @staticmethod
    def from_preset(preset) -> "SubtitleStyle":
        """Create a RenderConfig-compatible SubtitleStyle from a SubtitleStylePreset."""
        return SubtitleStyle(
            font_name=preset.font_name,
            font_size=preset.font_size,
            font_color=preset.font_color,
            stroke_color=preset.stroke_color,
            stroke_width=preset.stroke_width,
            stroke_enabled=preset.stroke_enabled,
            bg_color=preset.bg_color,
            bg_opacity=preset.bg_opacity,
            bg_padding_x=preset.bg_padding_x,
            bg_padding_y=preset.bg_padding_y,
            bg_corner_radius=preset.bg_corner_radius,
            bg_enabled=preset.bg_enabled,
            shadow_color=preset.shadow_color,
            shadow_opacity=preset.shadow_opacity,
            shadow_angle=preset.shadow_angle,
            shadow_distance=preset.shadow_distance,
            shadow_blur=preset.shadow_blur,
            shadow_enabled=preset.shadow_enabled,
            alignment=preset.alignment,
            margin_v=preset.margin_v,
            margin_l=preset.margin_l,
            margin_r=preset.margin_r,
        )


@dataclass
class ImageLayerConfig:
    enabled: bool = False
    path: str = ""
    position: int = 0  # 0: BR, 1: BL, 2: TR, 3: TL, 4: TC
    size: int = 100
    opacity: float = 0.9
    margin_t: int = 20
    margin_b: int = 20
    margin_l: int = 20
    margin_r: int = 20
    crop_t: int = 0
    crop_b: int = 0
    crop_l: int = 0
    crop_r: int = 0
    radius: int = 0

@dataclass
class RenderConfig:
    bg_folder: str = ""
    bg_videos: list[str] | None = None
    audio_folder: str = ""
    srt_folder: str = ""
    output_folder: str = ""
    subtitle_style: SubtitleStyle = None
    slow_min: float = 35.0
    slow_max: float = 45.0
    codec: str = "hevc_nvenc"
    resolution: str = "1280x720"
    use_gpu: bool = True
    logo_path: Optional[str] = None
    logo_position: int = 0  # Legacy field
    logo_size: int = 100     # Legacy field
    logo_opacity: float = 0.8 # Legacy field
    layers: list[ImageLayerConfig] = field(default_factory=lambda: [ImageLayerConfig() for _ in range(5)])

    def __post_init__(self):
        if self.subtitle_style is None:
            self.subtitle_style = SubtitleStyle()
        if self.bg_videos is None:
            self.bg_videos = []


# ---------------------------------------------------------------------------
# FFprobe helpers
# ---------------------------------------------------------------------------

def probe_duration(file_path: str) -> float:
    cmd = [
        FFPROBE_PATH, "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        file_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe returned non-zero code {result.returncode}. Stderr: {result.stderr}")
        if not result.stdout.strip():
            raise RuntimeError("ffprobe output is empty")
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception as e:
        raise RuntimeError(f"ffprobe failed on {file_path}: {e}")

def probe_resolution(file_path: str) -> tuple[int, int]:
    cmd = [
        FFPROBE_PATH, "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v:0",
        file_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe returned non-zero code {result.returncode}. Stderr: {result.stderr}")
        if not result.stdout.strip():
            raise RuntimeError("ffprobe output is empty")
        data = json.loads(result.stdout)
        if "streams" in data and len(data["streams"]) > 0:
            w = int(data["streams"][0]["width"])
            h = int(data["streams"][0]["height"])
            return w, h
        raise ValueError("No video/image stream found")
    except Exception as e:
        return 1280, 720


def list_video_files(folder: str) -> list[str]:
    result = []
    for f in Path(folder).iterdir():
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            result.append(str(f))
    return result


def list_valid_video_files(paths: list[str]) -> list[str]:
    return [path for path in paths if Path(path).is_file() and Path(path).suffix.lower() in VIDEO_EXTENSIONS]


# ---------------------------------------------------------------------------
# File pairing
# ---------------------------------------------------------------------------


def build_pairs(audio_sources: list[str], srt_sources: list[str]) -> list[FilePair]:
    audio_files = [Path(path) for path in audio_sources if Path(path).is_file()]
    srt_files = [Path(path) for path in srt_sources if Path(path).is_file()]

    pairs: list[FilePair] = []
    max_len = max(len(audio_files), len(srt_files))
    for idx in range(max_len):
        audio_path = str(audio_files[idx]) if idx < len(audio_files) else ""
        srt_path = str(srt_files[idx]) if idx < len(srt_files) else ""
        matched = bool(audio_path and srt_path)
        error = ""
        if not audio_path:
            error = "Thiếu file audio"
        elif not srt_path:
            error = "Thiếu file SRT"

        display_name = Path(audio_path).stem if audio_path else Path(srt_path).stem if srt_path else str(idx + 1)
        pairs.append(FilePair(
            index=str(idx + 1),
            audio_path=audio_path,
            srt_path=srt_path,
            matched=matched,
            error=error or f"Ghép theo thứ tự thủ công #{idx + 1}",
        ))

    return pairs


# ---------------------------------------------------------------------------
# Background video selection
# ---------------------------------------------------------------------------

def select_bg_segment(
    bg_folder: str,
    audio_duration: float,
    slow_min: float,
    slow_max: float,
    bg_videos: list[str] | None = None,
) -> tuple[str, float, float, float]:
    videos = list_valid_video_files(bg_videos or [])
    if not videos and bg_folder:
        videos = list_video_files(bg_folder)
    if not videos:
        raise RuntimeError("Không tìm thấy video nền nào đã chọn")

    random.shuffle(videos)

    slow_pct = random.uniform(slow_min, slow_max)
    speed_factor = slow_pct / 100.0
    needed_original = audio_duration * speed_factor

    for video_path in videos:
        try:
            vid_duration = probe_duration(video_path)
        except Exception:
            continue

        if vid_duration < needed_original + 1:
            continue

        max_start = vid_duration - needed_original
        start = random.uniform(0, max_start)
        return video_path, start, needed_original, slow_pct

    raise RuntimeError(
        f"Không có video nền nào đủ dài cho audio {audio_duration:.0f}s "
        f"(cần {needed_original:.0f}s gốc ở tốc độ {slow_pct:.1f}%). "
        "Thêm video dài hơn vào thư mục nền."
    )


# ---------------------------------------------------------------------------
# Subtitle ASS style string for FFmpeg
# ---------------------------------------------------------------------------

def _build_subtitle_filter(srt_path: str, style: SubtitleStyle) -> str:
    if not srt_path or not os.path.exists(srt_path):
        return ""
    """
    Build FFmpeg subtitles filter with force_style.

    BorderStyle mapping:
      1  = Outline + shadow only (no box)
      3  = Opaque box (rectangle)
      4  = Opaque box with rounded corners

    We use 3 (rectangle) when background is enabled, 1 (outline only) otherwise.
    Shadow: SSA supports only basic shadow (Shadow=1/2/3). We approximate with
    shadow_distance and shadow_blur via BorderStyle=1 + drop-shadow via
    libass natively when Shadow > 0.
    """
    def _hex_to_ass(hex_color: str, alpha: float) -> str:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        a = int((1.0 - alpha) * 255)
        return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"

    safe_srt = srt_path.replace("\\", "/").replace(":", "\\:")

    font_color_ass = _hex_to_ass(style.font_color, 1.0)

    # Stroke
    stroke_color_ass = _hex_to_ass(style.stroke_color, 1.0)
    outline_val = int(style.stroke_width) if style.stroke_enabled else 0

    # Shadow — convert angle+distance to SSA shadow depth
    # SSA Shadow=1/2/3 is a single-step shadow. Map our distance to nearest.
    shadow_val = 0
    if style.shadow_enabled:
        d = style.shadow_distance
        shadow_val = 1 if d <= 2 else 2 if d <= 4 else 3

    # Background
    bg_color_ass = _hex_to_ass(style.bg_color, style.bg_opacity)
    # Use standard ASS BorderStyle=3 (opaque box) when background is enabled, otherwise 1 (outline + shadow)
    border_style = 3 if style.bg_enabled else 1

    # Padding — translate to MarginL/R which extend the background box
    margin_l = style.margin_l + style.bg_padding_x
    margin_r = style.margin_r + style.bg_padding_x
    margin_v = style.margin_v + style.bg_padding_y

    force_style = (
        f"FontName={style.font_name},"
        f"FontSize={style.font_size},"
        f"PrimaryColour={font_color_ass},"
        f"BackColour={bg_color_ass},"
        f"OutlineColour={stroke_color_ass},"
        f"Outline={outline_val},"
        f"Shadow={shadow_val},"
        f"Alignment={style.alignment},"
        f"BorderStyle={border_style},"
        f"MarginV={margin_v},"
        f"MarginL={margin_l},"
        f"MarginR={margin_r}"
    )

    return f"subtitles='{safe_srt}':force_style='{force_style}'"


# ---------------------------------------------------------------------------
# FFmpeg render command builder
# ---------------------------------------------------------------------------

def build_ffmpeg_cmd(
    bg_video: str,
    bg_start: float,
    bg_segment_duration: float,
    slow_pct: float,
    audio_path: str,
    srt_path: str,
    output_path: str,
    config: RenderConfig
) -> list[str]:
    speed_factor = slow_pct / 100.0
    pts_expr = f"PTS/{speed_factor:.4f}"
    w, h = config.resolution.split("x")

    sub_filter = _build_subtitle_filter(srt_path, config.subtitle_style)

    # Resolve active layers (supporting up to 5 layers)
    active_layers = []
    if hasattr(config, "layers") and config.layers:
        for layer in config.layers:
            if layer.enabled and layer.path:
                # Resolve source type path dynamically
                if layer.path == "Video nền":
                    layer_resolved_path = bg_video
                elif layer.path == "Theo danh sách chạy":
                    layer_resolved_path = audio_path
                else:
                    layer_resolved_path = layer.path
                    
                if layer_resolved_path and os.path.exists(layer_resolved_path):
                    layer._resolved_path = layer_resolved_path
                    active_layers.append(layer)
                    
    # Fallback to legacy logo config if no active layers set
    if not active_layers and config.logo_path and os.path.exists(config.logo_path):
        fallback_layer = ImageLayerConfig(
            enabled=True,
            path=config.logo_path,
            position=config.logo_position,
            size=config.logo_size,
            opacity=config.logo_opacity,
            margin_t=20,
            margin_b=20,
            margin_l=20,
            margin_r=20
        )
        fallback_layer._resolved_path = config.logo_path
        active_layers.append(fallback_layer)

    vf_parts = []
    if config.use_gpu:
        vcodec = config.codec
        vf_parts.extend([
            "hwdownload",
            "format=nv12",
            "format=yuv420p",
            f"setpts={pts_expr}",
            f"scale={w}:{h}:flags=lanczos:force_original_aspect_ratio=decrease",
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        ])
    else:
        vcodec = "libx265" if "hevc" in config.codec else "libx264"
        vf_parts.extend([
            f"setpts={pts_expr}",
            f"scale={w}:{h}:flags=lanczos:force_original_aspect_ratio=decrease",
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        ])

    if sub_filter:
        vf_parts.append(sub_filter)

    vf = ",".join(vf_parts)

    cmd = [
        FFMPEG_PATH, "-y",
    ]
    if config.use_gpu:
        cmd.extend([
            "-hwaccel", "cuda",
            "-hwaccel_output_format", "cuda",
        ])
        
    cmd.extend([
        "-ss", f"{bg_start:.3f}",
        "-t", f"{bg_segment_duration:.3f}",
        "-i", bg_video,
        "-i", audio_path,
    ])
    for layer in active_layers:
        cmd.extend(["-i", layer._resolved_path])

    quality_flags = ["-qp", "23"] if config.use_gpu else ["-crf", "23"]
    preset_flags  = ["-preset", "fast"]

    # Build filter complex for sequential overlays
    filter_parts = [f"[0:v]{vf}[v_base]"]
    current_base = "v_base"

    is_edit_sub = bool(config.srt_folder)

    for idx, layer in enumerate(active_layers):
        input_index = 2 + idx
        layer_output = f"v_layer_{idx}"
        
        # 1. Probe original resolution of the layer clip
        lw_orig, lh_orig = probe_resolution(layer._resolved_path)
        
        if is_edit_sub:
            # Edit Subtitles tab logo layer calculations (1280x720 canvas)
            scale_x = int(w) / 1280.0
            scale_y = int(h) / 720.0
            
            pixel_w = int(layer.size * scale_x)
            pixel_w = max(4, (pixel_w // 2) * 2)
            
            crop_filter = ""
            
            filter_parts.append(
                f"[{input_index}:v]{crop_filter}scale={pixel_w}:-2,format=rgba,"
                f"colorchannelmixer=aa={layer.opacity:.2f}[{layer_output}]"
            )
            
            ml = int(layer.margin_l * scale_x)
            mr = int(layer.margin_r * scale_x)
            mt = int(layer.margin_t * scale_y)
            mb = int(layer.margin_b * scale_y)
            
            # Position mapping for Edit Sub:
            # 0: BR, 1: BL, 2: TR, 3: TL, 4: Top-Center
            if layer.position == 0:  # Bottom-Right
                overlay_pos = f"x=W-w-{mr}:y=H-h-{mb}"
            elif layer.position == 1:  # Bottom-Left
                overlay_pos = f"x={ml}:y=H-h-{mb}"
            elif layer.position == 2:  # Top-Right
                overlay_pos = f"x=W-w-{mr}:y={mt}"
            elif layer.position == 3:  # Top-Left
                overlay_pos = f"x={ml}:y={mt}"
            else:  # 4: Top-Center
                overlay_pos = f"x=(W-w)/2:y={mt}"
        else:
            # Edit Video tab active layer calculations (400x225 workspace)
            # 2. Crop values (virtual margins relative to virtual uncropped layer size)
            crop_t = getattr(layer, "crop_t", 0)
            crop_b = getattr(layer, "crop_b", 0)
            crop_l = getattr(layer, "crop_l", 0)
            crop_r = getattr(layer, "crop_r", 0)

            # 3. Compute virtual uncropped layer size
            if layer.size <= 100:
                max_w_virt = 400.0 * (layer.size / 100.0)
                max_h_virt = 225.0 * (layer.size / 100.0)
                scale_factor_virt = min(max_w_virt / float(lw_orig), max_h_virt / float(lh_orig))
                layer_w_virt = lw_orig * scale_factor_virt
                layer_h_virt = lh_orig * scale_factor_virt
            else:
                layer_w_virt = float(layer.size)
                layer_h_virt = layer_w_virt * lh_orig / float(lw_orig)

            # 4. Map virtual crop to actual pixel crop on the original video size
            actual_crop_l = max(0, min(lw_orig - 10, int(lw_orig * (crop_l / float(layer_w_virt)))))
            actual_crop_r = max(0, min(lw_orig - actual_crop_l - 10, int(lw_orig * (crop_r / float(layer_w_virt)))))
            actual_crop_t = max(0, min(lh_orig - 10, int(lh_orig * (crop_t / float(layer_h_virt)))))
            actual_crop_b = max(0, min(lh_orig - actual_crop_t - 10, int(lh_orig * (crop_b / float(layer_h_virt)))))

            # 5. Crop filter block
            crop_filter = ""
            if actual_crop_t > 0 or actual_crop_b > 0 or actual_crop_l > 0 or actual_crop_r > 0:
                crop_filter = f"crop=iw-{actual_crop_l}-{actual_crop_r}:ih-{actual_crop_t}-{actual_crop_b}:{actual_crop_l}:{actual_crop_t},"

            # 6. Compute final scale width pixel_w relative to cropped virtual width
            cropped_w_virt = max(10.0, layer_w_virt - crop_l - crop_r)
            pixel_w = int(int(w) * (cropped_w_virt / 400.0))
            # Ensure even width for FFmpeg compatibility
            pixel_w = max(4, (pixel_w // 2) * 2)

            # 7. Build filter for scaling, crop, format conversion
            filter_parts.append(
                f"[{input_index}:v]{crop_filter}scale={pixel_w}:-2,format=rgba,"
                f"colorchannelmixer=aa={layer.opacity:.2f}[{layer_output}]"
            )
            
            # 8. Position calculations with scaled margins
            scale_x = int(w) / 400.0
            scale_y = int(h) / 225.0
            
            ml = int(layer.margin_l * scale_x)
            mr = int(layer.margin_r * scale_x)
            mt = int(layer.margin_t * scale_y)
            mb = int(layer.margin_b * scale_y)

            # Combo positions: 4: Center, 0: BR, 1: BL, 2: TR, 3: TL
            if layer.position == 4: # Center
                overlay_pos = f"x=(W-w)/2+({ml}-{mr})/2:y=(H-h)/2+({mt}-{mb})/2"
            elif layer.position == 0:  # Bottom-Right
                overlay_pos = f"x=W-w-{mr}:y=H-h-{mb}"
            elif layer.position == 1:  # Bottom-Left
                overlay_pos = f"x={ml}:y=H-h-{mb}"
            elif layer.position == 2:  # Top-Right
                overlay_pos = f"x=W-w-{mr}:y={mt}"
            else:  # 3: Top-Left
                overlay_pos = f"x={ml}:y={mt}"
            
        next_base = f"v_base_next_{idx}" if idx < len(active_layers) - 1 else "vout"
        filter_parts.append(f"[{current_base}][{layer_output}]overlay={overlay_pos}[{next_base}]")
        current_base = next_base

    if not active_layers:
        filter_expr = f"[0:v]{vf}[vout]"
    else:
        filter_expr = ";".join(filter_parts)

    cmd += [
        "-filter_complex",
        filter_expr,
        "-map", "[vout]",
        "-map", "1:a",
        "-c:v", vcodec,
        *preset_flags,
        *quality_flags,
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        output_path
    ]

    return cmd


# ---------------------------------------------------------------------------
# High-level render job
# ---------------------------------------------------------------------------

def render_pair(
    pair: FilePair,
    config: RenderConfig,
    progress_callback=None,
    log_callback=None,
    should_abort=None,
) -> str:
    if not pair.matched:
        raise ValueError(f"FilePair {pair.index} chưa được ghép đầy đủ: {pair.error}")

    def _progress(pct, msg):
        if progress_callback:
            progress_callback(pct, msg)

    def _log(line):
        if log_callback:
            log_callback(line)

    _progress(0, f"[{pair.index}] Đọc thông tin audio...")
    audio_duration = probe_duration(pair.audio_path)
    _log(f"Audio duration: {audio_duration:.2f}s")

    if not config.bg_folder and not config.bg_videos:
        bg_video = pair.audio_path
        bg_start = 0.0
        bg_seg_dur = audio_duration
        slow_pct = 100.0
        _log("Không chọn video nền riêng; sử dụng trực tiếp video nguồn làm nền.")
    else:
        _progress(5, f"[{pair.index}] Chọn video nền ngẫu nhiên...")
        bg_video, bg_start, bg_seg_dur, slow_pct = select_bg_segment(
            config.bg_folder,
            audio_duration,
            config.slow_min,
            config.slow_max,
            config.bg_videos,
        )
    _log(f"Background: {os.path.basename(bg_video)}")
    _log(f"Segment start: {bg_start:.1f}s, duration: {bg_seg_dur:.1f}s, slow: {slow_pct:.1f}%")

    audio_stem = Path(pair.audio_path).stem
    output_filename = f"{audio_stem}.mp4"
    output_path = os.path.join(config.output_folder, output_filename)

    temp_srt_path = ""
    if pair.srt_path and os.path.exists(pair.srt_path):
        _progress(10, f"[{pair.index}] Chuẩn bị tệp phụ đề tạm thời...")
        import shutil

        project_root = Path(__file__).resolve().parent.parent
        temp_dir = project_root / ".temp_srt"
        temp_dir.mkdir(exist_ok=True)
        temp_srt_path = str(temp_dir / f"temp_{pair.index}.srt")
        try:
            shutil.copy2(pair.srt_path, temp_srt_path)
        except Exception as e:
            _log(f"Warning: Failed to copy srt file: {e}")
            temp_srt_path = ""
    else:
        _progress(10, f"[{pair.index}] Bỏ qua phụ đề (không có srt)...")

    try:
        _progress(12, f"[{pair.index}] Bắt đầu render với FFmpeg...")

        cmd = build_ffmpeg_cmd(
            bg_video=bg_video,
            bg_start=bg_start,
            bg_segment_duration=bg_seg_dur,
            slow_pct=slow_pct,
            audio_path=pair.audio_path,
            srt_path=temp_srt_path,
            output_path=output_path,
            config=config
        )

        _log("FFmpeg command: " + " ".join(shlex.quote(c) for c in cmd))

        _run_ffmpeg(cmd, audio_duration, _progress, _log, pair.index, should_abort)
    finally:
        try:
            if os.path.exists(temp_srt_path):
                os.unlink(temp_srt_path)
            # Clear directory if empty
            if temp_dir.exists() and not any(temp_dir.iterdir()):
                temp_dir.rmdir()
        except Exception:
            pass

    _progress(100, f"[{pair.index}] Hoàn thành! → {output_filename}")
    return output_path


def _run_ffmpeg(cmd: list[str], total_duration: float,
                progress_cb, log_cb, label: str, should_abort=None):
    time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")

    import sys
    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags
    )

    for line in process.stdout:
        if should_abort and should_abort():
            process.terminate()
            process.wait(timeout=5)
            raise InterruptedError("Render đã bị dừng")
        line = line.rstrip()
        if line:
            log_cb(line)
        m = time_pattern.search(line)
        if m and total_duration > 0:
            h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            elapsed = h * 3600 + mn * 60 + s
            pct = min(10 + (elapsed / total_duration) * 88, 98)
            progress_cb(pct, f"[{label}] Đang render... {elapsed:.0f}/{total_duration:.0f}s")

    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg thất bại với mã lỗi {process.returncode}")