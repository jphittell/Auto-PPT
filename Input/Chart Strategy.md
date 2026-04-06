# Chart Strategy — Auto PPT v1

**Version:** 1.0.0
**Status:** Authoritative for v1
**Decision:** PNG-first. Native PowerPoint charts deferred to v2.

---

## 1. Decision

V1 renders all charts as **PNG images** via Matplotlib's `savefig()`. The renderer inserts them
into image slots. Native PPTX chart objects (GraphicFrame) are not used in v1.

---

## 2. Rationale

| Factor | PNG-first | Native PPTX charts |
|---|---|---|
| Implementation complexity | Low — `savefig()` + image slot | High — `python-pptx` chart API requires series-level XML manipulation |
| Visual fidelity | Full Matplotlib control over style, color, padding | Limited to OOXML chart styles; hard to match brand tokens exactly |
| Chart type coverage | All 13 catalog types renderable with Matplotlib | `python-pptx` supports bar, line, pie, scatter; no waterfall, donut, KPI tile, combo |
| Determinism | Fully deterministic given identical spec + Matplotlib version | Deterministic, but styling depends on Office rendering engine |
| Editability post-export | Not editable in PowerPoint (raster) | Fully editable (user can change data, colors, labels) |
| Renderer simplicity | Chart PNG is just another image — same slot logic as photos | Chart objects use a separate `GraphicFrame` code path in the exporter |
| Asset policy alignment | Chart PNGs go through the same hash/cache/manifest flow as all other assets | Chart objects bypass the asset manifest entirely |
| Testing | Visual regression via pixel-diff or hash comparison | Requires Office or LibreOffice to verify rendering |

The editability tradeoff is real but acceptable for v1. Users who need editable charts can request
the source data (available in the chart spec) and rebuild in Excel or PowerPoint.

---

## 3. V1 Implementation Contract

### 3.1 Renderer: `chart_renderer.py`

`render_chart_to_png(chart_spec, output_path, dpi=150)` is the single entry point.

**Currently supported chart types:**
- `bar` — vertical bars, single series
- `line` — single series with markers
- `pie` — solid pie with autopct labels
- `scatter` — index-based x, value-based y

**Planned chart types (v1 stretch):**
- `stacked_bar` — multi-series stacked vertical bars
- `grouped_bar` — multi-series side-by-side bars
- `area` — filled area, single or multi-series
- `multi_line` — two or more line series
- `donut` — hollow pie with wedge_width
- `waterfall` — floating bars with total anchors
- `horizontal_bar` — horizontal orientation
- `kpi_tile` — 3-panel metric image
- `combo_bar_line` — dual-axis bar + line

### 3.2 Output contract

| Property | Value |
|---|---|
| Format | PNG, RGBA |
| DPI | 150 (configurable) |
| Background | Transparent (`facecolor="none"`) |
| Tight layout | `bbox_inches="tight"`, `pad_inches=0.1` |
| Naming | `<element_id>.png` pre-hash, renamed to `<sha256>.png` after caching |

### 3.3 Style tokens consumed

Charts read from `StyleTokens`:
- `colors.accent` — primary series color (default `#0A84FF`)
- `colors.text` — axis labels, tick labels, title
- `colors.muted` — grid lines
- `colors.bg` — not used (transparent background)
- `fonts.body` — tick and axis labels
- `fonts.heading` — chart title

Per-spec overrides:
- `accent_color` — overrides `colors.accent` for the primary series
- `palette` — ordered color list for multi-series or segmented charts

### 3.4 Aspect ratio

The chart spec's `aspect_ratio` field sets the figure's width/height ratio. The renderer
calculates figure dimensions as:

```
fig_width = slot_width_in or 11.833  (content width)
fig_height = fig_width / aspect_ratio
```

Common values:
- `1.78` — 16:9, full-width chart slot
- `1.33` — 4:3, two-column chart
- `1.0` — square, pie/donut charts
- `2.67` — ultra-wide KPI tile

---

## 4. V2 Extension: Native Charts

When native PPTX charts are added in v2:

1. A new `chart_type_policy` field on `StyleTokens` will control whether a given chart type
   renders as PNG or native. Default remains PNG.

2. Native chart rendering will live in a separate module (`renderer/native_charts.py`) that
   builds `python-pptx` `ChartData` objects and adds them via `slide.shapes.add_chart()`.

3. The layout resolver will use `ResolvedElementKind.CHART` for both PNG and native charts.
   The exporter will branch on the presence of a `local_path` (PNG) vs a `chart_data` object
   (native) in the resolved element.

4. Native charts will NOT go through the asset manifest (they are embedded XML, not files).
   The manifest will record them with `source_type: "chart_native"` and `local_path: null`.

---

## 5. Decision Log

| Date | Decision | Author |
|---|---|---|
| 2026-04-06 | PNG-first for v1; native charts deferred to v2 | Product / Architecture |
