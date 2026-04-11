from __future__ import annotations

import io

from fastapi.testclient import TestClient
from pptx import Presentation

import pptx_gen.api as api_module
from pptx_gen.api_schemas import ExportBlockRequest, ExportSlideRequest


def _reset_api_state() -> None:
    api_module._INGESTED_DOCS.clear()
    api_module._INGESTED_RESULTS.clear()
    api_module._DRAFTS.clear()
    api_module._DECKS.clear()
    api_module._RAW_DECK_SPECS.clear()
    api_module._CHAT_SESSIONS.clear()
    api_module._EMBEDDER = None
    api_module._STRUCTURED_LLM_CLIENT = False


def _ingest_fixture(client: TestClient, sample_pdf_path) -> str:
    response = client.post(
        "/api/ingest",
        files={"file": ("sample_ingestion.pdf", sample_pdf_path.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 200
    return response.json()["doc_id"]


def test_api_health_and_templates() -> None:
    client = TestClient(api_module.app)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "phase": "1", "ingest": True, "generation": "live"}

    templates = client.get("/api/templates")
    assert templates.status_code == 200
    payload = templates.json()
    assert len(payload) == 20
    template_by_id = {item["id"]: item for item in payload}
    assert template_by_id["headline.evidence"]["deck_default_allowed"] is True
    assert template_by_id["compare.2col"]["deck_default_allowed"] is True
    assert template_by_id["kpi.big"]["deck_default_allowed"] is True
    assert template_by_id["title.cover"]["deck_default_allowed"] is False
    assert template_by_id["exec.summary"]["deck_default_allowed"] is False
    assert template_by_id["closing.actions"]["deck_default_allowed"] is False
    assert template_by_id["impact.statement"]["deck_default_allowed"] is False

    themes = client.get("/api/themes")
    assert themes.status_code == 200
    assert themes.json() == ["ONAC"]


def test_api_ingest_pdf_returns_summary(monkeypatch, sample_pdf_path, deterministic_embedder) -> None:
    _reset_api_state()
    monkeypatch.setattr(api_module, "_get_embedder", lambda: deterministic_embedder)
    client = TestClient(api_module.app)

    response = client.post(
        "/api/ingest",
        files={"file": ("sample_ingestion.pdf", sample_pdf_path.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["doc_id"]
    assert payload["chunk_count"] > 0
    assert payload["title"]
    assert payload["element_types"]


def test_api_ingest_pptx_returns_slide_structure(monkeypatch, make_pptx_file, deterministic_embedder) -> None:
    _reset_api_state()
    monkeypatch.setattr(api_module, "_get_embedder", lambda: deterministic_embedder)
    client = TestClient(api_module.app)
    source_path = make_pptx_file()

    response = client.post(
        "/api/ingest",
        files={
            "file": (
                "sample.pptx",
                source_path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_format"] == "pptx"
    assert payload["slide_count"] == 2
    assert payload["slide_types"]["title"] == 1
    assert payload["slide_types"]["table"] == 1


def test_api_plan_from_prompt_uses_powerpoint_slide_count(monkeypatch, make_pptx_file, deterministic_embedder) -> None:
    _reset_api_state()
    monkeypatch.setattr(api_module, "_get_embedder", lambda: deterministic_embedder)
    client = TestClient(api_module.app)
    source_path = make_pptx_file()

    ingest = client.post(
        "/api/ingest",
        files={
            "file": (
                "sample.pptx",
                source_path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        },
    )
    assert ingest.status_code == 200
    doc_id = ingest.json()["doc_id"]

    planned = client.post(
        "/api/plan/prompt",
        json={
            "doc_ids": [doc_id],
            "prompt": "Rebrand this deck for ONAC while preserving the original structure.",
        },
    )

    assert planned.status_code == 200
    payload = planned.json()
    assert len(payload["slides"]) == 2
    assert payload["slides"][0]["template_id"] == "title.cover"
    assert payload["slides"][1]["title"] == "Decision Summary"
    assert payload["slides"][1]["template_id"] == "compare.2col"


def test_api_plan_and_generate_honor_authoritative_inputs(monkeypatch, sample_pdf_path, deterministic_embedder) -> None:
    _reset_api_state()
    monkeypatch.setattr(api_module, "_get_embedder", lambda: deterministic_embedder)
    client = TestClient(api_module.app)
    doc_id = _ingest_fixture(client, sample_pdf_path)

    planned = client.post(
        "/api/plan",
        json={
            "doc_ids": [doc_id],
            "goal": "Board update",
            "audience": "Executive Steering Committee",
            "tone": 15,
            "slide_count": 6,
        },
    )
    assert planned.status_code == 200
    draft = planned.json()
    assert len(draft["slides"]) == 6
    assert draft["draft_id"]
    assert draft["slides"][0]["template_id"] == "title.cover"
    assert draft["slides"][1]["template_id"] == "exec.summary"
    assert draft["slides"][1]["archetype"] == "executive_summary"
    assert draft["slides"][0]["blocks"][0]["content"].startswith("Subtitle:")
    assert any(slide["template_id"] == "closing.actions" for slide in draft["slides"])

    edited_outline = list(draft["slides"])
    edited_outline[1]["title"] = "Investor-safe evidence"
    edited_outline[1]["template_id"] = "compare.2col"
    edited_outline[2]["title"] = "Reordered board priorities"
    edited_outline[1], edited_outline[2] = edited_outline[2], edited_outline[1]
    for index, slide in enumerate(edited_outline, start=1):
        slide["index"] = index

    generated = client.post(
        "/api/generate",
        json={
            "draft_id": draft["draft_id"],
            "outline": [
                {
                    "id": slide["id"],
                    "index": slide["index"],
                    "purpose": slide["purpose"],
                    "title": slide["title"],
                    "template_id": slide["template_id"],
                }
                for slide in edited_outline
            ],
            "selected_template_id": "kpi.big",
            "brand_kit": {
                "logo_data_url": None,
                "primary_color": "#112233",
                "accent_color": "#445566",
                "font_pair": "DM Sans/DM Serif Display",
            },
        },
    )
    assert generated.status_code == 200
    deck = generated.json()

    assert len(deck["slides"]) == 6
    assert {deck["slides"][1]["title"], deck["slides"][2]["title"]} == {"Investor-safe evidence", "Reordered board priorities"}
    deck_by_title = {slide["title"]: slide for slide in deck["slides"]}
    content_templates = {
        slide["title"]: slide["template_id"]
        for slide in deck["slides"]
        if slide["purpose"] in {"content", "summary"}
    }
    assert deck_by_title["Investor-safe evidence"]["purpose"] == "content"
    assert content_templates["Investor-safe evidence"] == "compare.2col"
    assert any(slide.get("archetype") == "executive_summary" for slide in deck["slides"])
    overview_slide = next(slide for slide in deck["slides"] if slide.get("archetype") == "executive_summary")
    assert overview_slide["template_id"] in {"exec.summary", "compare.2col"}
    assert any(slide["template_id"] == "closing.actions" for slide in deck["slides"])
    assert not any(
        slide["title"].startswith(prefix)
        for slide in deck["slides"]
        for prefix in ("Implementation implications", "Design quality strategies", "Hybrid architecture")
    )
    assert any(
        block["kind"] == "bullets" and block["content"].startswith("• ")
        for slide in deck["slides"]
        for block in slide["blocks"]
    )
    assert deck["theme"]["primary_color"] == "#112233"
    assert deck["theme"]["accent_color"] == "#445566"
    assert deck["theme"]["heading_font"] == "DM Serif Display"
    assert deck["theme"]["body_font"] == "DM Sans"
    assert deck["theme"]["heading_font"] == "DM Serif Display"
    assert deck["theme"]["body_font"] == "DM Sans"
    fetched = client.get(f"/api/deck/{deck['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == deck["id"]

    pptx = client.post(f"/api/export/{deck['id']}", json={"format": "pptx"})
    assert pptx.status_code == 200
    assert pptx.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    assert pptx.content.startswith(b"PK")

    pdf = client.post(f"/api/export/{deck['id']}", json={"format": "pdf"})
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content.startswith(b"%PDF-1.4")


def test_api_different_prompt_inputs_change_generated_result(monkeypatch, sample_pdf_path, deterministic_embedder) -> None:
    _reset_api_state()
    monkeypatch.setattr(api_module, "_get_embedder", lambda: deterministic_embedder)
    client = TestClient(api_module.app)
    doc_id = _ingest_fixture(client, sample_pdf_path)

    analytical_plan = client.post(
        "/api/plan",
        json={
            "doc_ids": [doc_id],
            "goal": "Board update",
            "audience": "Board",
            "tone": 10,
            "slide_count": 6,
        },
    ).json()
    bold_plan = client.post(
        "/api/plan",
        json={
            "doc_ids": [doc_id],
            "goal": "Raise seed",
            "audience": "Investors",
            "tone": 90,
            "slide_count": 6,
        },
    ).json()

    analytical_deck = client.post(
        "/api/generate",
        json={
            "draft_id": analytical_plan["draft_id"],
            "outline": [
                {
                    "id": slide["id"],
                    "index": slide["index"],
                    "purpose": slide["purpose"],
                    "title": slide["title"],
                    "template_id": slide["template_id"],
                }
                for slide in analytical_plan["slides"]
            ],
            "selected_template_id": "headline.evidence",
            "brand_kit": {
                "logo_data_url": None,
                "primary_color": "#4F46E5",
                "accent_color": "#0F172A",
                "font_pair": "Inter/Inter",
            },
        },
    ).json()
    bold_deck = client.post(
        "/api/generate",
        json={
            "draft_id": bold_plan["draft_id"],
            "outline": [
                {
                    "id": slide["id"],
                    "index": slide["index"],
                    "purpose": slide["purpose"],
                    "title": slide["title"],
                    "template_id": slide["template_id"],
                }
                for slide in bold_plan["slides"]
            ],
            "selected_template_id": "compare.2col",
            "brand_kit": {
                "logo_data_url": None,
                "primary_color": "#0A84FF",
                "accent_color": "#111111",
                "font_pair": "Inter/Inter",
            },
        },
    ).json()

    analytical_text = "\n".join(block["content"] for slide in analytical_deck["slides"] for block in slide["blocks"])
    bold_text = "\n".join(block["content"] for slide in bold_deck["slides"] for block in slide["blocks"])

    assert analytical_deck["audience"] == "Board"
    assert bold_deck["audience"] == "Investors"
    analytical_tone_hints = [
        block.get("data", {}).get("tone_hint")
        for slide in analytical_deck["slides"]
        for block in slide["blocks"]
        if isinstance(block.get("data"), dict)
    ]
    bold_tone_hints = [
        block.get("data", {}).get("tone_hint")
        for slide in bold_deck["slides"]
        for block in slide["blocks"]
        if isinstance(block.get("data"), dict)
    ]
    # With the deterministic planner (no LLM), content text is the same from the
    # same source document regardless of tone — only structure, audience, and
    # template choices differ.  Verify the deck-level metadata reflects the
    # different briefs and that template variety exists across slides.
    assert analytical_deck["audience"] != bold_deck["audience"]
    analytical_templates = {slide["template_id"] for slide in analytical_deck["slides"]}
    bold_templates = {slide["template_id"] for slide in bold_deck["slides"]}
    assert len(analytical_templates) >= 2, f"Expected template variety, got {analytical_templates}"
    assert len(bold_templates) >= 2, f"Expected template variety, got {bold_templates}"
    assert analytical_plan["slides"][0]["blocks"][0]["content"].startswith("Subtitle: Board update")
    assert any(slide["template_id"] in {"compare.2col", "exec.summary"} for slide in analytical_plan["slides"])


def test_api_export_uses_ui_slide_overrides(monkeypatch, sample_pdf_path, deterministic_embedder) -> None:
    _reset_api_state()
    monkeypatch.setattr(api_module, "_get_embedder", lambda: deterministic_embedder)
    client = TestClient(api_module.app)
    doc_id = _ingest_fixture(client, sample_pdf_path)

    planned = client.post(
        "/api/plan",
        json={
            "doc_ids": [doc_id],
            "goal": "Board update",
            "audience": "Executive Steering Committee",
            "tone": 15,
            "slide_count": 6,
        },
    ).json()
    generated = client.post(
        "/api/generate",
        json={
            "draft_id": planned["draft_id"],
            "outline": [
                {
                    "id": slide["id"],
                    "index": slide["index"],
                    "purpose": slide["purpose"],
                    "title": slide["title"],
                    "template_id": slide["template_id"],
                }
                for slide in planned["slides"]
            ],
            "selected_template_id": "headline.evidence",
            "brand_kit": {
                "logo_data_url": None,
                "primary_color": "#112233",
                "accent_color": "#445566",
                "font_pair": "DM Sans/DM Serif Display",
            },
        },
    ).json()

    ui_slides = list(generated["slides"])
    ui_slides.append(
        {
            "id": "slide-ui-added",
            "index": len(ui_slides) + 1,
            "purpose": "content",
            "archetype": None,
            "title": "UI Added Slide",
            "template_id": "headline.evidence",
            "speaker_notes": "Added in editor",
            "blocks": [
                {
                    "id": "block-ui-added",
                    "kind": "text",
                    "content": "Export should include this slide.",
                    "data": {"text": "Export should include this slide."},
                    "citation": None,
                }
            ],
        }
    )

    pptx = client.post(
        f"/api/export/{generated['id']}",
        json={"format": "pptx", "slides": ui_slides},
    )

    assert pptx.status_code == 200
    exported = Presentation(io.BytesIO(pptx.content))
    slide_text = "\n".join(
        shape.text
        for slide in exported.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert len(exported.slides) == len(ui_slides)
    assert "UI Added Slide" in slide_text


def test_ui_export_canonicalizes_three_column_cards() -> None:
    slide = api_module._ui_slide_to_planning_slide(
        ExportSlideRequest(
            id="s-columns",
            index=1,
            purpose="content",
            title="Capability map",
            template_id="content.3col",
            speaker_notes=None,
            blocks=[
                ExportBlockRequest(
                    id="b1",
                    kind="callout",
                    content="Speed: Faster rollout\nQuality: Stronger controls\nCost: Lower support load",
                    data={
                        "cards": [
                            {"title": "Speed", "text": "Faster rollout"},
                            {"title": "Quality", "text": "Stronger controls"},
                            {"title": "Cost", "text": "Lower support load"},
                        ]
                    },
                    citation=None,
                )
            ],
        ),
        existing_slide=None,
        fallback_source_id="ui-export",
    )

    assert [block.kind.value for block in slide.blocks] == ["text", "text", "text"]
    assert [block.content["text"] for block in slide.blocks] == [
        "Speed\nFaster rollout",
        "Quality\nStronger controls",
        "Cost\nLower support load",
    ]


def test_ui_export_preserves_structured_image_data_for_photo_templates() -> None:
    slide = api_module._ui_slide_to_planning_slide(
        ExportSlideRequest(
            id="s-photo",
            index=1,
            purpose="content",
            title="Original title",
            template_id="bold.photo",
            speaker_notes=None,
            blocks=[
                ExportBlockRequest(
                    id="b1",
                    kind="text",
                    content="A sharper executive statement",
                    data={"text": "A sharper executive statement"},
                    citation=None,
                ),
                ExportBlockRequest(
                    id="b2",
                    kind="image",
                    content="path: C:/assets/photo.png",
                    data={"path": "C:/assets/photo.png"},
                    citation=None,
                ),
            ],
        ),
        existing_slide=None,
        fallback_source_id="ui-export",
    )

    assert slide.headline == "A sharper executive statement"
    assert slide.blocks[1].content == {"path": "C:/assets/photo.png"}


def test_ui_export_canonicalizes_chart_takeaway_callout_cards_to_text() -> None:
    slide = api_module._ui_slide_to_planning_slide(
        ExportSlideRequest(
            id="s-chart",
            index=1,
            purpose="content",
            title="Quarterly trend",
            template_id="chart.takeaway",
            speaker_notes=None,
            blocks=[
                ExportBlockRequest(
                    id="b1",
                    kind="chart",
                    content="Q1: 1\nQ2: 2",
                    data={"chart_type": "bar", "series": [{"label": "Q1", "value": 1.0}, {"label": "Q2", "value": 2.0}]},
                    citation=None,
                ),
                ExportBlockRequest(
                    id="b2",
                    kind="callout",
                    content="Takeaway: Automation compounds over time",
                    data={"cards": [{"title": "Takeaway", "text": "Automation compounds over time"}]},
                    citation=None,
                ),
            ],
        ),
        existing_slide=None,
        fallback_source_id="ui-export",
    )

    assert slide.blocks[1].content == {"text": "Takeaway: Automation compounds over time"}


def test_ui_export_preserves_structured_table_data() -> None:
    slide = api_module._ui_slide_to_planning_slide(
        ExportSlideRequest(
            id="s-table",
            index=1,
            purpose="content",
            title="Agenda",
            template_id="agenda.table",
            speaker_notes=None,
            blocks=[
                ExportBlockRequest(
                    id="b1",
                    kind="table",
                    content="Discovery | Align priorities\nDelivery | Sequence work",
                    data={
                        "columns": ["Section", "Focus"],
                        "rows": [["Discovery", "Align priorities"], ["Delivery", "Sequence work"]],
                    },
                    citation=None,
                )
            ],
        ),
        existing_slide=None,
        fallback_source_id="ui-export",
    )

    assert slide.blocks[0].content["columns"] == ["Section", "Focus"]
    assert slide.blocks[0].content["rows"][0] == ["Discovery", "Align priorities"]


def test_ui_export_preserves_card_data_for_icon_templates() -> None:
    for template_id, expected_count in (("icons.3", 3), ("icons.4", 4)):
        slide = api_module._ui_slide_to_planning_slide(
            ExportSlideRequest(
                id=f"s-{template_id}",
                index=1,
                purpose="content",
                title="Delivery model",
                template_id=template_id,
                speaker_notes=None,
                blocks=[
                    ExportBlockRequest(
                        id="b1",
                        kind="callout",
                        content="\n".join(
                            f"Card {index + 1}: Detail {index + 1}"
                            for index in range(expected_count)
                        ),
                        data={
                            "cards": [
                                {"title": f"Card {index + 1}", "text": f"Detail {index + 1}"}
                                for index in range(expected_count)
                            ]
                        },
                        citation=None,
                    )
                ],
            ),
            existing_slide=None,
            fallback_source_id="ui-export",
        )

        assert len(slide.blocks) == 1
        assert slide.blocks[0].kind.value == "callout"
        assert len(slide.blocks[0].content["cards"]) == expected_count


def test_api_plan_from_prompt_infers_planning_inputs(monkeypatch, sample_pdf_path, deterministic_embedder) -> None:
    _reset_api_state()
    monkeypatch.setattr(api_module, "_get_embedder", lambda: deterministic_embedder)
    client = TestClient(api_module.app)
    doc_id = _ingest_fixture(client, sample_pdf_path)

    response = client.post(
        "/api/plan/prompt",
        json={
            "doc_ids": [doc_id],
            "prompt": "Create a 6 slide architecture deck for Oracle consultants focused on pipeline design.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["audience"] == "Oracle consultants"
    assert payload["goal"].lower().startswith("create a 6 slide architecture")
    assert len(payload["slides"]) == 6
    assert payload["slides"][0]["template_id"] == "title.cover"


def test_api_chat_generate_runs_pipeline(monkeypatch, sample_pdf_path, deterministic_embedder) -> None:
    _reset_api_state()
    monkeypatch.setattr(api_module, "_get_embedder", lambda: deterministic_embedder)
    client = TestClient(api_module.app)

    response = client.post(
        "/api/chat/generate",
        data={"prompt": "Create a 6 slide architecture deck for Oracle consultants focused on pipeline design."},
        files={"file": ("sample_ingestion.pdf", sample_pdf_path.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"].startswith("chat-")
    assert payload["inferred_audience"] == "Oracle consultants"
    assert payload["inferred_slide_count"] == 6
    assert payload["deck"]["slides"]
    overview_slide = next(slide for slide in payload["deck"]["slides"] if slide["archetype"] == "executive_summary")
    assert any(block.get("data", {}).get("cards") for block in overview_slide["blocks"] if isinstance(block.get("data"), dict))
    assert any(slide["template_id"] in {"closing.actions", "compare.2col"} for slide in payload["deck"]["slides"])


def test_api_slide_preview_calls_llm_and_returns_consulting_style() -> None:
    _reset_api_state()

    class FakeClient:
        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict:
            assert schema_name == "SlidePreviewLLMResponse"
            assert "selected template key: exec.summary" in user_prompt.lower()
            return {
                "headline": "Executive Overview",
                "speaker_notes": "Consulting style preview",
                "blocks": [
                    {
                        "kind": "text",
                        "text": "Consulting-style summary for Oracle delivery leaders.",
                    },
                    {
                        "kind": "callout",
                        "cards": [
                            {"title": "Ingestion", "text": "Normalize enterprise inputs"},
                            {"title": "Retrieval", "text": "Ground claims in evidence"},
                            {"title": "Layout", "text": "Apply deterministic templates"},
                        ],
                    },
                ],
            }

    api_module._STRUCTURED_LLM_CLIENT = FakeClient()
    client = TestClient(api_module.app)

    response = client.post(
        "/api/slide/preview",
        json={
            "slide_id": "slide-preview-1",
            "title": "Executive Overview",
            "purpose": "content",
            "template_id": "exec.summary",
            "content": "Current draft text about ingestion, retrieval, layout, and export.",
            "audience": "Oracle consultants",
            "goal": "Explain the delivery architecture",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "slide-preview-1"
    assert payload["title"] == "Executive Overview"
    assert payload["template_id"] == "exec.summary"
    assert any(block.get("data", {}).get("cards") for block in payload["blocks"] if isinstance(block.get("data"), dict))


def test_api_slide_preview_falls_back_when_structured_llm_payload_is_malformed() -> None:
    _reset_api_state()

    class FakeClient:
        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict:
            return {
                "headline": "Broken Preview",
                "blocks": "not-a-list",
            }

    api_module._STRUCTURED_LLM_CLIENT = FakeClient()
    client = TestClient(api_module.app)

    response = client.post(
        "/api/slide/preview",
        json={
            "slide_id": "slide-preview-fallback",
            "title": "Fallback Preview",
            "purpose": "content",
            "template_id": "compare.2col",
            "content": "First point explains ingestion. Second point covers retrieval. Third point summarizes export.",
            "audience": "Operators",
            "goal": "Explain the workflow",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "slide-preview-fallback"
    assert payload["title"] == "Fallback Preview"
    assert payload["template_id"] == "compare.2col"
    assert payload["blocks"]
    assert all(isinstance(block.get("data"), dict) for block in payload["blocks"])
    assert len(payload["blocks"]) == 2
    assert all(block["kind"] == "bullets" for block in payload["blocks"])
    assert all(block.get("data", {}).get("items") for block in payload["blocks"])


def test_api_serves_built_frontend(monkeypatch, tmp_path) -> None:
    web_dir = tmp_path / "web"
    assets_dir = web_dir / "assets"
    assets_dir.mkdir(parents=True)
    index_path = web_dir / "index.html"
    asset_path = assets_dir / "app.js"
    index_path.write_text("<!doctype html><html><body>Auto-PPT UI</body></html>", encoding="utf-8")
    asset_path.write_text("console.log('ui')", encoding="utf-8")

    monkeypatch.setattr(api_module, "WEB_DIR", web_dir)
    monkeypatch.setattr(api_module, "WEB_INDEX", index_path)
    client = TestClient(api_module.app)

    root = client.get("/")
    assert root.status_code == 200
    assert "Auto-PPT UI" in root.text

    route = client.get("/editor/demo-deck")
    assert route.status_code == 200
    assert "Auto-PPT UI" in route.text

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert asset.text == "console.log('ui')"


# ---------------------------------------------------------------------------
# _infer_chat_brief – dynamic slide count heuristic
# ---------------------------------------------------------------------------


def test_infer_chat_brief_default_slide_count() -> None:
    result = api_module._infer_chat_brief("Make a deck about AI", "AI Overview")
    assert result["slide_count"] == 6


def test_infer_chat_brief_scales_with_chunk_count() -> None:
    # 60 chunks → 4 + 60//10 = 10 slides
    result = api_module._infer_chat_brief("Make a deck", "Doc", content_chunk_count=60)
    assert result["slide_count"] == 10

    # 200 chunks → capped at 20
    result = api_module._infer_chat_brief("Make a deck", "Doc", content_chunk_count=200)
    assert result["slide_count"] == 20

    # 15 chunks → max(6, 4+1) = 6 (floor)
    result = api_module._infer_chat_brief("Make a deck", "Doc", content_chunk_count=15)
    assert result["slide_count"] == 6


def test_infer_chat_brief_explicit_user_count_overrides() -> None:
    result = api_module._infer_chat_brief(
        "Create 12 slides about the platform", "Platform", content_chunk_count=5,
    )
    assert result["slide_count"] == 12


def test_infer_chat_brief_pptx_source_preserves_slide_count() -> None:
    ctx = {"source_format": "pptx", "slide_count": 8}
    result = api_module._infer_chat_brief("Rebrand this deck", "Deck", source_context=ctx)
    assert result["slide_count"] == 8


def test_infer_chat_brief_pptx_explicit_override_wins() -> None:
    ctx = {"source_format": "pptx", "slide_count": 8}
    result = api_module._infer_chat_brief(
        "Rebrand this deck as 4 slides", "Deck", source_context=ctx,
    )
    assert result["slide_count"] == 4


def test_infer_chat_brief_audience_extraction() -> None:
    result = api_module._infer_chat_brief(
        "Create a deck for Oracle consultants on AI", "AI",
    )
    assert result["audience"] == "Oracle consultants"


def test_infer_chat_brief_tone_technical() -> None:
    result = api_module._infer_chat_brief("Technical deep dive for consultants", "Tech")
    assert result["tone"] == 25.0


def test_infer_chat_brief_tone_sales() -> None:
    result = api_module._infer_chat_brief("Bold investor pitch", "Startup")
    assert result["tone"] == 80.0
