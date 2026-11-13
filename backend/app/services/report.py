from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from ..core.config import settings


def create_report(inspection) -> Path:
    path = settings.report_dir / f"inspection-{inspection.id}.pdf"
    document = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42)
    styles = getSampleStyleSheet()
    story = [Paragraph("ROADGUARD AI", styles["Title"]), Paragraph(f"Inspection #{inspection.id}  |  {inspection.timestamp:%B %d, %Y %H:%M}", styles["Normal"]), Spacer(1, 18)]
    if Path(inspection.annotated_image_path or "").exists():
        story.append(Image(inspection.annotated_image_path, width=480, height=300))
        story.append(Spacer(1, 14))
    story.append(Paragraph(f"Overall severity: <b>{inspection.overall_severity}</b> &nbsp; Priority: <b>{inspection.priority_score}/100</b>", styles["Heading2"]))
    data = [["Damage", "Confidence", "Area", "Severity"]] + [[d.class_name, f"{d.confidence:.0%}", f"{d.area:.0f} px²", d.severity] for d in inspection.damages]
    table = Table(data, colWidths=[190, 100, 100, 90])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123047")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe4ea")), ("PADDING", (0, 0), (-1, -1), 8)]))
    story += [Spacer(1, 12), table]
    document.build(story)
    return path
