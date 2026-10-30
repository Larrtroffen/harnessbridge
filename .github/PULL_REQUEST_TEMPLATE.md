## What does this PR do?

<!-- One paragraph. Link issues: Fixes #123 -->

## Type of change

- [ ] New harness reader / writer / adapter (includes sanitized fixture + evidence level)
- [ ] Converter / CLI behavior
- [ ] macOS app (UI/UX/logic)
- [ ] Documentation / translations / assets
- [ ] Build, CI or release
- [ ] Tests only

## How was it tested?

<!-- Exact commands and results. Redact personal paths/session content. -->

```bash
python3 -m unittest discover -s tools/agent-session-import/tests -p 'test_*.py' -v
# app changes:
cd tools/HarnessBridgeApp && ./build.sh
tools/HarnessBridgeApp/dist/HarnessBridge.app/Contents/MacOS/HarnessBridge --self-test
```

- [ ] Tests use a temporary `HOME` + env-overridden stores (no real user store writes).
- [ ] No real session content, credentials or absolute personal paths are included.
- [ ] `docs/COMPATIBILITY.md` (and zh-CN) updated if harness support/evidence changed.
- [ ] `README` / `docs/` updated when user-facing behavior changed.

## Screenshots / logs (redacted)

<!-- Optional -->

## Notes for reviewers

<!-- Risk areas, migration safety implications, follow-ups -->
