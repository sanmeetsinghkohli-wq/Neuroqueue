"""Official finalized-report PDF (ReportLab).

Layout: branded header, report ID and status, patient information, examination
details, AI-assisted classification with the full probability table, the
physician-approved clinical report, physician review and approval block,
patient summary, model information and disclaimer.

Everything printed here comes from stored records. Anything that was never
recorded is printed as "Not provided".
"""
from __future__ import annotations

import io
from datetime import date, datetime
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import CLASS_LABELS, CLASSES

BRAND, STRIPE = colors.HexColor("#0e7490"), colors.HexColor("#38bdf8")
INK, MUTED, RULE, PALE, TINT = colors.HexColor("#0f172a"), colors.HexColor("#64748b"), colors.HexColor("#cbd5e1"), colors.HexColor("#f1f5f9"), colors.HexColor("#ecfeff")
W = 174 * mm
NP = "Not provided"


def _styles():
    b = getSampleStyleSheet()["Normal"]
    mk = lambda name, **kw: ParagraphStyle(name, parent=b, **kw)  # noqa: E731
    return {
        "brand": mk("brand", fontName="Helvetica-Bold", fontSize=19, textColor=BRAND, leading=22),
        "sub": mk("sub", fontSize=8.5, textColor=MUTED, leading=11),
        "meta": mk("meta", fontSize=8.5, textColor=INK, leading=11, alignment=2),
        "sec": mk("sec", fontName="Helvetica-Bold", fontSize=10.5, textColor=INK, leading=13),
        "k": mk("k", fontName="Helvetica-Bold", fontSize=8.5, textColor=INK, leading=11),
        "v": mk("v", fontSize=8.5, textColor=INK, leading=11),
        "body": mk("body", fontSize=9.5, textColor=INK, leading=14),
        "small": mk("small", fontSize=7.8, textColor=MUTED, leading=10.5),
        "big_k": mk("big_k", fontName="Helvetica-Bold", fontSize=8.5, textColor=INK, leading=11),
        "big_v": mk("big_v", fontName="Helvetica-Bold", fontSize=15, textColor=BRAND, leading=18),
        "th": mk("th", fontName="Helvetica-Bold", fontSize=8.5, textColor=colors.white, leading=11),
        "status": mk("status", fontName="Helvetica-Bold", fontSize=10, textColor=BRAND, leading=13),
    }


def _section(title: str, st) -> Table:
    t = Table([[Paragraph(title, st["sec"])]], colWidths=[W])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, BRAND), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
    return t


def _kv(rows: list[list[tuple[str, str]]], st) -> Table:
    """Label/value grid, two pairs per row."""
    data = [[c for k, v in row for c in (Paragraph(escape(k), st["k"]), Paragraph(escape(str(v) if v not in (None, "") else NP), st["v"]))] for row in rows]
    t = Table(data, colWidths=[30 * mm, 57 * mm, 30 * mm, 57 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, RULE), ("BACKGROUND", (0, 0), (0, -1), PALE), ("BACKGROUND", (2, 0), (2, -1), PALE),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def _bar(p: float) -> Table:
    full = 46 * mm
    w = max(0.01, min(1.0, p)) * full
    t = Table([["", ""]], colWidths=[w, full - w + 0.01], rowHeights=[3 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), BRAND), ("BACKGROUND", (1, 0), (1, 0), PALE),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _thumb(image: bytes | None):
    if not image:
        return None
    try:
        im = PILImage.open(io.BytesIO(image)).convert("RGB")
        im.thumbnail((420, 420))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        w = 44 * mm
        return Image(buf, width=w, height=w * im.size[1] / im.size[0])
    except Exception:
        return None


def _age(scan: dict, patient: dict | None) -> str:
    if scan.get("patient_age"):
        return f"{scan['patient_age']} years"
    try:
        dob = date.fromisoformat((patient or {}).get("date_of_birth") or "")
        today = date.today()
        return f"{today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))} years"
    except ValueError:
        return NP


def _when(iso: str | None, with_time: bool = True) -> str:
    if not iso:
        return NP
    d = datetime.fromisoformat(iso)
    return d.strftime("%B %d, %Y at %H:%M UTC" if with_time else "%B %d, %Y")


def _text(text: str, st) -> list:
    out = []
    for block in text.split("\n\n"):
        if block.strip():
            out += [Paragraph(escape(block.strip()).replace("\n", "<br/>"), st), Spacer(1, 5)]
    return out


def build_pdf(*, scan: dict, report: dict, doctor: dict, patient: dict | None, signed_at: str, audit_hash: str | None,
              image: bytes | None, model_metrics: dict | None = None) -> bytes:
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=26 * mm, bottomMargin=20 * mm,
                            title=f"NeuroQueue report {report.get('report_no', '')}", author=doctor.get("full_name", ""))
    pred, rev = scan.get("prediction") or {}, scan.get("review") or {}
    report_no = report.get("report_no") or str(report.get("id", ""))[:8].upper()
    patient_id = f"PT-{scan['patient_id'].replace('-', '')[:8].upper()}" if scan.get("patient_id") else NP

    head = Table([[[Paragraph("NEUROQUEUE", st["brand"]), Paragraph("AI-Assisted Brain MRI Report: Clinical Version", st["sub"]),
                    Paragraph("Department of Radiology &amp; Medical Imaging", st["sub"])],
                   [Paragraph(f"<b>REPORT ID:</b> {escape(report_no)}", st["meta"]), Paragraph(f"<b>DATE:</b> {_when(signed_at, False)}", st["meta"]),
                    Paragraph("<b>STATUS:</b> APPROVED AND FINALIZED", st["meta"])]]], colWidths=[W * 0.55, W * 0.45])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story = [head, Spacer(1, 10)]

    story += [_section("PATIENT INFORMATION", st), _kv([
        [("Patient Name:", scan.get("patient_name")), ("Age:", _age(scan, patient))],
        [("Patient ID:", patient_id), ("Gender:", scan.get("patient_gender") or (patient or {}).get("gender"))],
        [("Email:", (patient or {}).get("email")), ("Date of Birth:", (patient or {}).get("date_of_birth"))],
    ], st), Spacer(1, 9)]

    story += [_section("EXAMINATION DETAILS", st), _kv([
        [("Examination:", scan.get("exam_type") or "MRI Brain"), ("Examination Date:", _when(scan.get("uploaded_at")))],
        [("Referring Doctor:", scan.get("referring_doctor")), ("Image File:", scan.get("filename"))],
        [("Clinical Concern:", scan.get("clinical_concern")), ("Scan ID:", str(scan.get("id", ""))[:8])],
    ], st), Spacer(1, 9)]

    # --- AI-assisted classification: printed straight from the stored model result ---
    if pred:
        box = Table([[Paragraph("AI MODEL CLASSIFICATION:", st["big_k"]), Paragraph("MODEL CONFIDENCE:", st["big_k"])],
                     [Paragraph(escape(CLASS_LABELS[pred["top_class"]].upper()), st["big_v"]), Paragraph(f"{pred['top_prob'] * 100:.1f}%", st["big_v"])]],
                    colWidths=[W * 0.6, W * 0.4])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, BRAND), ("BACKGROUND", (0, 0), (-1, -1), TINT), ("LEFTPADDING", (0, 0), (-1, -1), 9),
                                 ("TOPPADDING", (0, 0), (-1, 0), 7), ("BOTTOMPADDING", (0, 1), (-1, 1), 9)]))
        rows = [[Paragraph("Classification", st["th"]), Paragraph("Probability", st["th"]), Paragraph("Level", st["th"])]]
        for c in CLASSES:
            rows.append([Paragraph(CLASS_LABELS[c], st["v"]), Paragraph(f"{pred['probs'][c] * 100:.2f}%", st["v"]), _bar(pred["probs"][c])])
        thumb = _thumb(image)
        pw = W - (50 * mm if thumb else 0)
        probs = Table(rows, colWidths=[pw - 76 * mm, 24 * mm, 52 * mm])
        probs.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BRAND), ("GRID", (0, 0), (-1, -1), 0.5, RULE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                   ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PALE, colors.white]), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story += [_section("AI-ASSISTED CLASSIFICATION", st), box, Spacer(1, 7), Paragraph("<b>DETAILED CLASSIFICATION PROBABILITIES:</b>", st["k"]), Spacer(1, 4)]
        if thumb:
            side = Table([[probs, [thumb, Paragraph("Examined image", st["small"])]]], colWidths=[pw, 50 * mm])
            side.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 0), ("LEFTPADDING", (1, 0), (1, 0), 6 * mm)]))
            story.append(side)
        else:
            story.append(probs)
        story.append(Spacer(1, 9))

    # --- physician-approved clinical report ---
    final = CLASS_LABELS.get(rev.get("final_class"), NP)
    agree = rev.get("decision") == "confirm"
    story += [_section("CLINICAL REPORT (PHYSICIAN APPROVED)", st), Spacer(1, 5),
              Paragraph(f"<b>Physician-confirmed finding:</b> {escape(final)}"
                        + ("" if agree else f" (the physician overrode the AI classification. Reason: {escape(rev.get('override_reason') or NP)})"), st["body"]),
              Spacer(1, 5)] + _text(report["clinical_text"], st["body"]) + [Spacer(1, 6)]

    def _or_np(v):
        return escape((v or "").strip() or NP).replace("\n", "<br/>")

    info = Table([[Paragraph(k, st["k"]), Paragraph(_or_np(v), st["v"])] for k, v in (
        ("Chief Complaint / Reason:", scan.get("clinical_concern")), ("Symptoms:", rev.get("symptoms")),
        ("Relevant History:", rev.get("history")), ("Clinical Notes:", rev.get("notes")))], colWidths=[42 * mm, W - 42 * mm])
    info.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, RULE), ("BACKGROUND", (0, 0), (0, -1), PALE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story.append(KeepTogether([_section("CLINICAL INFORMATION", st), info, Spacer(1, 9)]))

    plan = Table([[Paragraph(k, st["k"]), Paragraph(_or_np(v), st["v"])] for k, v in (
        ("Treatment Plan:", rev.get("treatment_plan")), ("Follow-Up:", rev.get("follow_up")),
        ("Instructions Given to Patient:", rev.get("patient_instructions")), ("Warning Signs Advised:", rev.get("warning_signs")))], colWidths=[42 * mm, W - 42 * mm])
    plan.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, RULE), ("BACKGROUND", (0, 0), (0, -1), PALE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    blocks = [_section("TREATMENT PLAN AND FOLLOW-UP", st), plan]
    meds = [m for m in (rev.get("medications") or []) if (m.get("name") or "").strip()]
    if meds:
        rows = [[Paragraph(h, st["th"]) for h in ("Medication", "Indication", "How", "When", "Duration", "Instructions")]]
        for m in meds:
            rows.append([Paragraph(_or_np(m.get(k)), st["v"]) for k in ("name", "purpose", "how_to_take", "when_to_take", "duration", "instructions")])
        mt = Table(rows, colWidths=[30 * mm, 30 * mm, 26 * mm, 26 * mm, 22 * mm, 40 * mm])
        mt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BRAND), ("GRID", (0, 0), (-1, -1), 0.5, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PALE, colors.white]), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        blocks += [Spacer(1, 6), Paragraph("<b>MEDICATIONS:</b>", st["k"]), Spacer(1, 3), mt]
    else:
        blocks += [Spacer(1, 4), Paragraph("<b>Medications:</b> None recorded.", st["v"])]
    story.append(KeepTogether(blocks + [Spacer(1, 9)]))

    review_rows = _kv([
        [("Reviewed By:", doctor.get("full_name")), ("Report Status:", "Approved and finalized")],
        [("Credentials:", doctor.get("specialty")), ("Licence No.:", doctor.get("license_no"))],
        [("Institution:", doctor.get("hospital")), ("Approval Date:", _when(signed_at))],
        [("Decision:", "Confirmed the AI classification" if agree else "Overrode the AI classification"), ("Signature:", f"Electronically signed by {report.get('signed_by_name') or doctor.get('full_name', '')}")],
    ], st)
    story.append(KeepTogether([_section("PHYSICIAN REVIEW AND APPROVAL", st), review_rows, Spacer(1, 9)]))

    t = (model_metrics or {}).get("test")
    model_line = (f"Classification model: {pred.get('model', NP)} ({pred.get('model_version') or 'version not recorded'}). "
                  + (f"On {t['n']} held-out test images from the public dataset it was trained on, the model reached {t['accuracy'] * 100:.1f}% accuracy "
                     f"({t['tumor_vs_no_tumor']['tumor_recall'] * 100:.1f}% tumor recall). " if t else "")
                  + "The classification above is the model's output and was not altered by any language model.")
    story.append(KeepTogether([
        _section("AI MODEL INFORMATION AND IMPORTANT DISCLAIMER", st), Spacer(1, 5), Paragraph(escape(model_line), st["small"]), Spacer(1, 4),
        Paragraph("This AI-assisted report is intended for clinical decision support and does not replace professional medical judgment. "
                  "The AI classification is not a definitive diagnosis. The model was built on public 2D MRI images from a single dataset, does not use "
                  "patient history, and its performance on other scanners is unknown. Results should be interpreted together with the patient's history, "
                  "symptoms and other clinical findings. The physician named above reviewed and approved this report.", st["small"]),
    ] + ([Spacer(1, 4), Paragraph(f"Audit chain entry for this approval: {audit_hash}", st["small"])] if audit_hash else [])))

    def page(canvas, d):
        canvas.saveState()
        canvas.setFillColor(BRAND)
        canvas.rect(0, A4[1] - 15 * mm, A4[0], 15 * mm, stroke=0, fill=1)
        canvas.setFillColor(STRIPE)
        canvas.rect(0, A4[1] - 16.5 * mm, A4[0], 1.5 * mm, stroke=0, fill=1)
        canvas.setStrokeColor(BRAND)
        canvas.setLineWidth(1)
        canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.drawString(18 * mm, 11 * mm, "CONFIDENTIAL MEDICAL REPORT")
        canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, f"Finalized: {_when(signed_at)}")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(18 * mm, 7.5 * mm, f"NeuroQueue | Clinical report for medical professionals | Report {report_no} | AI-assisted triage was used.")
        canvas.drawRightString(A4[0] - 18 * mm, 7.5 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=page, onLaterPages=page)
    return buf.getvalue()


def build_patient_pdf(*, scan: dict, report: dict, patient: dict | None) -> bytes:
    """The patient version: built from services/patient_report.py, never from the clinical report text.
    No probabilities, tiers, model details or the doctor's clinical notes appear here."""
    from app.services.patient_report import build_patient_report

    pr = build_patient_report(scan, report)
    st = _styles()
    big = ParagraphStyle("p_big", parent=st["body"], fontSize=11, leading=16.5)
    h = ParagraphStyle("p_h", parent=st["sec"], fontSize=12.5, textColor=BRAND, spaceBefore=4, spaceAfter=3)
    title = ParagraphStyle("p_title", parent=st["brand"], fontSize=22, leading=26)
    headline = ParagraphStyle("p_headline", parent=st["big_v"], fontSize=18, leading=22)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=26 * mm, bottomMargin=20 * mm,
                            title="Your MRI report", author=pr.get("doctor") or "")
    width = A4[0] - 40 * mm
    name = scan.get("patient_name") or (patient or {}).get("full_name") or "Patient"
    story = [Paragraph("Your MRI Report", title), Paragraph("A plain-language summary prepared for you and approved by your doctor", st["sub"]), Spacer(1, 8)]
    facts = Table([[Paragraph("<b>Prepared for</b><br/>" + escape(name), st["v"]), Paragraph("<b>Your doctor</b><br/>" + escape(pr.get("doctor") or NP), st["v"]),
                    Paragraph("<b>Examination date</b><br/>" + _when(pr.get("exam_date"), False), st["v"]), Paragraph("<b>Report ID</b><br/>" + escape(pr.get("report_no") or NP), st["v"])]],
                  colWidths=[width / 4] * 4)
    facts.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE), ("BOX", (0, 0), (-1, -1), 0.5, RULE), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [facts, Spacer(1, 10)]

    for sec in pr["sections"]:
        block = [Paragraph(escape(sec["title"]), h)]
        if sec.get("headline"):
            box = Table([[Paragraph(escape(sec["headline"]), headline)]], colWidths=[width])
            box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TINT), ("BOX", (0, 0), (-1, -1), 1.2, BRAND), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                     ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
            block += [box, Spacer(1, 5)]
        if sec.get("text"):
            if sec.get("from_doctor"):
                block.append(Paragraph("<i>In your doctor's words:</i>", st["small"]))
            for para in sec["text"].split("\n\n"):
                if para.strip():
                    block += [Paragraph(escape(para.strip()).replace("\n", "<br/>"), big), Spacer(1, 4)]
        for f in sec.get("facts") or []:
            block.append(Paragraph("&bull; " + escape(f), big))
        for item in sec.get("items") or []:
            block.append(Paragraph("&bull; " + escape(item), big))
        for m in sec.get("medicines") or []:
            rows = [[Paragraph("<b>" + escape(m["name"]) + "</b>", big), ""]] + [[Paragraph(escape(d["label"]), st["k"]), Paragraph(escape(d["value"]), st["body"])] for d in m["details"]]
            mt = Table(rows, colWidths=[45 * mm, width - 45 * mm])
            mt.setStyle(TableStyle([("SPAN", (0, 0), (-1, 0)), ("BACKGROUND", (0, 0), (-1, 0), TINT), ("GRID", (0, 0), (-1, -1), 0.5, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("BACKGROUND", (0, 1), (0, -1), PALE), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            block += [mt, Spacer(1, 6)]
        story.append(KeepTogether(block + [Spacer(1, 7)]))

    story.append(Paragraph("This summary was written to be easy to read. It does not replace a conversation with your doctor. "
                           "A computer program assisted with the first reading of the scan; your doctor reviewed the images and approved this report on "
                           + _when(pr.get("signed_at")) + ".", st["small"]))

    def page(canvas, d):
        canvas.saveState()
        canvas.setFillColor(BRAND)
        canvas.rect(0, A4[1] - 15 * mm, A4[0], 15 * mm, stroke=0, fill=1)
        canvas.setFillColor(STRIPE)
        canvas.rect(0, A4[1] - 16.5 * mm, A4[0], 1.5 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawString(20 * mm, A4[1] - 9.5 * mm, "NEUROQUEUE")
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 9.5 * mm, "Patient copy")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(20 * mm, 9 * mm, f"Confidential. Prepared for {name}. Report {pr.get('report_no') or ''}")
        canvas.drawRightString(A4[0] - 20 * mm, 9 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=page, onLaterPages=page)
    return buf.getvalue()
