# Repo Health Check Learnings

Date: 2026-04-05

## Summary

This repo was moved from the old Desktop workspace into `C:\Users\jphit\.codex\Projects\Auto-PPT`.
The codebase itself appears present, but the move exposed environment and path drift that should be
treated as migration follow-up work.

## Confirmed Learnings

1. The repo-local Python environment did not move with the project.
   - `AGENTS.md` expects `.\.venv\Scripts\python.exe`.
   - `.venv` is not present in the current repo root.
   - Full Python verification is blocked until a local interpreter or `.venv` is restored.

2. The Codex shell environment does not currently resolve Python the same way as the interactive user shell.
   - In the Codex shell, `python`, `py`, and `.\.venv\Scripts\python.exe` were not executable.
   - This means repo health checks should distinguish code failures from shell/runtime drift.
   - After the repo-local `.venv` was recreated successfully from the user terminal, this shell still returned
     `Access is denied` when executing `.venv\Scripts\python.exe` and `.venv\Scripts\pytest.exe`.
   - The local environment may be healthy even when Codex cannot directly run the interpreter from its sandboxed shell.

3. Repo documentation and skill files contained stale absolute paths from the old Desktop location.
   - Several `Skills/*/SKILL.md` files still linked to `C:/Users/jphit/OneDrive/Desktop/Codex/Projects/Auto%20PPT/...`.
   - The README also referenced the old Desktop path.
   - These stale links were updated to the current `.codex\Projects\Auto-PPT` location.

4. The README referenced a missing setup file.
   - `README.md` pointed to `.env.example`, but that file is not present in the repo.
   - The guidance was corrected to instruct creating a local `.env` instead of copying a nonexistent template.

5. Frontend TypeScript appears structurally sound, but the full Vite build is not healthy in this environment.
   - `ui\node_modules\.bin\tsc.cmd --noEmit` completed successfully.
   - `npm.cmd run build` failed during Vite/esbuild startup with `spawn EPERM`.
   - This needs to be rechecked after the environment is stabilized.

6. PowerShell policy and transport behavior in this shell differ from the user terminal.
   - `npm.ps1` is blocked by execution policy, though `npm.cmd` can be used.
   - `Invoke-WebRequest` and `curl.exe` both hit environment-specific download issues during bootstrap attempts.
   - Bootstrap steps should prefer explicit executable paths and avoid assuming the shell matches the desktop terminal.

7. The repo now includes more than the original Python pipeline surface.
   - In addition to `pptx_gen/` and `tests/`, the repo includes a `ui/` frontend and `web/` output path expectations.
   - Health checks should cover both backend and frontend workflows after the Python runtime is restored.

8. `python -m pptx_gen.cli ...` had a real entrypoint bug.
   - `pptx_gen/cli.py` defined Click commands but did not call `cli()` under `if __name__ == "__main__":`.
   - Running `python -m pptx_gen.cli generate ...` exited successfully but produced no output and wrote no files.
   - This was fixed and covered by a regression test.

## Final Validation Status

- Backend test suite passes: `85 passed, 1 warning`.
- Frontend production build passes and emits the built app into `web/`.
- CLI smoke test passes and writes `out/sample.pptx` plus `out/sample_artifacts/`.
- Local server smoke test passes:
  - `GET /api/health` returns `200` with `{"status":"ok","phase":"1","ingest":true,"generation":"mock"}`
  - `GET /` returns `200` and serves HTML from the built frontend.
- Remaining warning is a third-party `chromadb` deprecation warning, not a repo move failure.

## Recommended Follow-Up

- Keep future repo docs and skill links relative where possible to avoid path breakage after moves.
- Treat `python -m pptx_gen.cli ...` as part of smoke coverage because tests that invoke Click directly will not catch missing module entrypoints.
- If the `chromadb` deprecation warning becomes noisy, pin or upgrade the dependency stack separately from move-related work.
