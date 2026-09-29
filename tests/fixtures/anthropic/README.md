# Anthropic response fixtures

Every file here is a **documented shape, not recorded**: built by hand from the response shapes in
Anthropic's docs (Messages API, preserved thinking, stop reasons, errors), checked 2026-09-29.
None was captured from the live API.

| File | Shape |
|---|---|
| `thinking_text.json` | documented shape, not recorded |
| `tool_use.json` | documented shape, not recorded |
| `redacted_and_unmodeled_blocks.json` | documented shape, not recorded (`future_block` is invented) |
| `refusal.json` | documented shape, not recorded |
| `unknown_stop_reason.json` | documented shape, not recorded (`budget_exhausted` is invented) |
| `prefix_mismatch_400.json` | documented shape, not recorded (message text from the preserved-thinking docs) |

Phase 2 task 5a replaces the ones a live run can produce with recorded, redacted responses. Mark
each replaced file here as "recorded <date>, redacted".
