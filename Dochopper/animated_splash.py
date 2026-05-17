"""
TariffMill Premium Splash Screen

An elegant, high-end splash screen with:
- Crisp, sharp rendering
- Sophisticated design
- Fluid motion graphics
- Premium typography
"""

import math
import time
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF
from PyQt5.QtGui import (QPainter, QColor, QPen, QFont, QPainterPath,
                         QRadialGradient, QLinearGradient)


class AnimatedMillSplash(QWidget):
    """Premium splash screen for TariffMill."""

    def __init__(self, app_name: str = "TariffMill", version: str = "", parent=None):
        super().__init__(parent)
        self.app_name = app_name
        self.version = version

        # Timing
        self.start_time = time.time()
        self.fade_opacity = 1.0
        self.is_fading = False

        # Progress
        self._progress = 0
        self._target_progress = 0
        self._message = "Initializing..."

        # Animation states
        self.intro_progress = 0.0
        self.ring_rotation = 0.0
        self.pulse_phase = 0.0
        self.wave_offset = 0.0

        # Window setup - no transparency for crisp rendering
        self.setFixedSize(540, 340)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        # White background instead of transparency for sharper text
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)

        # Animation timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(16)

    def _animate(self):
        """Update animations."""
        elapsed = time.time() - self.start_time

        # Fade out
        if self.is_fading:
            self.fade_opacity = max(0, self.fade_opacity - 0.04)
            if self.fade_opacity <= 0:
                self.timer.stop()
                self.close()
                return

        # Intro animation (0 to 1.0s)
        if elapsed < 1.0:
            self.intro_progress = self._ease_out_expo(elapsed / 1.0)
        else:
            self.intro_progress = 1.0

        # Continuous animations
        self.ring_rotation = elapsed * 30
        self.pulse_phase = elapsed * 2.5
        self.wave_offset = elapsed * 80

        # Smooth progress
        diff = self._target_progress - self._progress
        self._progress += diff * 0.1

        self.update()

    def _ease_out_expo(self, t: float) -> float:
        return 1 if t == 1 else 1 - pow(2, -10 * t)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.HighQualityAntialiasing, True)

        # Draw solid background first (entire widget)
        painter.fillRect(self.rect(), QColor(15, 23, 42))

        self._draw_background(painter)
        self._draw_orbital_rings(painter)
        self._draw_center_emblem(painter)
        self._draw_title(painter)
        self._draw_tagline(painter)
        self._draw_progress_area(painter)
        self._draw_corner_accents(painter)

        painter.end()

    def _draw_background(self, painter):
        """Draw premium gradient background."""
        painter.save()

        # Main card area
        card = self.rect().adjusted(0, 0, 0, 0)

        # Rich gradient background
        bg = QLinearGradient(0, 0, self.width(), self.height())
        bg.setColorAt(0, QColor(15, 23, 42))
        bg.setColorAt(0.5, QColor(30, 41, 59))
        bg.setColorAt(1, QColor(15, 23, 42))

        painter.setBrush(bg)
        painter.setPen(Qt.NoPen)
        painter.drawRect(card)

        # Subtle top glow
        glow_rect = QRectF(0, 0, self.width(), 140)
        glow = QLinearGradient(0, 0, 0, 140)
        glow.setColorAt(0, QColor(59, 130, 246, 30))
        glow.setColorAt(1, QColor(59, 130, 246, 0))
        painter.setBrush(glow)
        painter.drawRect(glow_rect)

        # Border
        painter.setBrush(Qt.NoBrush)
        border_pen = QPen(QColor(59, 130, 246, 120))
        border_pen.setWidth(2)
        painter.setPen(border_pen)
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))

        painter.restore()

    def _draw_orbital_rings(self, painter):
        """Draw rotating orbital rings around center."""
        painter.save()

        cx, cy = self.width() / 2, 100
        opacity = self.intro_progress * 0.7

        # Outer ring
        painter.translate(cx, cy)
        painter.rotate(self.ring_rotation)

        # Draw ring as arc segments for gradient effect
        pen = QPen(QColor(59, 130, 246, int(200 * opacity)))
        pen.setWidth(2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # Draw partial arcs for visual interest
        painter.drawArc(QRectF(-50, -50, 100, 100), 0, 120 * 16)

        pen.setColor(QColor(139, 92, 246, int(200 * opacity)))
        painter.setPen(pen)
        painter.drawArc(QRectF(-50, -50, 100, 100), 180 * 16, 120 * 16)

        # Inner ring (counter-rotate)
        painter.rotate(-self.ring_rotation * 2)

        pen.setColor(QColor(236, 72, 153, int(150 * opacity)))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawArc(QRectF(-36, -36, 72, 72), 60 * 16, 120 * 16)

        pen.setColor(QColor(59, 130, 246, int(150 * opacity)))
        painter.setPen(pen)
        painter.drawArc(QRectF(-36, -36, 72, 72), 240 * 16, 120 * 16)

        painter.restore()

    def _draw_center_emblem(self, painter):
        """Draw the central emblem."""
        painter.save()

        cx, cy = self.width() / 2, 100
        scale = self.intro_progress

        painter.translate(cx, cy)
        painter.scale(scale, scale)

        # Outer glow circle
        glow = QRadialGradient(0, 0, 45)
        glow.setColorAt(0, QColor(59, 130, 246, 60))
        glow.setColorAt(0.6, QColor(139, 92, 246, 30))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(glow)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(0, 0), 45, 45)

        # Main emblem circle
        emblem_bg = QRadialGradient(0, -8, 32)
        emblem_bg.setColorAt(0, QColor(51, 65, 85))
        emblem_bg.setColorAt(1, QColor(30, 41, 59))

        painter.setBrush(emblem_bg)
        pen = QPen(QColor(71, 85, 105))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawEllipse(QPointF(0, 0), 28, 28)

        # Pulsing inner ring
        pulse = 0.85 + 0.15 * math.sin(self.pulse_phase)
        pen = QPen(QColor(59, 130, 246, 180))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(0, 0), 20 * pulse, 20 * pulse)

        # Hopper monogram — four spokes radiating from a center hub.
        # Matches the app icon (Resources/*.svg). Replaces the prior "TM"
        # text glyph; same drawing works for both the TariffMill and
        # DocHopper brands since both share the mill/hopper iconography.
        hopper_fg = QColor(226, 232, 240)
        hopper_shadow = QColor(0, 0, 0, 100)

        SPOKE_INNER = 6        # distance from center to inner end of spoke
        SPOKE_OUTER = 14       # distance to outer end
        SPOKE_THICK = 3.0      # spoke thickness
        spoke_len = SPOKE_OUTER - SPOKE_INNER
        radius = SPOKE_THICK / 2

        def _spokes(brush, dx=0.0, dy=0.0):
            painter.setBrush(brush)
            # Left
            painter.drawRoundedRect(QRectF(-SPOKE_OUTER + dx, -radius + dy, spoke_len, SPOKE_THICK), radius, radius)
            # Right
            painter.drawRoundedRect(QRectF(SPOKE_INNER + dx, -radius + dy, spoke_len, SPOKE_THICK), radius, radius)
            # Top
            painter.drawRoundedRect(QRectF(-radius + dx, -SPOKE_OUTER + dy, SPOKE_THICK, spoke_len), radius, radius)
            # Bottom
            painter.drawRoundedRect(QRectF(-radius + dx, SPOKE_INNER + dy, SPOKE_THICK, spoke_len), radius, radius)

        painter.setPen(Qt.NoPen)
        # Shadow pass first (offset 1px down-right)
        _spokes(hopper_shadow, dx=1.0, dy=1.0)
        # Main pass
        _spokes(hopper_fg)

        # Center hub — white outer ring + dark inner dot (donut look)
        painter.setBrush(hopper_fg)
        painter.drawEllipse(QPointF(0, 0), 5.0, 5.0)
        painter.setBrush(QColor(30, 41, 59))   # match emblem_bg base color
        painter.drawEllipse(QPointF(0, 0), 2.5, 2.5)

        painter.restore()

    def _draw_title(self, painter):
        """Draw application title."""
        painter.save()

        opacity = max(0, (self.intro_progress - 0.2) / 0.8) if self.intro_progress > 0.2 else 0

        # Title font
        font = QFont("Segoe UI", 36, QFont.Light)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        painter.setFont(font)

        title_rect = QRectF(0, 155, self.width(), 50)

        # Shadow
        painter.setPen(QColor(0, 0, 0, int(100 * opacity)))
        painter.drawText(title_rect.adjusted(2, 2, 2, 2), Qt.AlignCenter, self.app_name)

        # Main title
        painter.setPen(QColor(248, 250, 252, int(255 * opacity)))
        painter.drawText(title_rect, Qt.AlignCenter, self.app_name)

        painter.restore()

    def _draw_tagline(self, painter):
        """Draw tagline. Pulled from _branding.APP_TAGLINE when available so
        TariffMill and DocHopper render their respective taglines from a
        single source of truth."""
        painter.save()

        opacity = max(0, (self.intro_progress - 0.4) / 0.6) if self.intro_progress > 0.4 else 0

        font = QFont("Segoe UI", 10)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        painter.setFont(font)
        painter.setPen(QColor(148, 163, 184, int(255 * opacity)))

        try:
            from Tariffmill._branding import APP_TAGLINE
        except ImportError:
            try:
                from _branding import APP_TAGLINE  # type: ignore[no-redef]
            except ImportError:
                APP_TAGLINE = "Customs Documentation Processing"

        painter.drawText(QRectF(0, 205, self.width(), 25), Qt.AlignCenter,
                        APP_TAGLINE.upper())

        painter.restore()

    def _draw_progress_area(self, painter):
        """Draw progress bar and status."""
        painter.save()

        opacity = max(0, (self.intro_progress - 0.5) / 0.5) if self.intro_progress > 0.5 else 0

        # Status message
        font = QFont("Segoe UI", 10)
        painter.setFont(font)
        painter.setPen(QColor(148, 163, 184, int(255 * opacity)))
        painter.drawText(QRectF(0, 248, self.width(), 20), Qt.AlignCenter, self._message)

        # Progress bar dimensions
        bar_width = 320
        bar_height = 5
        bar_x = (self.width() - bar_width) / 2
        bar_y = 278

        # Track background
        painter.setBrush(QColor(51, 65, 85, int(255 * opacity)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_width, bar_height), 2, 2)

        # Progress fill
        if self._progress > 0.5:
            fill_width = (self._progress / 100) * bar_width

            # Animated gradient
            offset = self.wave_offset % (bar_width * 2)
            fill_grad = QLinearGradient(bar_x - offset, 0, bar_x + bar_width * 2 - offset, 0)
            fill_grad.setColorAt(0, QColor(59, 130, 246))
            fill_grad.setColorAt(0.33, QColor(99, 102, 241))
            fill_grad.setColorAt(0.66, QColor(139, 92, 246))
            fill_grad.setColorAt(1, QColor(59, 130, 246))

            # Clip and draw
            painter.setClipRect(QRectF(bar_x, bar_y, fill_width, bar_height))
            painter.setBrush(fill_grad)
            painter.setOpacity(opacity)
            painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_width, bar_height), 2, 2)
            painter.setClipping(False)

            # Top shine
            shine = QLinearGradient(0, bar_y, 0, bar_y + bar_height)
            shine.setColorAt(0, QColor(255, 255, 255, 70))
            shine.setColorAt(0.5, QColor(255, 255, 255, 0))
            painter.setClipRect(QRectF(bar_x, bar_y, fill_width, bar_height / 2))
            painter.setBrush(shine)
            painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_width, bar_height), 2, 2)
            painter.setClipping(False)

        # Percentage text
        painter.setOpacity(opacity)
        pct_font = QFont("Segoe UI", 9)
        painter.setFont(pct_font)
        painter.setPen(QColor(100, 116, 139))
        painter.drawText(QRectF(bar_x + bar_width + 12, bar_y - 3, 50, 14),
                        Qt.AlignLeft | Qt.AlignVCenter, f"{int(self._progress)}%")

        painter.restore()

    def _draw_corner_accents(self, painter):
        """Draw corner accent decorations."""
        painter.save()

        opacity = self.intro_progress * 0.25

        # Top left - blue
        pen = QPen(QColor(59, 130, 246, int(255 * opacity)))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(15, 12, 40, 12)
        painter.drawLine(12, 15, 12, 40)

        # Top right - blue
        painter.drawLine(self.width() - 40, 12, self.width() - 15, 12)
        painter.drawLine(self.width() - 12, 15, self.width() - 12, 40)

        # Bottom left - purple
        pen.setColor(QColor(139, 92, 246, int(255 * opacity)))
        painter.setPen(pen)
        painter.drawLine(15, self.height() - 12, 40, self.height() - 12)
        painter.drawLine(12, self.height() - 40, 12, self.height() - 15)

        # Bottom right - purple
        painter.drawLine(self.width() - 40, self.height() - 12, self.width() - 15, self.height() - 12)
        painter.drawLine(self.width() - 12, self.height() - 40, self.width() - 12, self.height() - 15)

        painter.restore()

        # Version
        if self.version:
            painter.save()
            opacity = max(0, (self.intro_progress - 0.6) / 0.4) if self.intro_progress > 0.6 else 0

            font = QFont("Segoe UI", 8)
            painter.setFont(font)
            painter.setPen(QColor(100, 116, 139, int(180 * opacity)))
            ver = self.version if self.version.startswith('v') else f"v{self.version}"
            painter.drawText(QRectF(0, 308, self.width(), 20), Qt.AlignCenter, ver)
            painter.restore()

    def setText(self, text: str):
        self._message = text

    def setProgress(self, value: int):
        self._target_progress = min(100, max(0, value))

    def setVersion(self, version: str):
        self.version = version

    def fadeOut(self):
        self.is_fading = True

    def stop(self):
        self.timer.stop()


def create_splash(app_name: str = "TariffMill", version: str = "") -> AnimatedMillSplash:
    return AnimatedMillSplash(app_name, version)


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)

    # Enable high DPI scaling for crisp rendering
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    splash = create_splash("TariffMill", "2.4.0")
    splash.show()

    screen_geo = app.desktop().availableGeometry()
    splash.move(
        (screen_geo.width() - splash.width()) // 2,
        (screen_geo.height() - splash.height()) // 2
    )

    def update_progress():
        current = splash._target_progress
        if current < 100:
            splash.setProgress(current + 2)
            messages = [
                "Loading configuration...",
                "Connecting to database...",
                "Loading user preferences...",
                "Initializing workspace...",
                "Starting services...",
                "Almost ready..."
            ]
            msg_idx = min(current // 18, len(messages) - 1)
            splash.setText(messages[msg_idx])
        else:
            splash.fadeOut()

    progress_timer = QTimer()
    progress_timer.timeout.connect(update_progress)
    QTimer.singleShot(800, lambda: progress_timer.start(50))

    sys.exit(app.exec_())
