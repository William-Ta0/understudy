# Evidence

Every folder under `runs/` is one run, recorded by the system itself. What each file holds:

| file | contents |
|---|---|
| `events.jsonl` | Structured log: one JSON object per event, with actor (`system` / `agent` / `human`), type, and data. Redacted as it is written. |
| `report.md` | The same log as a readable timeline, with links to screenshots. **Start here.** |
| `result.json` | The replay result as persisted. Masked outputs are placeholders plus fingerprints; the caller gets the real values in memory. |
| `screens/*.png` | Screenshots, with pii, financial and secret regions blacked out *before* capture. |
| `ui/*.txt` | The text UI map that was on screen (redacted). Discovery saves one per turn; replay saves one on failure. |
| `trace.json` | Discovery only. The structured trace the compiler consumed. |
| `capability.yaml` | Discovery only. The capability exactly as the compiler emitted it. |
| `intervention-*.json` | The intervention request routed to a human, and its resolution, including the captured human actions. |

All member data is synthetic, from the Keystone Core mock. A test (`tests/test_zz_no_leaks.py`) scans every file here for that data and fails on any hit.

## Discovery: a real model driving the live UI

| run | what happened |
|---|---|
| [`20260911-134955-discovery-lookup_balance`](runs/20260911-134955-discovery-lookup_balance/report.md) | **GLM-4.6V**, multimodal (masked screenshot plus UI map each turn). 7 model calls, about 30k input / 1.5k output tokens. It opened Member Inquiry from a `<td onclick>` menu, typed `{{inputs.member_id}}`, searched, and pointed at the name and at the two balance cells in the accounts grid. The run compiled into [`keystone.member.lookup_balance@1.0.0`](../capabilities/keystone.member.lookup_balance/1.0.0.yaml). |
| [`20260911-135110-replay-verify`](runs/20260911-135110-replay-verify/report.md) | The compiler's verification: that capability replayed once with no model and succeeded, and the capability became `verified`. |
| [`20260911-135207-discovery-open_share_account`](runs/20260911-135207-discovery-open_share_account/report.md) | **GLM-5.3**, text-only (UI map, no screenshots). 17 model calls, about 54k input / 7k output tokens. Details below the table. |
| [`20260911-135930-replay-verify`](runs/20260911-135930-replay-verify/report.md) | Verification of `open_share_account`. It replayed up to the irreversible step, confirmed that step's target resolves, and stopped without committing (`verification_stop`). |

The `open_share_account` discovery went like this:
1. The model first clicked the wrong menu item. The compiler pruned that as a detour and left a review note.
2. It found the member, filled the four-field form using input placeholders, reached the review screen, and read the dividend rate.
3. It called `request_human(kind=approval)`, because policy blocks irreversible actions for the model.
4. A person approved **through the operator console UI in a browser**: took control, clicked *Confirm & Open Account* in the live view, and handed back with `completed`. This operator is recorded as `console-operator`; it was not the scripted operator.
5. The agent then read the confirmation number and the new suffix.
6. The human's click was captured, compiled into an irreversible, approval-gated `origin: human` step, and saved as [`keystone.member.open_share_account@1.0.0`](../capabilities/keystone.member.open_share_account/1.0.0.yaml).

## Replay: deterministic, no model

Produced by [`scripts/demo_replays.sh`](../scripts/demo_replays.sh), plus the approval gate and the agent-facing runs. Faults were injected into the mock over its control endpoint. The replay engine had to *detect* each one from the screen.

| run | scenario | result |
|---|---|---|
| [`lookup-success`](runs/20260911-140940-replay-lookup-success/report.md) | Production mode (`--require-approved`) on the tenant it was discovered on | `succeeded` in about 2 s; outputs stored as placeholders plus fingerprints |
| [`lookup-not-found`](runs/20260911-140943-replay-lookup-not-found/report.md) | Member 999999 | `business_outcome` **MEMBER_NOT_FOUND**, with the app's own message |
| [`lookup-restricted`](runs/20260911-140946-replay-lookup-restricted/report.md) | Member with a fraud-alert restriction | `business_outcome` **MEMBER_RESTRICTED** |
| [`lookup-invalid-input`](runs/20260911-140950-replay-lookup-invalid-input/report.md) | `member_id=12ab` | `failed` **INVALID_INPUT** before the browser was touched (0 steps) |
| [`lookup-session-expired`](runs/20260911-140951-replay-lookup-session-expired/report.md) | Session killed on the search POST | `succeeded`: detected `session_expired`, signed on again, restarted from the entry screen |
| [`lookup-interstitial-and-retry`](runs/20260911-140957-replay-lookup-interstitial-and-retry/report.md) | Host timeout on the search POST, then a maintenance notice on the detail page | `succeeded`, with 2 recoveries: clicked Retry, then Acknowledge |
| [`lookup-app-error`](runs/20260911-141002-replay-lookup-app-error/report.md) | Server error page | `failed` **APP_ERROR** at `click_search`, with the expected and observed state, a masked screenshot, a UI map, and `retryable: true` |
| [`pinecrest-with-vocabulary`](runs/20260911-141005-replay-pinecrest-with-vocabulary/report.md) | The same capability on the second tenant (relabelled fields, renamed product and column, mandatory bulletin) | `succeeded`: the tenant vocabulary was applied, and the bulletin was handled as a tenant runtime condition |
| [`pinecrest-no-vocabulary`](runs/20260911-141009-replay-pinecrest-no-vocabulary/report.md) | Same, with the tenant's capability layer disabled (`--no-overrides`) | Navigation survived on vendor-level fallbacks (2 `locator_drift` warnings), then `failed` **TARGET_NOT_FOUND** on the balance read. Reads never fall back. |
| [`open-not-approved`](runs/20260911-141401-replay-open-not-approved/report.md) | Production mode on a capability that is verified but not yet approved | `failed` **NOT_APPROVED** |
| [`open-unsupervised`](runs/20260911-141028-replay-open-unsupervised/report.md) | Write flow with no human attached | `failed` **POLICY_BLOCKED** at the irreversible step; nothing committed |
| [`open-approved`](runs/20260911-141403-replay-open-approved/report.md) | Supervised; the operator approves | Paused for approval, the operator approved, the automation clicked Confirm; `succeeded` with the confirmation number |
| [`open-supervisor-override`](runs/20260911-163958-replay-open-supervisor-override/report.md) | Deposit above the teller limit | A `human_required` condition paused the run. A supervisor claimed the live session, typed their ID and override code (captured as `[secret]`), and pressed Submit, then handed back. The automation re-synced, reached the approval gate, got approval, and `succeeded`. |
| [`open-deposit-rejected`](runs/20260911-141056-replay-open-deposit-rejected/report.md) | Deposit below the product minimum | `business_outcome` **DEPOSIT_REJECTED** |

The approval and supervisor runs use the **simulated operator** (`examples/operators/*.yaml`, operators `ops.jlee` and `sup.kim`). It drives the real operator console over HTTP, and its actions go through the same page-level capture a person's would.

## As a tool for an AI agent

| run | what happened |
|---|---|
| [`agent-ask`](runs/20260911-141103-agent-ask/events.jsonl) → [`replay-via-agent`](runs/20260911-141111-replay-via-agent/report.md) | Question: *"How much can member 100234 at Lakeshore withdraw from their savings right now?"* GLM-5.3 was given the capability catalog. It called `keystone__member__lookup_balance(tenant="lakeshore", member_id="100234")`, got the typed outputs, and answered with the available balance. The persisted answer is redacted. |
| [`agent-ask`](runs/20260911-141122-agent-ask/events.jsonl) → [`replay-via-agent`](runs/20260911-141129-replay-via-agent/report.md) | Member 999999. The agent received `MEMBER_NOT_FOUND` and explained it to the user as an answer, not an error. |
