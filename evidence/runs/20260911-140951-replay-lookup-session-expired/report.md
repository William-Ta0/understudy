# Replay of keystone.member.lookup_balance@1.0.0 on lakeshore

Run `rep-20260911-140951-1826`. Every line below comes from `events.jsonl`; screenshots are masked before capture.

| t (s) | event |
|---:|---|
| 0.44 | · run_started: capability=keystone.member.lookup_balance, version=1.0.0, content_hash=sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3, lifecycle=approved, tenant=lakeshore, product_version=7.2.4, inputs={'member_id': '100234'}, supervised=False |
| 0.44 | · sign_on_started: tenant=lakeshore, attempt=1 |
| 1.16 | 🔑 sign_on_completed: screen=workstation_home |
| 1.17 | ▶ **click_member_inquiry** (click): Click on Member Inquiry button to access member lookup functionality |
| 1.25 |   · click |
| 1.52 | ▶ **enter_member_number** (fill): Enter the member ID in the Member Number field to search for the member record. |
| 1.56 |   · fill 100234 |
| 1.97 | ▶ **click_search** (click): Click the Search button to find the member record with the entered member number. |
| 2.02 |   · click |
| 2.32 | ⚑ runtime condition `session_expired` (recoverable): Your Keystone session has expired due to inactivity. |
| 2.32 | ↻ recovery for `session_expired`: relogin (attempt 1) |
| 2.32 | · sign_on_started: tenant=lakeshore, attempt=2 |
| 2.99 | 🔑 sign_on_completed: screen=workstation_home |
| 2.99 | ↺ flow_restarted: reason=session re-established, restart=1 |
| 3.00 | ▶ **click_member_inquiry** (click): Click on Member Inquiry button to access member lookup functionality |
| 3.08 |   · click |
| 3.35 | ▶ **enter_member_number** (fill): Enter the member ID in the Member Number field to search for the member record. |
| 3.40 |   · fill 100234 |
| 3.79 | ▶ **click_search** (click): Click the Search button to find the member record with the entered member number. |
| 3.84 |   · click |
| 4.14 | ▶ **read_member_detail** (extract): Read the declared outputs from the screen |
| 4.17 | ⇥ output `member_name` via label="Name" role=cell: {"redacted": "pii", "fp": "hmac:7bdae3f3680cb3c0"} |
| 4.17 | ⇥ output `savings_balance` via table_cell column="Current Balance" row[Description=Share Savings]: {"redacted": "financial", "fp": "hmac:3667b28d4af5ffb7"} |
| 4.18 | ⇥ output `available_balance` via table_cell column="Available Balance" row[Description=Share Savings]: {"redacted": "financial", "fp": "hmac:27ca2ab3c5810eac"} |
| 4.23 | ✓ success checkpoint: screen member_detail |
| 4.23 | ■ **run finished**: status=succeeded, duration_ms=3784 |

## Result (as persisted: masked outputs are placeholders + fingerprints)

```json
{
  "run_id": "rep-20260911-140951-1826",
  "capability": {
    "id": "keystone.member.lookup_balance",
    "version": "1.0.0",
    "content_hash": "sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3"
  },
  "tenant": "lakeshore",
  "status": "succeeded",
  "outputs": {
    "member_name": {
      "redacted": "pii",
      "fp": "hmac:7bdae3f3680cb3c0"
    },
    "savings_balance": {
      "redacted": "financial",
      "fp": "hmac:3667b28d4af5ffb7"
    },
    "available_balance": {
      "redacted": "financial",
      "fp": "hmac:27ca2ab3c5810eac"
    }
  },
  "recoveries": [
    {
      "condition": "session_expired",
      "step_id": "click_search",
      "action": "relogin",
      "attempt": 1,
      "at": "2026-09-11T06:09:53.857838Z"
    }
  ],
  "warnings": [],
  "interventions": [],
  "steps": [
    {
      "id": "click_member_inquiry",
      "status": "done",
      "duration_ms": 352,
      "locator": "role=button name=\"Member Inquiry\""
    },
    {
      "id": "enter_member_number",
      "status": "done",
      "duration_ms": 449,
      "locator": "label=\"Member Number\" role=textbox"
    },
    {
      "id": "click_member_inquiry",
      "status": "done",
      "duration_ms": 354,
      "locator": "role=button name=\"Member Inquiry\""
    },
    {
      "id": "enter_member_number",
      "status": "done",
      "duration_ms": 443,
      "locator": "label=\"Member Number\" role=textbox"
    },
    {
      "id": "click_search",
      "status": "done",
      "duration_ms": 349,
      "locator": "role=button name=\"Search\""
    },
    {
      "id": "read_member_detail",
      "status": "done",
      "duration_ms": 35
    }
  ],
  "started_at": "2026-09-11T06:09:51.984027Z",
  "finished_at": "2026-09-11T06:09:55.767625Z",
  "duration_ms": 3784,
  "evidence_dir": "/Users/williammac/Desktop/project/understudy/evidence/runs/20260911-140951-replay-lookup-session-expired"
}
```
