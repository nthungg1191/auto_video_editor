"""
Interactive Video Layout Preview widget using QPainter.
Supports dragging, resizing, selecting, and cropping 5 layers.
"""
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QImage

class VideoLayoutPreview(QWidget):
    # Signals to communicate updates back to Main Window
    layerSelected = pyqtSignal(int) # index (1-based)
    layerMoved = pyqtSignal(int, int, int, int, int) # index, t, b, l, r
    layerResized = pyqtSignal(int, int) # index, scale_pct
    layerCropped = pyqtSignal(int, int, int, int, int) # index, t, b, l, r

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(280)
        self.setMouseTracking(True)

        # Configs for 5 layers (will be populated from main window)
        self._configs = {} # index -> ImageLayerConfig
        self._selected_index = 1 # Layer 1 selected by default
        self._is_crop_mode = False
        
        # Actual preview frames (background and layers)
        self._bg_image = None
        self._layer_images = {}

        # Drag state variables
        self._active_drag = None # None, 'move', 'resize', 'crop-resize'
        self._resize_handle = None # 'se', 'sw'
        self._crop_handle = None # 'n', 's', 'w', 'e'
        self._start_mouse = QPoint()
        
        # Bounding box caches (rendered positions relative to widget)
        # Coordinates in workspace space
        self._ws_w = 400
        self._ws_h = 225
        self._ws_x = 0
        self._ws_y = 0
        
        self._layer_rects = {} # index -> QRect (local coordinates of layer rect)
        self._uncropped_layer_rects = {} # index -> QRect (local coordinates of uncropped layer rect)
        self._crop_rect = QRect() # local coordinates of crop box

    def set_configs(self, configs: dict):
        """Pass the dictionary of layer configs {1..5: config}."""
        self._configs = configs
        self.update()

    def set_bg_image(self, img: QImage | None):
        self._bg_image = img
        self.update()

    def set_layer_image(self, index: int, img: QImage | None):
        if img is None or img.isNull():
            self._layer_images.pop(index, None)
        else:
            self._layer_images[index] = img
        self.update()

    def select_layer(self, index: int | None):
        if index is None or (1 <= index <= 5):
            self._selected_index = index
            self.layerSelected.emit(index if index is not None else 0)
            self.update()

    def set_crop_mode(self, enabled: bool):
        self._is_crop_mode = enabled
        self._active_drag = None
        self.update()

    def _get_workspace_geometry(self) -> tuple[int, int, int, int]:
        """Calculates centered 16:9 workspace bounds inside the widget."""
        cw = self.width()
        ch = self.height()
        scale = min(cw / float(self._ws_w), ch / float(self._ws_h))
        # Keep aspect ratio
        vw = int(self._ws_w * scale * 0.9) # leave margins
        vh = int(self._ws_h * scale * 0.9)
        vx = (cw - vw) // 2
        vy = (ch - vh) // 2
        return vx, vy, vw, vh

    def _get_layer_rect(self, index: int, vx: int, vy: int, vw: int, vh: int) -> QRect:
        """Computes the rendering QRect for a layer relative to the widget."""
        cfg = self._configs.get(index)
        if not cfg or not cfg.enabled:
            return QRect()

        # Compute width & height based on actual aspect ratio of the imported layer image
        layer_img = self._layer_images.get(index)
        if layer_img and not layer_img.isNull():
            lw = layer_img.width()
            lh = layer_img.height()
        else:
            # Fallbacks if no image loaded yet
            if index == 2:
                lw, lh = 1, 1
            else:
                lw, lh = 16, 9

        if cfg.size <= 100:
            max_w = vw * (cfg.size / 100.0)
            max_h = vh * (cfg.size / 100.0)
            scale_factor = min(max_w / float(lw), max_h / float(lh))
            layer_w = int(lw * scale_factor)
            layer_h = int(lh * scale_factor)
        else:
            layer_w = int(vw * (cfg.size / 400.0))
            layer_h = int(layer_w * lh / float(lw))

        # Position calculations using Margins
        # In our configuration layout: margins are top, bottom, left, right in workspace pixels.
        # We scale them to current preview rendering resolution.
        scale_x = vw / float(self._ws_w)
        scale_y = vh / float(self._ws_h)

        ml = int(cfg.margin_l * scale_x)
        mr = int(cfg.margin_r * scale_x)
        mt = int(cfg.margin_t * scale_y)
        mb = int(cfg.margin_b * scale_y)

        # NEO (Alignment) mapping:
        # Combo positions: 4: Center, 0: BR, 1: BL, 2: TR, 3: TL
        if cfg.position == 4: # Center
            lx = vx + (vw - layer_w) // 2 + (ml - mr) // 2
            ly = vy + (vh - layer_h) // 2 + (mt - mb) // 2
        elif cfg.position == 0: # BR
            lx = vx + vw - layer_w - mr
            ly = vy + vh - layer_h - mb
        elif cfg.position == 1: # BL
            lx = vx + ml
            ly = vy + vh - layer_h - mb
        elif cfg.position == 2: # TR
            lx = vx + vw - layer_w - mr
            ly = vy + mt
        else: # 3: TL
            lx = vx + ml
            ly = vy + mt

        return QRect(int(lx), int(ly), int(layer_w), int(layer_h))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cw = self.width()
        ch = self.height()

        # Draw dark canvas background
        p.fillRect(0, 0, cw, ch, QColor("#0A0B10"))

        # Center workspace
        vx, vy, vw, vh = self._get_workspace_geometry()
        self._ws_x, self._ws_y, self._ws_w_rendered, self._ws_h_rendered = vx, vy, vw, vh
        p.fillRect(vx, vy, vw, vh, QColor("#1e293b"))
        if self._bg_image and not self._bg_image.isNull():
            p.drawImage(QRect(vx, vy, vw, vh), self._bg_image)
        
        # Workspace Border
        p.setPen(QPen(QColor("#334155"), 1))
        p.drawRect(vx, vy, vw, vh)

        # Label background (only show if no bg image to reduce clutter)
        if not self._bg_image:
            p.setPen(QPen(QColor("#475569")))
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            p.drawText(QRect(vx, vy + 10, vw, 20), Qt.AlignmentFlag.AlignCenter, "VIDEO NỀN (BACKGROUND)")

        # Render all enabled layers in order of index (1 to 5)
        self._layer_rects.clear()
        self._uncropped_layer_rects.clear()
        
        # Determine colors for each layer
        colors = {
            1: (QColor(37, 99, 235), QColor(96, 165, 250), "Video Layer 1\n(Kéo/Co giãn)"), # Blue
            2: (QColor(16, 185, 129), QColor(52, 211, 153), "logo.png\n(Layer 2)"), # Green
            3: (QColor(217, 70, 239), QColor(240, 171, 252), "Layer 3\n(Overlay)"), # Fuchsia
            4: (QColor(245, 158, 11), QColor(251, 191, 36), "Layer 4\n(Overlay)"), # Amber
            5: (QColor(99, 102, 241), QColor(129, 140, 248), "Layer 5\n(Overlay)")  # Indigo
        }

        for i in range(1, 6):
            cfg = self._configs.get(i)
            if not cfg or not cfg.enabled:
                continue

            rect = self._get_layer_rect(i, vx, vy, vw, vh)
            if rect.isEmpty():
                continue

            # Draw background layer with alpha transparency
            bg_color, border_color, name = colors[i]
            
            # Apply crop visual preview using clip path representation
            crop_t = getattr(cfg, "crop_t", 0)
            crop_b = getattr(cfg, "crop_b", 0)
            crop_l = getattr(cfg, "crop_l", 0)
            crop_r = getattr(cfg, "crop_r", 0)
            radius = getattr(cfg, "radius", 0)

            # Scale crop values to rendered size
            scale_x = vw / 400.0
            scale_y = vh / 225.0
            rl = int(crop_l * scale_x)
            rr = int(crop_r * scale_x)
            rt = int(crop_t * scale_y)
            rb = int(crop_b * scale_y)

            # Calculate cropped rectangle
            cropped_rect = QRect(
                rect.left() + rl,
                rect.top() + rt,
                rect.width() - rl - rr,
                rect.height() - rt - rb
            )

            self._uncropped_layer_rects[i] = rect
            self._layer_rects[i] = cropped_rect

            p.save()
            # Draw uncropped boundaries (faint dotted line)
            p.setPen(QPen(QColor(border_color.red(), border_color.green(), border_color.blue(), 60), 1, Qt.PenStyle.DotLine))
            p.setBrush(QBrush(QColor(bg_color.red(), bg_color.green(), bg_color.blue(), 15)))
            p.drawRoundedRect(rect, radius, radius)

            # Draw real layer frame if available with correct opacity
            layer_img = self._layer_images.get(i)
            layer_opacity = getattr(cfg, "opacity", 1.0)
            if layer_img and not layer_img.isNull():
                p.save()
                p.setOpacity(layer_opacity)
                p.setClipRect(cropped_rect)
                p.drawImage(rect, layer_img)
                p.restore()
                # Semi-transparent overlay to indicate selected layer status
                p.setBrush(QBrush(QColor(bg_color.red(), bg_color.green(), bg_color.blue(), 25 if i == self._selected_index else 0)))
            else:
                c = QColor(bg_color.red(), bg_color.green(), bg_color.blue(), int(60 * layer_opacity))
                p.setBrush(QBrush(c))

            # Draw cropped boundaries (solid fill + thick border)
            p.setPen(QPen(border_color, 2 if i == self._selected_index else 1))
            # Selected layer gets a dashed border to stand out
            if i == self._selected_index:
                p.setPen(QPen(border_color, 2, Qt.PenStyle.DashLine))
            p.drawRoundedRect(cropped_rect, radius, radius)

            # Text indicator
            if not layer_img or i == self._selected_index:
                p.setPen(QPen(QColor("#000000")))
                p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                p.drawText(cropped_rect.translated(1, 1), Qt.AlignmentFlag.AlignCenter, name)
                p.setPen(QPen(QColor("#FFFFFF")))
                p.drawText(cropped_rect, Qt.AlignmentFlag.AlignCenter, name)
            p.restore()

        # Draw handles for the selected layer (8 handles in Layout Mode)
        active_rect = self._layer_rects.get(self._selected_index)
        if active_rect and not active_rect.isEmpty() and not self._is_crop_mode:
            p.save()
            border_color = colors[self._selected_index][1]
            p.setBrush(QBrush(border_color))
            p.setPen(QPen(QColor("#FFFFFF"), 1))
            
            # 1. Top-Left (NW)
            p.drawRect(active_rect.left() - 3, active_rect.top() - 3, 6, 6)
            # 2. Top-Right (NE)
            p.drawRect(active_rect.right() - 3, active_rect.top() - 3, 6, 6)
            # 3. Bottom-Left (SW)
            p.drawRect(active_rect.left() - 3, active_rect.bottom() - 3, 6, 6)
            # 4. Bottom-Right (SE)
            p.drawRect(active_rect.right() - 3, active_rect.bottom() - 3, 6, 6)
            # 5. Top-Center (N)
            p.drawRect(active_rect.left() + active_rect.width() // 2 - 3, active_rect.top() - 3, 6, 6)
            # 6. Bottom-Center (S)
            p.drawRect(active_rect.left() + active_rect.width() // 2 - 3, active_rect.bottom() - 3, 6, 6)
            # 7. Left-Center (W)
            p.drawRect(active_rect.left() - 3, active_rect.top() + active_rect.height() // 2 - 3, 6, 6)
            # 8. Right-Center (E)
            p.drawRect(active_rect.right() - 3, active_rect.top() + active_rect.height() // 2 - 3, 6, 6)
            p.restore()

        # Draw Crop Box (only if Crop Mode is active)
        uncropped_rect = self._uncropped_layer_rects.get(self._selected_index)
        if self._is_crop_mode and uncropped_rect:
            p.save()
            # Setup crop box geometry based on current crop values
            cfg = self._configs.get(self._selected_index)
            scale_x = vw / 400.0
            scale_y = vh / 225.0
            rl = int(cfg.crop_l * scale_x)
            rr = int(cfg.crop_r * scale_x)
            rt = int(cfg.crop_t * scale_y)
            rb = int(cfg.crop_b * scale_y)

            self._crop_rect = QRect(
                uncropped_rect.left() + rl,
                uncropped_rect.top() + rt,
                uncropped_rect.width() - rl - rr,
                uncropped_rect.height() - rt - rb
            )

            # Draw semi-transparent dimming outside crop box but inside active layer
            p.setClipRect(uncropped_rect)
            p.fillRect(uncropped_rect, QColor(0, 0, 0, 100))
            p.setClipping(False)

            # Draw crop boundary
            p.setPen(QPen(QColor("#f59e0b"), 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self._crop_rect)

            # Label on top left of crop
            p.setPen(QPen(QColor("#f59e0b")))
            p.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            p.drawText(self._crop_rect.left() + 4, self._crop_rect.top() + 10, "Crop Box")

            # Handles (N, S, W, E)
            p.setBrush(QBrush(QColor("#f59e0b")))
            p.setPen(QPen(QColor("#FFFFFF"), 1))
            
            # Top (N)
            p.drawRect(self._crop_rect.left() + self._crop_rect.width() // 2 - 3, self._crop_rect.top() - 3, 6, 6)
            # Bottom (S)
            p.drawRect(self._crop_rect.left() + self._crop_rect.width() // 2 - 3, self._crop_rect.bottom() - 3, 6, 6)
            # Left (W)
            p.drawRect(self._crop_rect.left() - 3, self._crop_rect.top() + self._crop_rect.height() // 2 - 3, 6, 6)
            # Right (E)
            p.drawRect(self._crop_rect.right() - 3, self._crop_rect.top() + self._crop_rect.height() // 2 - 3, 6, 6)

            p.restore()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        pos = event.position().toPoint()
        
        # 1. Check Crop Mode click interaction
        if self._is_crop_mode:
            active_rect = self._uncropped_layer_rects.get(self._selected_index)
            if active_rect:
                # Click on handles
                if self._hit_test_handle(self._crop_rect.left() + self._crop_rect.width() // 2, self._crop_rect.top(), pos):
                    self._active_drag = 'crop-resize'
                    self._crop_handle = 'n'
                elif self._hit_test_handle(self._crop_rect.left() + self._crop_rect.width() // 2, self._crop_rect.bottom(), pos):
                    self._active_drag = 'crop-resize'
                    self._crop_handle = 's'
                elif self._hit_test_handle(self._crop_rect.left(), self._crop_rect.top() + self._crop_rect.height() // 2, pos):
                    self._active_drag = 'crop-resize'
                    self._crop_handle = 'w'
                elif self._hit_test_handle(self._crop_rect.right(), self._crop_rect.top() + self._crop_rect.height() // 2, pos):
                    self._active_drag = 'crop-resize'
                    self._crop_handle = 'e'
                # Click inside crop box
                elif self._crop_rect.contains(pos):
                    self._active_drag = 'crop-move'
                else:
                    return

                self._start_mouse = pos
                # Cache initial values
                cfg = self._configs[self._selected_index]
                self._start_crop_t = cfg.crop_t
                self._start_crop_b = cfg.crop_b
                self._start_crop_l = cfg.crop_l
                self._start_crop_r = cfg.crop_r
                
                # Cache bounds of layer and crop rect
                self._start_crop_rect = QRect(self._crop_rect)
            return

        # 2. Check standard Layout Mode click interaction
        # Check resize handles first
        active_rect = self._layer_rects.get(self._selected_index)
        if active_rect:
            # 1. Top-Left (NW)
            if self._hit_test_handle(active_rect.left(), active_rect.top(), pos):
                self._active_drag = 'resize'
                self._resize_handle = 'nw'
                self._start_mouse = pos
                self._start_size = self._configs[self._selected_index].size
                return
            # 2. Top-Right (NE)
            elif self._hit_test_handle(active_rect.right(), active_rect.top(), pos):
                self._active_drag = 'resize'
                self._resize_handle = 'ne'
                self._start_mouse = pos
                self._start_size = self._configs[self._selected_index].size
                return
            # 3. Bottom-Left (SW)
            elif self._hit_test_handle(active_rect.left(), active_rect.bottom(), pos):
                self._active_drag = 'resize'
                self._resize_handle = 'sw'
                self._start_mouse = pos
                self._start_size = self._configs[self._selected_index].size
                return
            # 4. Bottom-Right (SE)
            elif self._hit_test_handle(active_rect.right(), active_rect.bottom(), pos):
                self._active_drag = 'resize'
                self._resize_handle = 'se'
                self._start_mouse = pos
                self._start_size = self._configs[self._selected_index].size
                return
            # 5. Top-Center (N)
            elif self._hit_test_handle(active_rect.left() + active_rect.width() // 2, active_rect.top(), pos):
                self._active_drag = 'resize'
                self._resize_handle = 'n'
                self._start_mouse = pos
                self._start_size = self._configs[self._selected_index].size
                return
            # 6. Bottom-Center (S)
            elif self._hit_test_handle(active_rect.left() + active_rect.width() // 2, active_rect.bottom(), pos):
                self._active_drag = 'resize'
                self._resize_handle = 's'
                self._start_mouse = pos
                self._start_size = self._configs[self._selected_index].size
                return
            # 7. Left-Center (W)
            elif self._hit_test_handle(active_rect.left(), active_rect.top() + active_rect.height() // 2, pos):
                self._active_drag = 'resize'
                self._resize_handle = 'w'
                self._start_mouse = pos
                self._start_size = self._configs[self._selected_index].size
                return
            # 8. Right-Center (E)
            elif self._hit_test_handle(active_rect.right(), active_rect.top() + active_rect.height() // 2, pos):
                self._active_drag = 'resize'
                self._resize_handle = 'e'
                self._start_mouse = pos
                self._start_size = self._configs[self._selected_index].size
                return

        # Click inside any enabled layer (top to bottom index)
        for i in sorted(self._layer_rects.keys(), reverse=True):
            rect = self._layer_rects[i]
            if rect.contains(pos):
                self.select_layer(i)
                self._active_drag = 'move'
                self._start_mouse = pos
                cfg = self._configs[i]
                self._start_margin_l = cfg.margin_l
                self._start_margin_r = cfg.margin_r
                self._start_margin_t = cfg.margin_t
                self._start_margin_b = cfg.margin_b
                return

        # Click outside all layers -> deselect
        self.select_layer(None)

    def _hit_test_handle(self, hx: int, hy: int, mouse_pos: QPoint) -> bool:
        """Returns True if mouse is within 6px tolerance of handle coordinate."""
        return abs(hx - mouse_pos.x()) <= 8 and abs(hy - mouse_pos.y()) <= 8

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if not self._active_drag:
            # Show hover cursor indications
            self._update_cursor(pos)
            return

        dx = pos.x() - self._start_mouse.x()
        dy = pos.y() - self._start_mouse.y()

        scale_x = self._ws_w_rendered / float(self._ws_w)
        scale_y = self._ws_h_rendered / float(self._ws_h)

        # Scale pixel movements back to virtual workspace coordinates
        ws_dx = int(dx / scale_x)
        ws_dy = int(dy / scale_y)

        # 1. Moving layer position
        if self._active_drag == 'move':
            cfg = self._configs[self._selected_index]
            
            # Simple direct updates: increment margins depending on alignment
            # Bottom-Right (0) active offsets: margin_r & margin_b decreases as mouse moves right & down
            # Bottom-Left (1) active offsets: margin_l & margin_b
            # Top-Right (2) active offsets: margin_r & margin_t
            # Top-Left (3) active offsets: margin_l & margin_t
            # Center (4): update left/right top/bottom
            
            if cfg.position == 0: # BR
                cfg.margin_r = max(0, self._start_margin_r - ws_dx)
                cfg.margin_b = max(0, self._start_margin_b - ws_dy)
            elif cfg.position == 1: # BL
                cfg.margin_l = max(0, self._start_margin_l + ws_dx)
                cfg.margin_b = max(0, self._start_margin_b - ws_dy)
            elif cfg.position == 2: # TR
                cfg.margin_r = max(0, self._start_margin_r - ws_dx)
                cfg.margin_t = max(0, self._start_margin_t + ws_dy)
            elif cfg.position == 3: # TL
                cfg.margin_l = max(0, self._start_margin_l + ws_dx)
                cfg.margin_t = max(0, self._start_margin_t + ws_dy)
            else: # Center
                cfg.margin_l = max(0, self._start_margin_l + ws_dx)
                cfg.margin_r = max(0, self._start_margin_r - ws_dx)
                cfg.margin_t = max(0, self._start_margin_t + ws_dy)
                cfg.margin_b = max(0, self._start_margin_b - ws_dy)

            self.layerMoved.emit(self._selected_index, cfg.margin_t, cfg.margin_b, cfg.margin_l, cfg.margin_r)
            self.update()

        # 2. Resizing layer
        elif self._active_drag == 'resize':
            cfg = self._configs[self._selected_index]
            
            # Compute size adjustment based on 8 handles
            if self._resize_handle in ('se', 'ne', 'e'):
                new_size = max(10, min(100, self._start_size + int(ws_dx * 0.5)))
            elif self._resize_handle in ('sw', 'nw', 'w'):
                new_size = max(10, min(100, self._start_size - int(ws_dx * 0.5)))
            elif self._resize_handle == 's':
                new_size = max(10, min(100, self._start_size + int(ws_dy * 0.5)))
            else: # 'n'
                new_size = max(10, min(100, self._start_size - int(ws_dy * 0.5)))
                
            cfg.size = new_size
            self.layerResized.emit(self._selected_index, new_size)
            self.update()

        # 3. Cropping layer
        elif self._active_drag == 'crop-resize':
            cfg = self._configs[self._selected_index]
            uncropped_rect = self._uncropped_layer_rects[self._selected_index]
            
            # Scale uncropped layer boundaries to workspace pixels
            ws_layer_w = int(uncropped_rect.width() / scale_x)
            ws_layer_h = int(uncropped_rect.height() / scale_y)

            if self._crop_handle == 'n':
                cfg.crop_t = max(0, min(ws_layer_h - cfg.crop_b - 10, self._start_crop_t + ws_dy))
            elif self._crop_handle == 's':
                cfg.crop_b = max(0, min(ws_layer_h - cfg.crop_t - 10, self._start_crop_b - ws_dy))
            elif self._crop_handle == 'w':
                cfg.crop_l = max(0, min(ws_layer_w - cfg.crop_r - 10, self._start_crop_l + ws_dx))
            elif self._crop_handle == 'e':
                cfg.crop_r = max(0, min(ws_layer_w - cfg.crop_l - 10, self._start_crop_r - ws_dx))

            self.layerCropped.emit(self._selected_index, cfg.crop_t, cfg.crop_b, cfg.crop_l, cfg.crop_r)
            self.update()

    def mouseReleaseEvent(self, event):
        self._active_drag = None
        self._resize_handle = None
        self._crop_handle = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _update_cursor(self, pos: QPoint):
        # Update pointer cursor visual based on hover position
        if self._is_crop_mode:
            active_rect = self._layer_rects.get(self._selected_index)
            if active_rect:
                if self._hit_test_handle(self._crop_rect.left() + self._crop_rect.width() // 2, self._crop_rect.top(), pos):
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                elif self._hit_test_handle(self._crop_rect.left() + self._crop_rect.width() // 2, self._crop_rect.bottom(), pos):
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                elif self._hit_test_handle(self._crop_rect.left(), self._crop_rect.top() + self._crop_rect.height() // 2, pos):
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                elif self._hit_test_handle(self._crop_rect.right(), self._crop_rect.top() + self._crop_rect.height() // 2, pos):
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                elif self._crop_rect.contains(pos):
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
                else:
                    self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        active_rect = self._layer_rects.get(self._selected_index)
        if active_rect:
            # Diagonal: NW (top-left) and SE (bottom-right)
            if (self._hit_test_handle(active_rect.left(), active_rect.top(), pos) or
                self._hit_test_handle(active_rect.right(), active_rect.bottom(), pos)):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                return
            # Diagonal: NE (top-right) and SW (bottom-left)
            elif (self._hit_test_handle(active_rect.right(), active_rect.top(), pos) or
                  self._hit_test_handle(active_rect.left(), active_rect.bottom(), pos)):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                return
            # Vertical: N (top-center) and S (bottom-center)
            elif (self._hit_test_handle(active_rect.left() + active_rect.width() // 2, active_rect.top(), pos) or
                  self._hit_test_handle(active_rect.left() + active_rect.width() // 2, active_rect.bottom(), pos)):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
                return
            # Horizontal: W (left-center) and E (right-center)
            elif (self._hit_test_handle(active_rect.left(), active_rect.top() + active_rect.height() // 2, pos) or
                  self._hit_test_handle(active_rect.right(), active_rect.top() + active_rect.height() // 2, pos)):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
                return

        # Check hover over layers
        for rect in self._layer_rects.values():
            if rect.contains(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                return

        self.setCursor(Qt.CursorShape.ArrowCursor)
