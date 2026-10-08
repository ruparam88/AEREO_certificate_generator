"""Certificate PDF generation service.

This module handles PDF creation using ReportLab. It supports:
1. Three built-in template styles:
   - 'classic': Traditional gold double-border on cream background with classical serif typography
   - 'modern': Minimalist geometric design with blue accents and crisp modern typography
   - 'elegant': Dark navy executive design with radiant gold highlights and luxury serif typography
2. User-uploaded custom templates (e.g. Canva / Photoshop PNG / JPEG / PDF):
   - 'preprinted' mode: For complete templates (like Borcelle Company's template)
     that already have title, borders, and signatures. Perfectly overlays the
     recipient's name, course name, and date on the designated placeholder lines.
   - 'full' mode: For blank decorative borders/frames where full certificate
     titles, course name, date, and signatures are generated.
   - Dynamic aspect-ratio matching to eliminate white letterboxing/margins.
   - Exact color matching (auto-detects template's primary & accent color palette).
   - Exact font matching (modern sans-serif vs classic serif with graceful system fallbacks).
"""

import os
import io
import re
from typing import Any
from collections import Counter
from PIL import Image
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.colors import Color, HexColor
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


# ---------------------------------------------------------------------------
# Font Registry & Typography Management
# ---------------------------------------------------------------------------

_FONTS_INITIALIZED = False
_FONT_MAP = {
    "sans_bold": "Helvetica-Bold",
    "sans_regular": "Helvetica",
    "serif_bold": "Times-Bold",
    "serif_regular": "Times-Roman",
    "elegant_bold": "Times-Bold",
    "elegant_regular": "Times-Roman",
}


def _ensure_fonts_registered() -> None:
    """Register system TrueType fonts (e.g. Segoe UI, Georgia, Palatino) if available,
    falling back to built-in standard PostScript fonts otherwise.
    """
    global _FONTS_INITIALIZED, _FONT_MAP
    if _FONTS_INITIALIZED:
        return

    windows_fonts = r"C:\Windows\Fonts"
    candidates = {
        ("sans_bold", "SegoeUI-Bold"): ["segoeuib.ttf", "arialbd.ttf"],
        ("sans_regular", "SegoeUI"): ["segoeui.ttf", "arial.ttf"],
        ("serif_bold", "Georgia-Bold"): ["georgiab.ttf", "timesbd.ttf"],
        ("serif_regular", "Georgia"): ["georgia.ttf", "times.ttf"],
        ("elegant_bold", "Palatino-Bold"): ["palab.ttf", "georgiab.ttf", "timesbd.ttf"],
        ("elegant_regular", "Palatino"): ["pala.ttf", "georgia.ttf", "times.ttf"],
    }

    if os.path.exists(windows_fonts):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        for (map_key, reg_name), file_names in candidates.items():
            for fn in file_names:
                fpath = os.path.join(windows_fonts, fn)
                if os.path.exists(fpath):
                    try:
                        pdfmetrics.registerFont(TTFont(reg_name, fpath))
                        _FONT_MAP[map_key] = reg_name
                        break
                    except Exception:
                        pass

    _FONTS_INITIALIZED = True


def _get_font_pair(font_family: str | None) -> tuple[str, str]:
    """Return (bold_font_name, regular_font_name) for the requested family."""
    _ensure_fonts_registered()
    fam = (font_family or "sans").lower().strip()
    if fam in ("serif", "classic", "times", "georgia"):
        return _FONT_MAP["serif_bold"], _FONT_MAP["serif_regular"]
    elif fam in ("elegant", "luxury", "palatino"):
        return _FONT_MAP["elegant_bold"], _FONT_MAP["elegant_regular"]
    else:
        return _FONT_MAP["sans_bold"], _FONT_MAP["sans_regular"]


# ---------------------------------------------------------------------------
# Color Palette & Resolvers
# ---------------------------------------------------------------------------

GOLD = HexColor("#C8A951")
GOLD_BRIGHT = HexColor("#E5C378")
DARK_NAVY = HexColor("#1B2A4A")
PANEL_NAVY = HexColor("#1F3461")
WHITE = HexColor("#FFFFFF")
CREAM = HexColor("#FFF8E7")

TEXT_DARK = HexColor("#1E293B")
TEXT_MUTED = HexColor("#475569")
TEXT_LIGHT = HexColor("#CBD5E1")
TEXT_SUBTLE = HexColor("#94A3B8")
ACCENT_BLUE = HexColor("#2E86AB")


def _resolve_color(val: Any, fallback: Any) -> Color:
    """Safely convert a hex string or Color to Color with fallback."""
    if isinstance(val, Color):
        return val
    if isinstance(val, str) and val.strip():
        s = val.strip()
        if not s.startswith("#") and len(s) in (3, 6, 8):
            s = f"#{s}"
        try:
            return HexColor(s)
        except Exception:
            pass
    return fallback


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_certificate(
    recipient_name: str,
    course_name: str,
    date: str,
    certificate_id: str,
    output_dir: str,
    template_style: str = "classic",
    custom_template_path: str | None = None,
    overlay_mode: str = "full",
    name_y_ratio: float = 0.515,
    course_y_ratio: float | None = None,
    course_x_ratio: float | None = None,
    date_y_ratio: float | None = None,
    date_x_ratio: float | None = None,
    show_course: bool = True,
    show_date: bool = True,
    font_family: str = "sans",
    primary_color: str | None = None,
    accent_color: str | None = None,
) -> str:
    """Generate a single PDF certificate and save it to disk.

    Args:
        recipient_name: Full name of the recipient (printed prominently).
        course_name: Name of the course or event.
        date: Date string in YYYY-MM-DD format.
        certificate_id: Unique ID for this certificate (printed as footer).
        output_dir: Directory where the PDF will be saved.
        template_style: One of 'classic', 'modern', 'elegant'.
        custom_template_path: Path to user-uploaded background image or PDF.
        overlay_mode: 'preprinted' (name, course, date overlay) or 'full' (all text).
        name_y_ratio: Position of recipient name from bottom.
        course_y_ratio: Vertical position ratio for course name (None for auto).
        course_x_ratio: Horizontal center ratio for course name (None for auto).
        date_y_ratio: Vertical position ratio for date (None for auto).
        date_x_ratio: Horizontal center ratio for date (None for auto).
        show_course: Whether to render course name on preprinted templates.
        show_date: Whether to render date on preprinted templates.
        font_family: Typography style ('sans', 'serif', 'elegant').
        primary_color: Primary text hex color (e.g. '#0A001D' or '#1E293B').
        accent_color: Accent hex color (e.g. '#609AAD' or '#C8A951').

    Returns:
        Absolute path to the generated PDF file.
    """
    os.makedirs(output_dir, exist_ok=True)

    filename = f"certificate_{certificate_id}.pdf"
    file_path = os.path.join(output_dir, filename)

    if custom_template_path:
        if not os.path.exists(custom_template_path):
            raise FileNotFoundError(f"Template image not found: {custom_template_path}")

        if custom_template_path.lower().endswith(".pdf"):
            # Support PDF vector templates natively via pypdf page merging
            import pypdf

            reader = pypdf.PdfReader(custom_template_path)
            if not reader.pages:
                raise ValueError("Custom PDF template has no pages")
            template_page = reader.pages[0]

            page_width = float(template_page.mediabox.width)
            page_height = float(template_page.mediabox.height)
            mbox_bottom = float(template_page.mediabox.bottom or 0.0)
            mbox_left = float(template_page.mediabox.left or 0.0)

            # Auto-detect layout and palette if not specified
            layout = detect_template_layout(custom_template_path)
            if overlay_mode == "preprinted":
                if course_y_ratio is None and date_y_ratio is None:
                    name_y_ratio = layout.get("name_y_ratio", name_y_ratio)
                    course_y_ratio = layout.get("course_y_ratio")
                    course_x_ratio = layout.get("course_x_ratio")
                    date_y_ratio = layout.get("date_y_ratio")
                    date_x_ratio = layout.get("date_x_ratio")
                    if "show_course" in layout:
                        show_course = layout["show_course"]
                    if "show_date" in layout:
                        show_date = layout["show_date"]

            if not primary_color and "primary_color" in layout:
                primary_color = layout["primary_color"]
            if not accent_color and "accent_color" in layout:
                accent_color = layout["accent_color"]
            if (not font_family or font_family == "sans") and "font_family" in layout:
                font_family = layout["font_family"]

            packet = io.BytesIO()
            c = canvas.Canvas(packet, pagesize=(page_width, page_height))

            # Translate canvas origin so (0, 0) in ReportLab aligns with PDF MediaBox lower-left
            if mbox_bottom != 0.0 or mbox_left != 0.0:
                c.translate(mbox_left, mbox_bottom)

            if overlay_mode == "preprinted":
                _draw_preprinted_custom_content(
                    c=c,
                    recipient_name=recipient_name,
                    course_name=course_name,
                    date=date,
                    certificate_id=certificate_id,
                    page_width=page_width,
                    page_height=page_height,
                    name_y_ratio=name_y_ratio,
                    course_y_ratio=course_y_ratio,
                    course_x_ratio=course_x_ratio,
                    date_y_ratio=date_y_ratio,
                    date_x_ratio=date_x_ratio,
                    show_course=show_course,
                    show_date=show_date,
                    font_family=font_family,
                    primary_color=primary_color,
                    accent_color=accent_color,
                )
            else:
                _draw_certificate_content(
                    c=c,
                    recipient_name=recipient_name,
                    course_name=course_name,
                    date=date,
                    certificate_id=certificate_id,
                    template_style="classic",
                    page_width=page_width,
                    page_height=page_height,
                    font_family=font_family,
                    primary_color=primary_color,
                    accent_color=accent_color,
                )

            c.save()
            packet.seek(0)

            overlay_reader = pypdf.PdfReader(packet)

            writer = pypdf.PdfWriter()
            merged_page = writer.add_page(template_page)
            merged_page.merge_page(overlay_reader.pages[0])

            with open(file_path, "wb") as f:
                writer.write(f)

            return os.path.abspath(file_path)

        # Image custom templates (PNG, JPEG): dynamic aspect ratio canvas
        with Image.open(custom_template_path) as im:
            img_w, img_h = im.size

        aspect = img_w / img_h
        page_height = 595.27  # A4 height in points
        page_width = page_height * aspect

        layout = detect_template_layout(custom_template_path)
        if overlay_mode == "preprinted":
            if course_y_ratio is None and date_y_ratio is None:
                name_y_ratio = layout.get("name_y_ratio", name_y_ratio)
                course_y_ratio = layout.get("course_y_ratio")
                course_x_ratio = layout.get("course_x_ratio")
                date_y_ratio = layout.get("date_y_ratio")
                date_x_ratio = layout.get("date_x_ratio")
                if "show_course" in layout:
                    show_course = layout["show_course"]
                if "show_date" in layout:
                    show_date = layout["show_date"]

        if not primary_color and "primary_color" in layout:
            primary_color = layout["primary_color"]
        if not accent_color and "accent_color" in layout:
            accent_color = layout["accent_color"]
        if (not font_family or font_family == "sans") and "font_family" in layout:
            font_family = layout["font_family"]

        c = canvas.Canvas(file_path, pagesize=(page_width, page_height))

        # Draw custom background filling 100% of the canvas
        c.drawImage(
            ImageReader(custom_template_path),
            0, 0,
            width=page_width,
            height=page_height,
        )

        if overlay_mode == "preprinted":
            _draw_preprinted_custom_content(
                c=c,
                recipient_name=recipient_name,
                course_name=course_name,
                date=date,
                certificate_id=certificate_id,
                page_width=page_width,
                page_height=page_height,
                name_y_ratio=name_y_ratio,
                course_y_ratio=course_y_ratio,
                course_x_ratio=course_x_ratio,
                date_y_ratio=date_y_ratio,
                date_x_ratio=date_x_ratio,
                show_course=show_course,
                show_date=show_date,
                font_family=font_family,
                primary_color=primary_color,
                accent_color=accent_color,
            )
        else:
            _draw_certificate_content(
                c=c,
                recipient_name=recipient_name,
                course_name=course_name,
                date=date,
                certificate_id=certificate_id,
                template_style="classic",
                page_width=page_width,
                page_height=page_height,
                font_family=font_family,
                primary_color=primary_color,
                accent_color=accent_color,
            )

    else:
        # Built-in templates: standard Letter landscape
        page_width, page_height = landscape(LETTER)
        c = canvas.Canvas(file_path, pagesize=(page_width, page_height))

        if template_style == "classic":
            _draw_classic_template(c, page_width, page_height)
            font_family = font_family if font_family != "sans" else "serif"
            primary_color = primary_color or "#1B2A4A"
            accent_color = accent_color or "#C8A951"
        elif template_style == "modern":
            _draw_modern_template(c, page_width, page_height)
            font_family = font_family or "sans"
            primary_color = primary_color or "#0F172A"
            accent_color = accent_color or "#2E86AB"
        elif template_style == "elegant":
            _draw_elegant_template(c, page_width, page_height)
            font_family = font_family if font_family != "sans" else "elegant"
            primary_color = primary_color or "#FFFFFF"
            accent_color = accent_color or "#E5C378"
        else:
            raise ValueError(
                f"Unknown template style: '{template_style}'. "
                f"Choose from: 'classic', 'modern', 'elegant'."
            )

        _draw_certificate_content(
            c=c,
            recipient_name=recipient_name,
            course_name=course_name,
            date=date,
            certificate_id=certificate_id,
            template_style=template_style,
            page_width=page_width,
            page_height=page_height,
            font_family=font_family,
            primary_color=primary_color,
            accent_color=accent_color,
        )

    c.save()
    return os.path.abspath(file_path)


# ---------------------------------------------------------------------------
# Built-in Template Renderers
# ---------------------------------------------------------------------------

def _draw_classic_template(c: canvas.Canvas, width: float, height: float) -> None:
    """Classic template: Gold double border with cream background."""
    c.setFillColor(CREAM)
    c.rect(0, 0, width, height, fill=True, stroke=False)

    # Outer gold border
    c.setStrokeColor(GOLD)
    c.setLineWidth(4)
    c.rect(20, 20, width - 40, height - 40, fill=False, stroke=True)

    # Inner gold border
    c.setLineWidth(1.5)
    c.rect(35, 35, width - 70, height - 70, fill=False, stroke=True)

    # Corner decorations
    corner_size = 12
    c.setFillColor(GOLD)
    for x, y in [
        (25, 25),
        (width - 25 - corner_size, 25),
        (25, height - 25 - corner_size),
        (width - 25 - corner_size, height - 25 - corner_size),
    ]:
        c.rect(x, y, corner_size, corner_size, fill=True, stroke=False)


def _draw_modern_template(c: canvas.Canvas, width: float, height: float) -> None:
    """Modern template: Clean geometric design with blue accents."""
    c.setFillColor(WHITE)
    c.rect(0, 0, width, height, fill=True, stroke=False)

    # Left accent bar
    c.setFillColor(ACCENT_BLUE)
    c.rect(0, 0, 40, height, fill=True, stroke=False)

    # Top & bottom accent strips
    c.setFillColor(ACCENT_BLUE)
    c.rect(0, height - 8, width, 8, fill=True, stroke=False)
    c.rect(0, 0, width, 8, fill=True, stroke=False)

    # Subtle grid pattern
    c.setStrokeColor(HexColor("#E8E8E8"))
    c.setLineWidth(0.3)
    for x in range(60, int(width), 50):
        c.line(x, 20, x, height - 20)
    for y in range(20, int(height), 50):
        c.line(60, y, width - 20, y)

    # Circle decoration
    c.setFillColor(HexColor("#E8F4F8"))
    c.circle(width - 80, height - 80, 50, fill=True, stroke=False)
    c.setStrokeColor(ACCENT_BLUE)
    c.setLineWidth(2)
    c.circle(width - 80, height - 80, 50, fill=False, stroke=True)


def _draw_elegant_template(c: canvas.Canvas, width: float, height: float) -> None:
    """Elegant template: Dark navy executive background with gold highlights."""
    c.setFillColor(DARK_NAVY)
    c.rect(0, 0, width, height, fill=True, stroke=False)

    # Inner rounded panel
    margin = 48
    c.setFillColor(PANEL_NAVY)
    c.roundRect(
        margin, margin,
        width - 2 * margin, height - 2 * margin,
        radius=10, fill=True, stroke=False,
    )

    # Gold border on inner panel
    c.setStrokeColor(GOLD)
    c.setLineWidth(2)
    c.roundRect(
        margin, margin,
        width - 2 * margin, height - 2 * margin,
        radius=10, fill=False, stroke=True,
    )

    # Top & bottom decorative gold lines
    y_top = height - margin - 25
    y_bottom = margin + 25
    c.setStrokeColor(GOLD)
    c.setLineWidth(1)
    c.line(margin + 25, y_top, width - margin - 25, y_top)
    c.line(margin + 25, y_bottom, width - margin - 25, y_bottom)

    # Center diamond decorations
    center_x = width / 2
    for y in [y_top, y_bottom]:
        c.setFillColor(GOLD)
        c.saveState()
        c.translate(center_x, y)
        c.rotate(45)
        c.rect(-5, -5, 10, 10, fill=True, stroke=False)
        c.restoreState()


# ---------------------------------------------------------------------------
# Certificate Content Renderers
# ---------------------------------------------------------------------------

def _draw_certificate_content(
    c: canvas.Canvas,
    recipient_name: str,
    course_name: str,
    date: str,
    certificate_id: str,
    template_style: str = "classic",
    page_width: float = 792.0,
    page_height: float = 612.0,
    font_family: str = "sans",
    primary_color: str | None = None,
    accent_color: str | None = None,
) -> None:
    """Draw complete certificate content (used for built-in & blank frame templates)."""
    center_x = page_width / 2
    font_bold, font_regular = _get_font_pair(font_family)

    # Theme-aware colors
    is_dark = (template_style == "elegant")
    if is_dark:
        title_col = _resolve_color(accent_color, GOLD_BRIGHT)
        name_col = _resolve_color(primary_color, WHITE)
        subtitle_col = TEXT_LIGHT
        course_col = _resolve_color(accent_color, GOLD_BRIGHT)
        date_col = TEXT_LIGHT
        sig_line_col = GOLD
        sig_label_col = TEXT_SUBTLE
        id_col = HexColor("#64748B")
    else:
        title_col = _resolve_color(primary_color, TEXT_DARK)
        name_col = _resolve_color(primary_color, TEXT_DARK)
        subtitle_col = TEXT_MUTED
        course_col = _resolve_color(primary_color, TEXT_DARK)
        date_col = TEXT_MUTED
        sig_line_col = _resolve_color(accent_color, GOLD)
        sig_label_col = TEXT_MUTED
        id_col = TEXT_SUBTLE

    # Title: "CERTIFICATE OF COMPLETION"
    c.setFont(font_bold, 28)
    c.setFillColor(title_col)
    c.drawCentredString(center_x, page_height - 130, "CERTIFICATE OF COMPLETION")

    # Subtitle
    c.setFont(font_regular, 12)
    c.setFillColor(subtitle_col)
    c.drawCentredString(center_x, page_height - 160, "This is to certify that")

    # Recipient Name with dynamic font-sizing to fit
    name_font_size = 36
    while name_font_size > 18 and c.stringWidth(recipient_name, font_bold, name_font_size) > page_width * 0.72:
        name_font_size -= 2

    c.setFont(font_bold, name_font_size)
    c.setFillColor(name_col)
    c.drawCentredString(center_x, page_height - 220, recipient_name)

    # Underline beneath name
    underline_col = _resolve_color(accent_color, GOLD)
    c.setStrokeColor(underline_col)
    c.setLineWidth(1)
    name_width = c.stringWidth(recipient_name, font_bold, name_font_size)
    half_width = min(name_width / 2 + 25, page_width * 0.35)
    c.line(center_x - half_width, page_height - 235, center_x + half_width, page_height - 235)

    # Course description
    c.setFont(font_regular, 14)
    c.setFillColor(subtitle_col)
    c.drawCentredString(center_x, page_height - 270, "has successfully completed the course")

    # Course Name with dynamic sizing
    course_font_size = 22
    while course_font_size > 12 and c.stringWidth(course_name, font_bold, course_font_size) > page_width * 0.75:
        course_font_size -= 1

    c.setFont(font_bold, course_font_size)
    c.setFillColor(course_col)
    c.drawCentredString(center_x, page_height - 310, course_name)

    # Date
    c.setFont(font_regular, 12)
    c.setFillColor(date_col)
    c.drawCentredString(center_x, page_height - 360, f"Date of Completion: {date}")

    # Signature lines
    sig_y = 105
    c.setStrokeColor(sig_line_col)
    c.setLineWidth(0.8)
    c.line(center_x - 240, sig_y, center_x - 90, sig_y)
    c.line(center_x + 90, sig_y, center_x + 240, sig_y)

    c.setFont(font_regular, 9)
    c.setFillColor(sig_label_col)
    c.drawCentredString(center_x - 165, sig_y - 15, "Program Director")
    c.drawCentredString(center_x + 165, sig_y - 15, "Date")

    # Certificate ID
    id_y = 62 if is_dark else 55
    c.setFont(font_regular, 8)
    c.setFillColor(id_col)
    c.drawCentredString(center_x, id_y, f"Certificate ID: {certificate_id}")


def _draw_preprinted_custom_content(
    c: canvas.Canvas,
    recipient_name: str,
    course_name: str,
    date: str,
    certificate_id: str,
    page_width: float,
    page_height: float,
    name_y_ratio: float = 0.558,
    course_y_ratio: float | None = None,
    course_x_ratio: float | None = None,
    date_y_ratio: float | None = None,
    date_x_ratio: float | None = None,
    show_course: bool = True,
    show_date: bool = True,
    font_family: str = "sans",
    primary_color: str | None = None,
    accent_color: str | None = None,
) -> None:
    """Overlay recipient details onto a pre-designed certificate template.

    Neatly overlays:
    1. Recipient name optically balanced in the designated placeholder area.
    2. Course name perfectly sitting 4.5pt above the course underline line.
    3. Issue date perfectly sitting 4.5pt above the date underline line.
    4. Unique certificate ID at the bottom margin without visual clutter.
    """
    center_x = page_width / 2
    font_bold, font_regular = _get_font_pair(font_family)
    primary_col = _resolve_color(primary_color, HexColor("#0A001D"))
    footer_col = HexColor("#64748B")

    # 1. Recipient Name: auto-adjust font size to fit seamlessly
    name_font_size = 34
    while name_font_size > 18 and c.stringWidth(recipient_name, font_bold, name_font_size) > page_width * 0.70:
        name_font_size -= 2

    c.setFont(font_bold, name_font_size)
    c.setFillColor(primary_col)
    name_y = page_height * (name_y_ratio if name_y_ratio is not None else 0.558)
    c.drawCentredString(center_x, name_y, recipient_name)

    # 2. Course Name: sitting on underline, sized so it never collides with labels
    if show_course and course_y_ratio is not None and course_name:
        course_y = page_height * course_y_ratio
        course_x = page_width * (course_x_ratio if course_x_ratio is not None else 0.562)

        # Underline available width is approx 33% of page width (~280pt on A4)
        max_course_w = min(280.0, page_width * 0.35)
        c_font_size = 16
        while c_font_size > 10 and c.stringWidth(course_name, font_bold, c_font_size) > max_course_w:
            c_font_size -= 1

        c.setFont(font_bold, c_font_size)
        c.setFillColor(primary_col)
        c.drawCentredString(course_x, course_y, course_name)

    # 3. Issue Date: sitting on underline
    if show_date and date_y_ratio is not None and date:
        date_y = page_height * date_y_ratio
        date_x = page_width * (date_x_ratio if date_x_ratio is not None else 0.585)

        c.setFont(font_bold, 13.5)
        c.setFillColor(primary_col)
        c.drawCentredString(date_x, date_y, date)

    # 4. Certificate ID: subtle footer at bottom margin
    c.setFont(font_regular, 8)
    c.setFillColor(footer_col)
    c.drawCentredString(center_x, 14, f"Certificate ID: {certificate_id}")


# ---------------------------------------------------------------------------
# Template Auto-detection & Palette Extraction
# ---------------------------------------------------------------------------

def detect_template_layout(image_path: str) -> dict:
    """Analyze a template image or PDF to detect horizontal placeholder lines,
    field positions, text alignments, dominant brand color palette, and font family.
    """
    ext = os.path.splitext(image_path)[1].lower()

    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(image_path)
            page = reader.pages[0] if reader.pages else None
            text = (page.extract_text() or "") if page else ""

            font_family = "sans"
            primary_color = "#0A001D"
            accent_color = "#609AAD"
            mbox_bottom = float(page.mediabox.bottom or 0.0) if page else 0.0
            mbox_left = float(page.mediabox.left or 0.0) if page else 0.0

            # Extract stream content to inspect fonts and colors
            raw_data = b""
            if page and "/Resources" in page and "/XObject" in page["/Resources"]:
                xobjs = page["/Resources"]["/XObject"].get_object()
                for k, v in xobjs.items():
                    obj = v.get_object()
                    try:
                        raw_data += obj.get_data()
                    except Exception:
                        pass
            if not raw_data and page:
                c_obj = page.get_contents()
                if isinstance(c_obj, list):
                    raw_data = b"".join(c.get_data() for c in c_obj)
                elif c_obj:
                    raw_data = c_obj.get_data()

            stream_text = raw_data.decode("latin-1", errors="ignore")

            # Check font classification
            if any(f in stream_text for f in ["Times", "Georgia", "Garamond", "Minion", "Serif"]):
                font_family = "serif"
            elif any(f in stream_text for f in ["Garet", "Helvetica", "Arial", "Segoe", "Roboto", "Montserrat", "Poppins"]):
                font_family = "sans"

            # Extract colors from stream (e.g. .0392 0 .1137 rg)
            rg_matches = re.findall(r'([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s+rg', stream_text)
            dark_colors = []
            accent_colors = []
            for r_s, g_s, b_s in rg_matches:
                try:
                    r, g, b = float(r_s), float(g_s), float(b_s)
                    brightness = (r * 299 + g * 587 + b * 114) / 1000
                    hex_c = f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"
                    diff = max(r, g, b) - min(r, g, b)
                    if brightness < 0.25:
                        # Prioritize colored darks (like deep navy #0A001D) over pure black
                        if diff > 0.03:
                            dark_colors.insert(0, hex_c)
                        else:
                            dark_colors.append(hex_c)
                    elif 0.20 <= brightness <= 0.75 and diff > 0.08:
                        accent_colors.append(hex_c)
                except Exception:
                    pass

            if dark_colors:
                primary_color = Counter(dark_colors).most_common(1)[0][0]
            if accent_colors:
                accent_color = Counter(accent_colors).most_common(1)[0][0]

            is_multifield = any(kw in text for kw in ["Course name", "Issued on", "Course", "Participation", "PARTICIPATION"])

            if is_multifield:
                return {
                    "name_y_ratio": 0.555,
                    "course_y_ratio": 0.467,
                    "course_x_ratio": 0.562,
                    "date_y_ratio": 0.342,
                    "date_x_ratio": 0.585,
                    "show_course": True,
                    "show_date": True,
                    "font_family": font_family,
                    "primary_color": primary_color,
                    "accent_color": accent_color,
                    "mediabox_bottom": mbox_bottom,
                    "mediabox_left": mbox_left,
                }
            else:
                return {
                    "name_y_ratio": 0.515,
                    "course_y_ratio": None,
                    "course_x_ratio": None,
                    "date_y_ratio": None,
                    "date_x_ratio": None,
                    "show_course": False,
                    "show_date": False,
                    "font_family": font_family,
                    "primary_color": primary_color,
                    "accent_color": accent_color,
                    "mediabox_bottom": mbox_bottom,
                    "mediabox_left": mbox_left,
                }
        except Exception:
            pass

    # Image analysis (PNG, JPEG)
    try:
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            w, h = im.size

        # Sample dominant text and accent colors
        dark_samples = []
        accent_samples = []
        for y in range(0, h, 4):
            for x in range(0, w, 4):
                p = im.getpixel((x, y))
                brightness = (p[0] * 299 + p[1] * 587 + p[2] * 114) / 1000
                diff = max(p) - min(p)
                if brightness < 65:
                    if diff > 10:
                        dark_samples.insert(0, p)
                    else:
                        dark_samples.append(p)
                elif 65 <= brightness <= 190 and diff > 25:
                    accent_samples.append(p)

        primary_color = "#1E293B"
        accent_color = "#609AAD"
        if dark_samples:
            most_c = Counter(dark_samples).most_common(1)[0][0]
            primary_color = f"#{most_c[0]:02X}{most_c[1]:02X}{most_c[2]:02X}"
        if accent_samples:
            most_acc = Counter(accent_samples).most_common(1)[0][0]
            accent_color = f"#{most_acc[0]:02X}{most_acc[1]:02X}{most_acc[2]:02X}"

        lines = []
        for y in range(int(h * 0.25), int(h * 0.75), 4):
            samples = [im.getpixel((x, y)) for x in range(int(w * 0.35), int(w * 0.65), 10)]
            dark_or_colored = [p for p in samples if (p[0] < 235 or p[1] < 235 or p[2] < 235)]
            if len(dark_or_colored) > len(samples) * 0.6:
                frac = (h - y) / h
                if not any(abs(frac - l) < 0.02 for l in lines):
                    lines.append(round(frac, 3))

        has_course_line = any(0.43 <= l <= 0.48 for l in lines)
        has_date_line = any(0.30 <= l <= 0.36 for l in lines)

        if has_course_line or has_date_line:
            return {
                "name_y_ratio": 0.558,
                "course_y_ratio": 0.466,
                "course_x_ratio": 0.562,
                "date_y_ratio": 0.334,
                "date_x_ratio": 0.585,
                "show_course": True,
                "show_date": True,
                "font_family": "sans",
                "primary_color": primary_color,
                "accent_color": accent_color,
                "mediabox_bottom": 0.0,
                "mediabox_left": 0.0,
            }

        return {
            "name_y_ratio": 0.515,
            "course_y_ratio": None,
            "course_x_ratio": None,
            "date_y_ratio": None,
            "date_x_ratio": None,
            "show_course": False,
            "show_date": False,
            "font_family": "sans",
            "primary_color": primary_color,
            "accent_color": accent_color,
            "mediabox_bottom": 0.0,
            "mediabox_left": 0.0,
        }
    except Exception:
        pass

    return {
        "name_y_ratio": 0.515,
        "course_y_ratio": None,
        "course_x_ratio": None,
        "date_y_ratio": None,
        "date_x_ratio": None,
        "show_course": False,
        "show_date": False,
        "font_family": "sans",
        "primary_color": "#1E293B",
        "accent_color": "#2E86AB",
        "mediabox_bottom": 0.0,
        "mediabox_left": 0.0,
    }
