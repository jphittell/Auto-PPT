from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import pptx_gen.pipeline as pipeline_module
from pptx_gen.planning.llm_client import (
    AnthropicStructuredClient,
    OpenAIStructuredClient,
    StructuredLLMClientError,
    build_default_structured_llm_client,
)


class FakeMessagesAPI:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeAnthropicSDK:
    def __init__(self, response: object) -> None:
        self.messages = FakeMessagesAPI(response)


class FakeOpenAICompletionsAPI:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeOpenAIChatAPI:
    def __init__(self, response: object) -> None:
        self.completions = FakeOpenAICompletionsAPI(response)


class FakeOpenAISDK:
    def __init__(self, response: object) -> None:
        self.chat = FakeOpenAIChatAPI(response)


def test_anthropic_structured_client_parses_tool_use_json() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="return_deckbrief",
                input={
                    "schema_version": "1.0.0",
                    "audience": "Executive team",
                    "goal": "Summarize the quarter",
                    "tone": "executive",
                    "slide_count_target": 6,
                    "source_corpus_ids": ["doc-1"],
                    "questions_for_user": [],
                },
            )
        ]
    )
    sdk = FakeAnthropicSDK(response)
    client = AnthropicStructuredClient(anthropic_client=sdk, api_key="test-key")

    result = client.generate_json(system_prompt="sys", user_prompt="user", schema_name="DeckBrief")

    assert result["audience"] == "Executive team"
    assert sdk.messages.calls
    call = sdk.messages.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "return_deckbrief"}
    assert "strict" not in call["tools"][0]


def test_openai_structured_client_parses_json_schema_response() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        '{"schema_version":"1.0.0","audience":"Executive team","goal":"Summarize the quarter",'
                        '"tone":"executive","slide_count_target":6,"source_corpus_ids":["doc-1"],'
                        '"questions_for_user":[]}'
                    )
                )
            )
        ]
    )
    sdk = FakeOpenAISDK(response)
    client = OpenAIStructuredClient(openai_client=sdk, api_key="test-key")

    result = client.generate_json(system_prompt="sys", user_prompt="user", schema_name="DeckBrief")

    assert result["audience"] == "Executive team"
    assert sdk.chat.completions.calls
    call = sdk.chat.completions.calls[0]
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["name"] == "DeckBrief"
    assert call["response_format"]["json_schema"]["strict"] is True


def test_openai_structured_client_uses_json_object_for_complex_schema() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        '{"schema_version":"1.0.0","applied":true,"rationale":["trimmed text"],'
                        '"presentation_spec":{"schema_version":"1.0.0","title":"Quarterly Review",'
                        '"audience":"Executive team","language":"en-US","theme":{"name":"Auto PPT",'
                        '"style_tokens":{"fonts":{"heading":"Aptos Display","body":"Aptos","mono":"Cascadia Code"},'
                        '"colors":{"bg":"#FFFFFF","text":"#111111","accent":"#0A84FF","muted":"#6B7280"},'
                        '"spacing":{"margin_in":0.5,"gutter_in":0.25},'
                        '"images":{"source_policy":"provided_only","style_prompt":"clean editorial visuals"}}},'
                        '"slides":[{"slide_id":"s1","purpose":"title","layout_intent":{"template_key":"title.cover","strict_template":true},'
                        '"headline":"Quarterly Review","speaker_notes":"","blocks":[{"block_id":"b1","kind":"text",'
                        '"content":{"subtitle":"Quarter summary","presenter":"Leadership","date":"2026-04-05"},'
                        '"source_citations":[],"asset_refs":[]}]}],"questions_for_user":[]}}'
                    )
                )
            )
        ]
    )
    sdk = FakeOpenAISDK(response)
    client = OpenAIStructuredClient(openai_client=sdk, api_key="test-key")

    result = client.generate_json(system_prompt="sys", user_prompt="user", schema_name="DesignRefinement")

    assert result["applied"] is True
    call = sdk.chat.completions.calls[0]
    assert call["response_format"] == {"type": "json_object"}


def test_openai_structured_client_normalizes_presentation_spec_like_payload() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "schema_version": "1.0.0",
                            "theme": {
                                "style_tokens": {
                                    "fonts": {"heading": "Aptos Display", "body": "Aptos", "mono": "Cascadia Code"},
                                    "colors": {"bg": "#FFFFFF", "text": "#111111", "accent": "#0A84FF", "muted": "#6B7280"},
                                    "spacing": {"margin_in": 0.5, "gutter_in": 0.25},
                                    "images": {"source_policy": "provided_only", "style_prompt": "clean editorial visuals"},
                                }
                            },
                            "slides": [
                                {
                                    "slide_id": "s1",
                                    "template_key": "title.cover",
                                    "title": "Quarterly Review",
                                    "blocks": [{"kind": "text", "content": "Quarter summary"}],
                                }
                            ],
                        }
                    )
                )
            )
        ]
    )
    sdk = FakeOpenAISDK(response)
    client = OpenAIStructuredClient(openai_client=sdk, api_key="test-key")

    result = client.generate_json(system_prompt="sys", user_prompt="user", schema_name="PresentationSpec")

    assert result["title"] == "Quarterly Review"
    assert result["slides"][0]["layout_intent"]["template_key"] == "title.cover"
    assert result["slides"][0]["blocks"][0]["content"] == {"text": "Quarter summary"}


def test_anthropic_structured_client_normalizes_presentation_spec_like_payload() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="return_presentationspec",
                input={
                    "schema_version": "1.0.0",
                    "theme": {
                        "style_tokens": {
                            "fonts": {"heading": "Aptos Display", "body": "Aptos", "mono": "Cascadia Code"},
                            "colors": {"bg": "#FFFFFF", "text": "#111111", "accent": "#0A84FF", "muted": "#6B7280"},
                            "spacing": {"margin_in": 0.5, "gutter_in": 0.25},
                            "images": {"source_policy": "provided_only", "style_prompt": "clean editorial visuals"},
                        }
                    },
                    "slides": [
                        {
                            "slide_id": "s1",
                            "template_key": "title.cover",
                            "title": "Quarterly Review",
                            "blocks": [{"kind": "text", "content": "Quarter summary"}],
                        },
                        {
                            "slide_id": "s2",
                            "template_key": "headline.evidence",
                            "headline": "Revenue Improved",
                            "blocks": [{"kind": "text", "content": "Revenue improved materially"}],
                        },
                        {
                            "slide_id": "s3",
                            "template_key": "headline.evidence",
                            "headline": "Margin Expanded",
                            "blocks": [
                                {
                                    "kind": "text",
                                    "content": "Margin expanded after infrastructure changes",
                                    "source_citations": [{"source_id": "doc-1", "locator": "doc-1:page1"}],
                                }
                            ],
                        },
                    ],
                },
            )
        ]
    )
    sdk = FakeAnthropicSDK(response)
    client = AnthropicStructuredClient(anthropic_client=sdk, api_key="test-key")

    result = client.generate_json(system_prompt="sys", user_prompt="user", schema_name="PresentationSpec")

    assert result["title"] == "Quarterly Review"
    assert result["slides"][0]["layout_intent"]["template_key"] == "title.cover"
    assert result["slides"][1]["blocks"][0]["source_citations"] == [
        {"source_id": "doc-1", "locator": "doc-1:page1", "quote": None, "confidence": None}
    ]


def test_build_default_structured_llm_client_returns_none_without_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("pptx_gen.planning.llm_client._load_local_env", lambda: None)
    assert build_default_structured_llm_client() is None


def test_build_default_structured_llm_client_loads_repo_dotenv(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PPTX_GEN_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("PPTX_GEN_ANTHROPIC_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=test-from-dotenv\nPPTX_GEN_ANTHROPIC_MODEL=claude-test-model\n",
        encoding="utf-8",
    )

    fake_sdk = object()
    monkeypatch.setattr("pptx_gen.planning.llm_client._make_anthropic_client", lambda api_key: fake_sdk)

    client = build_default_structured_llm_client()

    assert client is not None
    assert client.api_key == "test-from-dotenv"
    assert client.model == "claude-test-model"
    assert client.anthropic_client is fake_sdk


def test_build_default_prefers_openai_over_anthropic(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("PPTX_GEN_OPENAI_MODEL", "gpt-4o")
    monkeypatch.setattr("pptx_gen.planning.llm_client._make_openai_client", lambda api_key: object())

    client = build_default_structured_llm_client()

    assert isinstance(client, OpenAIStructuredClient)


def test_anthropic_structured_client_fails_when_tool_use_missing() -> None:
    sdk = FakeAnthropicSDK(SimpleNamespace(content=[SimpleNamespace(type="text", text="not json")]))
    client = AnthropicStructuredClient(anthropic_client=sdk, api_key="test-key")

    with pytest.raises(StructuredLLMClientError, match="tool_use"):
        client.generate_json(system_prompt="sys", user_prompt="user", schema_name="DeckBrief")


def test_pipeline_uses_default_llm_client_when_available(
    monkeypatch,
    tmp_path,
    deterministic_embedder,
) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text(
        "Quarterly review. Revenue improved materially. Margin expanded after infrastructure changes.",
        encoding="utf-8",
    )

    class FakeStructuredClient:
        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict:
            if schema_name == "DeckBrief":
                return {
                    "schema_version": "1.0.0",
                    "audience": "Leadership",
                    "goal": "Summarize the quarter",
                    "tone": "executive",
                    "slide_count_target": 5,
                    "source_corpus_ids": ["source-txt"],
                    "questions_for_user": [],
                }
            if schema_name == "OutlineSpec":
                return {
                    "schema_version": "1.0.0",
                    "outline": [
                        {
                            "slide_id": "s1",
                            "purpose": "title",
                            "headline": "Quarterly Review",
                            "message": "Open the review.",
                            "evidence_queries": [],
                            "template_key": "title.cover",
                        },
                        {
                            "slide_id": "s2",
                            "purpose": "content",
                            "headline": "Revenue Improved",
                            "message": "Revenue improved materially.",
                            "evidence_queries": ["revenue improved materially"],
                            "template_key": "headline.evidence",
                        },
                        {
                            "slide_id": "s3",
                            "purpose": "summary",
                            "headline": "Key Takeaways",
                            "message": "Close the review.",
                            "evidence_queries": [],
                            "template_key": "headline.evidence",
                        },
                    ],
                    "questions_for_user": [],
                }
            if schema_name == "RetrievalPlan":
                return {
                    "schema_version": "1.0.0",
                    "retrieval_plan": [
                        {
                            "slide_id": "s2",
                            "queries": [
                                {
                                    "query": "revenue improved materially",
                                    "doc_ids": ["source-txt"],
                                    "min_date": None,
                                }
                            ],
                        }
                    ],
                    "questions_for_user": [],
                }
            if schema_name == "PresentationSpec":
                return {
                    "schema_version": "1.0.0",
                    "title": "Quarterly Review",
                    "audience": "Leadership",
                    "language": "en-US",
                    "theme": {
                        "name": "Auto PPT",
                        "style_tokens": pipeline_module.StyleTokens(**pipeline_module.DEFAULT_STYLE_TOKENS).model_dump(),
                    },
                    "slides": [
                        {
                            "slide_id": "s1",
                            "purpose": "title",
                            "layout_intent": {"template_key": "title.cover", "strict_template": True},
                            "headline": "Quarterly Review",
                            "speaker_notes": "Open the review. Set expectations.",
                            "blocks": [
                                {
                                    "block_id": "b1",
                                    "kind": "text",
                                    "content": {"subtitle": "Quarter summary", "presenter": "Leadership", "date": "2026-04-04"},
                                    "source_citations": [],
                                    "asset_refs": [],
                                }
                            ],
                        },
                        {
                            "slide_id": "s2",
                            "purpose": "content",
                            "layout_intent": {"template_key": "headline.evidence", "strict_template": True},
                            "headline": "Revenue Improved",
                            "speaker_notes": "Revenue improved materially. Cite the supporting chunk.",
                            "blocks": [
                                {
                                    "block_id": "b1",
                                    "kind": "bullets",
                                    "content": {"items": ["Revenue improved materially"]},
                                    "source_citations": [{"source_id": "source-txt", "locator": "source-txt:page1"}],
                                    "asset_refs": [],
                                },
                                {
                                    "block_id": "b2",
                                    "kind": "callout",
                                    "content": {"text": "Revenue improved"},
                                    "source_citations": [{"source_id": "source-txt", "locator": "source-txt:page1"}],
                                    "asset_refs": [],
                                },
                            ],
                        },
                        {
                            "slide_id": "s3",
                            "purpose": "summary",
                            "layout_intent": {"template_key": "headline.evidence", "strict_template": True},
                            "headline": "Key Takeaways",
                            "speaker_notes": "Close the review. Reinforce the supported message.",
                            "blocks": [
                                {
                                    "block_id": "b1",
                                    "kind": "bullets",
                                    "content": {"items": ["Revenue improved materially"]},
                                    "source_citations": [{"source_id": "source-txt", "locator": "source-txt:page1"}],
                                    "asset_refs": [],
                                },
                                {
                                    "block_id": "b2",
                                    "kind": "callout",
                                    "content": {"text": "Quarter summary"},
                                    "source_citations": [{"source_id": "source-txt", "locator": "source-txt:page1"}],
                                    "asset_refs": [],
                                },
                            ],
                        },
                    ],
                    "questions_for_user": [],
                }
            raise AssertionError(f"unexpected schema_name: {schema_name}")

    monkeypatch.setattr(pipeline_module, "build_default_structured_llm_client", lambda: FakeStructuredClient())

    result = pipeline_module.generate_deck(
        source_path=source_path,
        output_path=tmp_path / "llm-generated.pptx",
        audience="Leadership",
        goal="Summarize the quarter",
        slide_count_target=5,
        embedder=deterministic_embedder,
        llm_client=None,
    )

    assert result.output_path.endswith("llm-generated.pptx")
    assert result.export_job.status.value == "success"
