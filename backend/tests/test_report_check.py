import asyncio

from app.services import report_check as rc
from app.services import report_writer as rw

SCAN = {"id": "abcdef12-0000", "filename": "scan.png", "patient_name": "Pat Example", "uploaded_at": "2026-10-06T09:00:00.000+00:00"}
REVIEW = {"final_class": "glioma", "size_mm": 23.0, "location": "left frontal lobe", "notes": None, "reviewer_name": "Dr Ada Reader"}


def build(body: str, summary_body: str | None = None, review: dict = REVIEW):
    fields = rw.review_fields(review)
    clinical = rw.assemble_clinical(SCAN, review, body)
    summary = rw.assemble_summary(summary_body or rw.template_summary(fields))
    return rc.summarise(rc.deterministic_rows(clinical, summary, fields, rw.fixed_text(SCAN, review)))


def codes(result) -> set[str]:
    return {i["code"] for i in result["issues"]}


def test_template_draft_passes_for_every_class():
    for cls in ("glioma", "meningioma", "pituitary", "no_tumor"):
        review = {**REVIEW, "final_class": cls}
        result = build(rw.template_clinical(rw.review_fields(review)), review=review)
        assert result["passed"], (cls, result["issues"])


def test_missing_fields_are_written_as_not_provided_and_pass():
    review = {**REVIEW, "size_mm": None, "location": None}
    body = rw.template_clinical(rw.review_fields(review))
    assert body.count(rw.NOT_PROVIDED) == 3  # size, location, notes: stated as missing, never guessed
    assert build(body, review=review)["passed"]


def test_the_writer_is_given_only_the_confirmed_fields():
    payload = rw._payload(rw.review_fields(REVIEW), "clinical")
    assert set(__import__("json").loads(payload)) == {"physician_confirmed_finding", "size", "location", "physician_notes"}
    assert "Never change the supplied finding" in rw.SYSTEM and "Never invent" in rw.SYSTEM


def test_different_tumor_type_is_a_contradiction():
    result = build("FINDINGS: A glioma is seen. Appearance could also suggest meningioma.\n\nIMPRESSION: glioma, 23 mm, left frontal lobe.")
    assert not result["passed"] and "CONTRADICTION" in codes(result)


def test_tumor_mention_in_a_no_tumor_report_is_a_contradiction():
    review = {**REVIEW, "final_class": "no_tumor", "size_mm": None, "location": None}
    result = build("FINDINGS: no tumor. A small pituitary adenoma cannot be excluded.\n\nIMPRESSION: no tumor.", review=review)
    assert "CONTRADICTION" in codes(result)


def test_invented_size_is_blocked():
    result = build("FINDINGS: glioma measuring 23 mm with a second 9 mm focus in the left frontal lobe.\n\nIMPRESSION: glioma.")
    assert not result["passed"]
    assert any(i["code"] == "INVENTED_DETAIL" and i["quote"] == "9" for i in result["issues"])


def test_size_in_cm_equivalent_is_allowed():
    assert build("FINDINGS: glioma, 2.3 cm, left frontal lobe.\n\nIMPRESSION: glioma.")["passed"]


def test_invented_location_is_blocked():
    result = build("FINDINGS: glioma 23 mm in the left frontal lobe extending to the right temporal lobe.\n\nIMPRESSION: glioma.")
    quotes = {i["quote"] for i in result["issues"] if i["code"] == "INVENTED_DETAIL"}
    assert {"right", "temporal"} <= quotes


def test_right_away_is_not_a_location():
    ok = build(rw.template_clinical(rw.review_fields(REVIEW)), summary_body="The radiologist saw a glioma. Please talk to your doctor right away.")
    assert ok["passed"], ok["issues"]


def test_invented_subtype_is_blocked():
    result = build("FINDINGS: glioma (glioblastoma) 23 mm left frontal lobe.\n\nIMPRESSION: glioma.")
    assert any(i["quote"] == "glioblastoma" and i["code"] == "INVENTED_DETAIL" for i in result["issues"])


def test_malignancy_prognosis_and_cleared_language_is_blocked():
    for phrase in ("likely malignant", "benign appearance", "poor prognosis", "WHO grade IV", "the patient is cleared", "high-grade"):
        result = build(f"FINDINGS: glioma 23 mm left frontal lobe, {phrase}.\n\nIMPRESSION: glioma.")
        assert "FORBIDDEN_PHRASE" in codes(result), phrase


def test_missing_confirmed_finding_is_blocked():
    result = build("FINDINGS: A mass of 23 mm in the left frontal lobe.\n\nIMPRESSION: mass.")
    assert "MISSING_FIELD" in codes(result)


def test_missing_ai_statement_is_blocked():
    fields = rw.review_fields(REVIEW)
    clinical = rw.assemble_clinical(SCAN, REVIEW, rw.template_clinical(fields)).replace(rc.REQUIRED_LINE, "")
    result = rc.summarise(rc.deterministic_rows(clinical, rw.assemble_summary(rw.template_summary(fields)), fields, rw.fixed_text(SCAN, REVIEW)))
    assert "MISSING_STATEMENT" in codes(result)


def test_patient_summary_is_checked_too():
    result = build(rw.template_clinical(rw.review_fields(REVIEW)), summary_body="You have a glioma and it is cancer. It is 40 mm.")
    where = {(i["where"], i["code"]) for i in result["issues"]}
    assert ("summary", "FORBIDDEN_PHRASE") in where and ("summary", "INVENTED_DETAIL") in where


def test_no_review_means_no_pass():
    result = rc.summarise(rc.deterministic_rows("anything", "anything", None))
    assert not result["passed"] and codes(result) == {"NO_REVIEW"}


def test_the_check_is_deterministic_only_and_never_consults_a_language_model():
    import inspect
    assert "qwen" not in inspect.signature(rc.run_check).parameters
    fields = rw.review_fields(REVIEW)
    clinical = rw.assemble_clinical(SCAN, REVIEW, rw.template_clinical(fields))

    async def go():
        return [r["id"] async for r in rc.run_check(clinical, rw.assemble_summary(rw.template_summary(fields)), fields, fixed_text=rw.fixed_text(SCAN, REVIEW))]
    assert asyncio.run(go()) == ["REVIEW", "TUMOR_TYPE", "MEASUREMENTS", "LOCATION", "LANGUAGE", "STATEMENTS"]


def test_report_number_and_stage_labels():
    assert rw.report_number("1a2b3c4d-0000-0000-0000-000000000000", "2026-10-06T10:00:00.000+00:00") == "NQ-20261006-1A2B3C"
    assert rw.report_stage(None) == "Draft"
    assert rw.report_stage({"status": "passed", "sources": {}}) == "AI-generated draft"
    assert rw.report_stage({"status": "passed", "sources": {"edited_by": "Dr A"}}) == "Under physician review"
    assert rw.report_stage({"status": "signed"}) == "Approved and finalized"


def test_live_guard_stops_the_stream_on_a_forbidden_phrase():
    class Leaky:
        async def stream(self, messages, **kw):
            for tok in ["FINDINGS: glioma ", "which is ", "malig", "nant ", "and more text"]:
                yield tok

    async def go():
        seen = []

        async def on_token(t):
            seen.append(t)
        try:
            await rw.write_section(Leaky(), "clinical", rw.review_fields(REVIEW), on_token)
        except rw.GuardTripped as g:
            return g.phrase, seen
        return None, seen

    phrase, seen = asyncio.run(go())
    assert phrase.lower().startswith("malignan") and "and more text" not in seen and "nant " not in seen
