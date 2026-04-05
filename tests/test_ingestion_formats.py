from __future__ import annotations

from pptx_gen.ingestion.chunker import chunk_document
from pptx_gen.ingestion.parser import parse_source


def test_parse_markdown_file_preserves_basic_chunk_metadata(make_markdown_file) -> None:
    path = make_markdown_file()

    request = parse_source(path)
    chunks = chunk_document(request)

    assert request.document.elements
    assert request.document.mime_type in {"text/markdown", "text/plain"}
    assert chunks
    assert all(chunk.chunk_id.startswith(f"{request.document.elements[0].doc_id}:") for chunk in chunks)


def test_parse_docx_preserves_structured_element_types(make_docx_file) -> None:
    path = make_docx_file()

    request = parse_source(path)
    element_types = {element.type.value for element in request.document.elements}

    assert request.document.mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert {"title", "heading", "paragraph", "list_item", "table"} <= element_types


def test_parse_csv_emits_title_and_table(make_csv_file) -> None:
    path = make_csv_file()

    request = parse_source(path)

    assert request.document.elements[0].type.value == "title"
    assert any(element.type.value == "table" for element in request.document.elements)
    assert all(element.page == 1 for element in request.document.elements)


def test_parse_xlsx_emits_sheet_heading_and_table(make_xlsx_file) -> None:
    path = make_xlsx_file()

    request = parse_source(path)
    chunks = chunk_document(request)

    assert request.document.mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert any(element.type.value == "heading" for element in request.document.elements)
    assert any(element.type.value == "table" for element in request.document.elements)
    assert chunks
    assert all(chunk.locator.endswith("page1") for chunk in chunks)


def test_parse_pptx_extracts_slide_text_and_tables(make_pptx_file) -> None:
    path = make_pptx_file()

    request = parse_source(path)
    element_types = {element.type.value for element in request.document.elements}
    pages = {element.page for element in request.document.elements}

    assert request.document.mime_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    assert {"title", "paragraph", "table"} <= element_types
    assert pages == {1, 2}


def test_parse_json_emits_title_and_structured_elements(make_json_file) -> None:
    path = make_json_file()

    request = parse_source(path)
    element_types = {element.type.value for element in request.document.elements}
    chunks = chunk_document(request)

    assert request.document.title == "Chart Spec Catalog"
    assert request.document.mime_type == "application/json"
    assert request.document.elements[0].type.value == "title"
    assert {"heading", "paragraph", "table", "list_item"} & element_types
    assert chunks


def test_parse_png_emits_figure_with_metadata(make_image_file) -> None:
    path = make_image_file(".png")

    request = parse_source(path)

    assert request.document.mime_type == "image/png"
    assert [element.type.value for element in request.document.elements] == ["title", "figure"]
    figure = request.document.elements[1]
    assert figure.extensions is not None
    assert figure.extensions["path"] == str(path)
    assert figure.extensions["format"] == "PNG"


def test_parse_webp_emits_figure_with_metadata(make_image_file) -> None:
    path = make_image_file(".webp")

    request = parse_source(path)

    assert request.document.mime_type == "image/webp"
    assert request.document.elements[1].type.value == "figure"
    assert request.document.elements[1].extensions is not None
    assert request.document.elements[1].extensions["format"] == "WEBP"
