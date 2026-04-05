# Asset Policy — Auto PPT

**Version:** 1.0.0
**Status:** Authoritative for v1
**Scope:** All image, chart, icon, and font assets consumed by the renderer

---

## 1. Purpose

The renderer is deterministic. It accepts only local, cached, integrity-verified assets at render
time. This document defines what is allowed into the cache, what is forbidden, and what metadata
every asset must carry before the renderer touches it.

---

## 2. V1 Source Policy: Local-Only, Provided Assets

V1 is **`provided_only`**. This mirrors the `ImageSourcePolicy.PROVIDED_ONLY` enum value that is
already the default in `ImageTokens` (layout/schemas.py) and the `source_policy` field in
`DEFAULT_STYLE_TOKENS` (pipeline.py).

The only assets that may enter the asset cache in v1 are:

| Source kind | Allowed in v1 | Notes |
|---|---|---|
| Local file path supplied by the caller | ✅ Yes | Must exist on disk at resolution time |
| Chart spec rendered to PNG by `chart_renderer.py` | ✅ Yes | Treated as a locally-generated asset |
| Stock image service (Getty, Unsplash, Pexels, etc.) | ❌ No | Reserved for v2 |
| AI image generation (DALL-E, Stable Diffusion, etc.) | ❌ No | Reserved for v2+ |
| Remote URL passed directly into a layout slot | ❌ Never | Hard-blocked at all pipeline stages |
| Authenticated / short-lived CDN URL | ❌ Never | Hard-blocked; URLs expire before render |

The `source_policy` field on `StyleTokens.images` controls which path the asset stage takes.
Callers that try to set a non-`provided_only` policy in v1 must receive a clear `ValueError` at
the top of `resolve_assets`.

---

## 3. What Is Forbidden

The following are unconditional prohibitions regardless of pipeline stage or caller intent:

1. **Remote URLs in the PPTX.** No `http://` or `https://` string may appear in any rendered
   element. `extract_local_asset_path` (renderer/slide_ops.py) already enforces this; it must
   remain a hard guard, not a warning.

2. **Unverified file hashes.** Every asset that enters the cache must have its SHA-256 computed
   and stored in `AssetRecord.sha256` before the renderer receives the layout. An asset with a
   missing or malformed hash must be rejected.

3. **Assets outside the declared cache directory.** The resolver copies every provided asset into
   the artifacts `assets/` subdirectory. No element payload may reference a path outside that
   directory at render time.

4. **Lossy format coercion.** Chart PNGs are already written with `dpi=150`. Provided images must
   not be recompressed or converted during copy; they are hashed and stored as-is.

5. **Silent skip of missing assets.** If a `ResolvedElement` of kind `IMAGE` or `CHART` has no
   resolvable local path, the resolver must raise — it must not silently drop the element or
   substitute a placeholder. The current code in `_resolve_element_asset` already does this.

---

## 4. Required Asset Metadata

Every `AssetRecord` persisted to `AssetManifest` must carry the following fields. Fields marked
**Required** must be non-null; fields marked **Optional-v1** may be `None` in v1 but must be
present in the model so they can be populated in v2 without a schema break.

| Field | Type | Required | Description |
|---|---|---|---|
| `asset_id` | `str` | Required | Matches the `element_id` of the resolved element that owns this asset |
| `source_type` | `AssetSourceType` enum | Required | One of: `local_provided`, `chart_rendered`, `stock` (v2), `ai_generated` (v2+) |
| `local_path` | `str` | Required | Absolute path to the cached file inside the artifacts `assets/` directory |
| `sha256` | `str` (64 hex chars) | Required | SHA-256 of the cached file, computed after copy/render |
| `license` | `str \| None` | Optional-v1 | SPDX identifier or free-text usage terms (e.g. `"CC0-1.0"`, `"editorial_only"`) |
| `alt_text` | `str \| None` | Optional-v1 | Accessibility description of the visual content; required for v2 |
| `aspect_ratio` | `float \| None` | Optional-v1 | `width / height` of the cached file; used by v2 fill/fit logic |
| `original_source` | `str \| None` | Optional-v1 | Provenance URI or local path before caching; the pre-copy origin |
| `created_at` | `datetime \| None` | Optional-v1 | UTC timestamp of when the asset was written into the cache |

The `AssetRecord` model in `assets/resolver.py` currently has `asset_id`, `sha256`,
`source_uri`, `license`, `attribution`, and `created_at`. The delta to reach compliance with
this spec is:

- Rename `uri` → `local_path` (or add `local_path` as the canonical field and deprecate `uri`)
- Add `source_type: AssetSourceType` (new required enum)
- Add `alt_text: str | None`
- Add `aspect_ratio: float | None`
- Rename or alias `source_uri` → `original_source`

These changes are additive and non-breaking if done as field additions with defaults before any
rename.

---

## 5. Asset Source Type Enum

```python
class AssetSourceType(str, Enum):
    LOCAL_PROVIDED   = "local_provided"   # Caller-supplied file; v1 only source
    CHART_RENDERED   = "chart_rendered"   # PNG produced by chart_renderer.py
    STOCK            = "stock"            # Downloaded from a licensed stock service (v2)
    AI_GENERATED     = "ai_generated"     # Produced by an image generation model (v2+)
```

The resolver must set `source_type` based on the element kind:

- `ResolvedElementKind.CHART` → `AssetSourceType.CHART_RENDERED`
- `ResolvedElementKind.IMAGE` → `AssetSourceType.LOCAL_PROVIDED` (v1)

---

## 6. Cache Directory Contract

```
<output_name>_artifacts/
└── assets/
    ├── <sha256>.<ext>          # All provided images, named by hash
    ├── <element_id>.png        # Chart renders, named by element id pre-hash
    └── asset_manifest.json     # Full AssetManifest written by pipeline.py
```

Rules:

- File names for provided images must use the SHA-256 as the stem (current behavior in
  `_copy_local_asset`). This ensures identical files are deduplicated automatically.
- Chart render files may use the element ID as the stem before hashing, then be renamed to the
  hash once written (or kept by element ID — either is acceptable as long as `local_path` in
  `AssetRecord` is the definitive reference).
- The `asset_manifest.json` must be written by `pipeline.py` after `resolve_assets` returns and
  before `export_pptx` is called. This is already the case.

---

## 7. V2 Extension Points

When `source_policy` is upgraded beyond `provided_only`, the following additions are expected:

- A downloader module (`assets/downloader.py`) responsible for fetching, verifying, and caching
  stock images. It must compute SHA-256 after download and refuse to write to cache on hash
  mismatch.
- A `license` field population step — stock images must carry their license string before entering
  the manifest. Assets with `license: None` are only acceptable for `local_provided` and
  `chart_rendered` types.
- An `alt_text` generation step (LLM or caption model) that runs after download/render and
  populates the field before the manifest is finalized.
- An `aspect_ratio` check against the target slot dimensions from the template registry, with a
  fill/fit policy decision recorded on the `AssetRecord`.

---

## 8. Relationship to Existing Code

| Policy rule | Where enforced today |
|---|---|
| No remote URLs in the PPTX | `extract_local_asset_path` in renderer/slide_ops.py |
| Local copy before render | `_copy_local_asset` in assets/resolver.py |
| SHA-256 computed and stored | `_hash_file` + `AssetRecord.sha256` in assets/resolver.py |
| Manifest written before export | `pipeline.py` lines 235–236 |
| `source_policy` field on StyleTokens | `ImageTokens` in layout/schemas.py |
| Missing asset raises, not skips | `_resolve_element_asset` in assets/resolver.py |

Fields not yet enforced: `source_type`, `alt_text`, `aspect_ratio`, `local_path` canonical name.
