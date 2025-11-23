# pdf_export.py
from io import BytesIO
import json
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
import re

# 根据空行和 1./2./3. 分段。
def split_into_paragraphs(text: str):
    lines = text.split("\n")

    paragraphs = []
    buffer = []

    for line in lines:
        stripped = line.strip()

        if stripped == "":
            if buffer:
                paragraphs.append(" ".join(buffer))
                buffer = []
            continue

        if re.match(r"^\d+\.\s", stripped):
            if buffer:
                paragraphs.append(" ".join(buffer))
                buffer = []
            paragraphs.append(stripped)
            continue

        buffer.append(stripped)

    if buffer:
        paragraphs.append(" ".join(buffer))

    return paragraphs


# 生成 PDF，返回 BytesIO。
# world_obj: 世界 JSON dict
# adventure_history: 冒险记录列表
# labels: PDF 内部标签（来自 PDF_LABELS）
def generate_pdf(world_obj, adventure_history, labels, lang_ui):
    buffer = BytesIO()

    # 注册中文字体
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm
    )

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.fontName = "STSong-Light"
    title_style = styles["Title"]
    title_style.fontName = "STSong-Light"

    story = []

    # 标题
    story.append(Paragraph(world_obj.get("title", "Untitled World"), title_style))
    story.append(Spacer(1, 10))

    # 世界简介
    story.append(Paragraph(f"<b>{labels['summary'][lang_ui]}</b>", normal))
    story.append(Paragraph(world_obj.get("summary", ""), normal))
    story.append(Spacer(1, 12))

    # 冒险记录
    story.append(Paragraph(f"<b>{labels['log'][lang_ui]}</b>", normal))
    story.append(Spacer(1, 8))

    for it in adventure_history:
        # Player
        story.append(Paragraph(f"<b>{labels['player'][lang_ui]}:</b>", normal))
        player_paras = split_into_paragraphs(str(it["player"]))
        for p in player_paras:
            story.append(Paragraph(p, normal))
            story.append(Spacer(1, 4))

        # DM
        story.append(Paragraph(f"<b>{labels['dm'][lang_ui]}:</b>", normal))
        dm_paras = split_into_paragraphs(str(it["dm"]))
        for p in dm_paras:
            story.append(Paragraph(p, normal))
            story.append(Spacer(1, 4))

        story.append(Spacer(1, 8))

    doc.build(story)
    buffer.seek(0)
    return buffer

