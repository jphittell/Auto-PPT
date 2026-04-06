from __future__ import annotations

from fastapi.testclient import TestClient

import pptx_gen.api as api_module


def _reset_api_state() -> None:
    api_module._INGESTED_DOCS.clear()
    api_module._INGESTED_RESULTS.clear()
    api_module._DRAFTS.clear()
    api_module._DECKS.clear()
    api_module._RAW_DECK_SPECS.clear()
    api_module._CHAT_SESSIONS.clear()
    api_module._EMBEDDER = None


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
    assert len(payload) == 12
    template_by_id = {item["id"]: item for item in payload}
    assert template_by_id["content.1col"]["deck_default_allowed"] is True
    assert template_by_id["content.3col.cards"]["deck_default_allowed"] is True
    assert template_by_id["kpi.3up"]["deck_default_allowed"] is True
    assert template_by_id["title.hero"]["deck_default_allowed"] is False
    assert template_by_id["executive.overview"]["deck_default_allowed"] is False
    assert template_by_id["architecture.grid"]["deck_default_allowed"] is False


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
    assert draft["slides"][0]["template_id"] == "title.hero"
    assert draft["slides"][1]["template_id"] == "agenda.list"
    assert draft["slides"][2]["archetype"] == "executive_overview"
    assert draft["slides"][2]["template_id"] == "executive.overview"
    assert draft["slides"][0]["blocks"][0]["content"].startswith("Subtitle:")
    assert draft["slides"][1]["blocks"][0]["kind"] == "bullets"
    assert any(slide["template_id"] == "architecture.grid" for slide in draft["slides"])

    edited_outline = list(draft["slides"])
    edited_outline[1]["title"] = "Reordered board priorities"
    edited_outline[2]["title"] = "Investor-safe evidence"
    edited_outline[2]["template_id"] = "content.3col.cards"
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
            "selected_template_id": "kpi.3up",
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
    assert deck["slides"][1]["title"] == "Investor-safe evidence"
    assert deck["slides"][2]["title"] == "Reordered board priorities"
    deck_by_title = {slide["title"]: slide for slide in deck["slides"]}
    content_templates = {
        slide["title"]: slide["template_id"]
        for slide in deck["slides"]
        if slide["purpose"] in {"content", "summary"}
    }
    assert deck_by_title["Investor-safe evidence"]["purpose"] == "content"
    assert content_templates["Investor-safe evidence"] == "content.3col.cards"
    assert any(template_id == "kpi.3up" for title, template_id in content_templates.items() if title != "Investor-safe evidence")
    assert any(slide.get("archetype") == "executive_overview" for slide in deck["slides"])
    overview_slide = next(slide for slide in deck["slides"] if slide.get("archetype") == "executive_overview")
    assert any(block.get("data", {}).get("cards") for block in overview_slide["blocks"] if isinstance(block.get("data"), dict))
    assert any(slide["template_id"] == "architecture.grid" for slide in deck["slides"])
    assert any(
        block["kind"] == "bullets" and block["content"].startswith("• ")
        for slide in deck["slides"]
        for block in slide["blocks"]
    )
    assert deck["theme"]["primary_color"] == "#112233"
    assert deck["theme"]["accent_color"] == "#445566"
    assert deck["theme"]["heading_font"] == "DM Serif Display"
    assert deck["theme"]["body_font"] == "DM Sans"
    assert any("Analytical framing" in block["content"] for slide in deck["slides"] for block in slide["blocks"])

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
            "selected_template_id": "content.1col",
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
            "selected_template_id": "content.3col.cards",
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
    assert analytical_text != bold_text
    assert "Analytical framing" in analytical_text
    assert "Bold framing" in bold_text
    assert any(
        slide["template_id"] in {"content.3col.cards", "architecture.grid", "kpi.3up", "executive.overview"}
        for slide in bold_deck["slides"]
        if slide["purpose"] in {"content", "summary"}
    )
    assert analytical_plan["slides"][0]["blocks"][0]["content"].startswith("Subtitle: Board update")
    assert any(slide["template_id"] in {"content.3col.cards", "architecture.grid"} for slide in analytical_plan["slides"])


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
    overview_slide = next(slide for slide in payload["deck"]["slides"] if slide["archetype"] == "executive_overview")
    assert any(block.get("data", {}).get("cards") for block in overview_slide["blocks"] if isinstance(block.get("data"), dict))
    assert any(slide["template_id"] == "architecture.grid" for slide in payload["deck"]["slides"])


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
