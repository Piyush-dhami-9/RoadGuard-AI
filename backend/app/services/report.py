from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from .images import stored_file

MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT = 480, 320
DISCLAIMER = (
    "Severity and priority are estimated indicators derived from image-space (pixel) measurements. "
    "They are not calibrated physical dimensions and not a certified engineering assessment."
)


def provenance_banner(inspection) -> tuple[str, colors.Color]:
    if inspection.inference_mode == "trained":
        return f"TRAINED MODEL: {escape(inspection.model_name or 'unnamed')} (version {escape(inspection.model_version or 'unrecorded')})", colors.HexColor("#1f7a5a")
    if inspection.inference_mode == "demo":
        return "DEMO MODE: produced by a brightness-threshold placeholder detector. These are NOT AI predictions and must not be used for decisions.", colors.HexColor("#b3261e")
    return "DETECTOR NOT RECORDED: this inspection predates provenance tracking; treat its results as unverified.", colors.HexColor("#8a6100")


def create_report(inspection) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42, title=f"RoadGuard inspection {inspection.id}")
    styles = getSampleStyleSheet()
    banner_text, banner_color = provenance_banner(inspection)
    banner = Table([[Paragraph(f'<font color="white"><b>{banner_text}</b></font>', styles["Normal"])]], colWidths=[MAX_IMAGE_WIDTH])
    banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), banner_color), ("PADDING", (0, 0), (-1, -1), 8)]))
    story = [Paragraph("ROADGUARD AI", styles["Title"]), Paragraph(f"Inspection #{inspection.id}  |  {inspection.timestamp:%B %d, %Y %H:%M} UTC", styles["Normal"]), Spacer(1, 12), banner, Spacer(1, 14)]
    image_path = stored_file(inspection.annotated_image_path)
    if image_path is not None:
        try:
            width, height = ImageReader(str(image_path)).getSize()
            scale = min(MAX_IMAGE_WIDTH / width, MAX_IMAGE_HEIGHT / height)
            story += [Image(str(image_path), width=width * scale, height=height * scale), Spacer(1, 14)]
        except Exception:
            image_path = None
    if image_path is None:
        story += [Paragraph("<i>The annotated image is no longer available on the server.</i>", styles["Normal"]), Spacer(1, 14)]
    story.append(Paragraph(f"Estimated severity: <b>{escape(inspection.overall_severity)}</b> &nbsp; Repair priority: <b>{inspection.priority_score:.0f}/100</b>", styles["Heading2"]))
    if inspection.damages:
        data = [["Damage", "Confidence", "Region area (image px)", "Severity"]] + [[d.class_name, f"{d.confidence:.0%}", f"{d.area:.0f}", d.severity] for d in inspection.damages]
        table = Table(data, colWidths=[170, 90, 130, 90])
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123047")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe4ea")), ("PADDING", (0, 0), (-1, -1), 8)]))
        story += [Spacer(1, 12), table]
    else:
        story += [Spacer(1, 12), Paragraph("No damage regions were detected in this image.", styles["Normal"])]
    story += [Spacer(1, 16), Paragraph(f"<i>{DISCLAIMER}</i>", styles["Normal"])]
    document.build(story)
    return buffer.getvalue()
