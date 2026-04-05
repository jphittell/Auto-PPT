from __future__ import annotations

from fastapi.testclient import TestClient

import pptx_gen.api as api_module
import pptx_gen.pipeline as pipeline_module


def test_api_health_and_templates() -> None:
    client = TestClient(api_module.app)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "phase": "1", "ingest": True, "generation": "mock"}

    templates = client.get("/api/templates")
    assert templates.status_code == 200
    payload = templates.json()
    assert len(payload) == 10
    assert any(item["id"] == "title.hero" for item in payload)


def test_api_ingest_pdf_returns_summary(monkeypatch, sample_pdf_path, deterministic_embedder) -> None:
    api_module._INGESTED_DOCS.clear()
    monkeypatch.setattr(pipeline_module, "SentenceTransformerEmbedder", lambda: deterministic_embedder)
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


def test_api_generate_get_deck_and_export(monkeypatch) -> None:
    async def _noop_sleep(_: float) -> None:
        return None

    api_module._INGESTED_DOCS.clear()
    api_module._DECKS.clear()
    api_module._RAW_DECK_SPECS.clear()
    api_module._INGESTED_DOCS["demo-doc"] = api_module.IngestResponse(
        doc_id="demo-doc",
        chunk_count=4,
        title="Demo Document",
        element_types={"title": 1, "paragraph": 3},
    )
    monkeypatch.setattr(api_module.asyncio, "sleep", _noop_sleep)
    client = TestClient(api_module.app)

    generated = client.post(
        "/api/generate",
        json={
          "doc_id": "demo-doc",
          "goal": "Board update",
          "audience": "Executive Steering Committee",
          "tone": 50,
          "slide_count": 8,
        },
    )

    assert generated.status_code == 200
    deck = generated.json()
    assert len(deck["slides"]) == 8
    deck_id = deck["id"]

    fetched = client.get(f"/api/deck/{deck_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == deck_id

    upgrade = client.post(f"/api/export/{deck_id}", json={"format": "pptx"})
    assert upgrade.status_code == 200
    assert upgrade.json() == {"status": "upgrade_required", "tier": "pro"}

    pdf = client.post(f"/api/export/{deck_id}", json={"format": "pdf"})
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content.startswith(b"%PDF-1.4")
