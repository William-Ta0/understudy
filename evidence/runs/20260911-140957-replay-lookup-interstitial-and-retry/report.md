# Replay of keystone.member.lookup_balance@1.0.0 on lakeshore

Run `rep-20260911-140957-363b`. Every line below comes from `events.jsonl`; screenshots are masked before capture.

| t (s) | event |
|---:|---|
| 0.46 | · run_started: capability=keystone.member.lookup_balance, version=1.0.0, content_hash=sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3, lifecycle=approved, tenant=lakeshore, product_version=7.2.4, inputs={'member_id': '100234'}, supervised=False |
| 0.46 | · sign_on_started: tenant=lakeshore, attempt=1 |
| 1.22 | 🔑 sign_on_completed: screen=workstation_home |
| 1.23 | ▶ **click_member_inquiry** (click): Click on Member Inquiry button to access member lookup functionality |
| 1.31 |   · click |
| 1.58 | ▶ **enter_member_number** (fill): Enter the member ID in the Member Number field to search for the member record. |
| 1.63 |   · fill 100234 |
| 2.03 | ▶ **click_search** (click): Click the Search button to find the member record with the entered member number. |
| 2.07 |   · click |
| 2.37 | ⚑ runtime condition `host_timeout` (recoverable): KC-HOST-0103: Host communication timeout. |
| 2.63 | ↻ recovery for `host_timeout`: click (attempt 1) |
| 3.48 | ⚑ runtime condition `system_notice` (recoverable): System Notice |
| 3.73 | ↻ recovery for `system_notice`: click (attempt 1) |
| 4.33 | ▶ **read_member_detail** (extract): Read the declared outputs from the screen |
| 4.35 | ⇥ output `member_name` via label="Name" role=cell: {"redacted": "pii", "fp": "hmac:7bdae3f3680cb3c0"} |
| 4.36 | ⇥ output `savings_balance` via table_cell column="Current Balance" row[Description=Share Savings]: {"redacted": "financial", "fp": "hmac:3667b28d4af5ffb7"} |
| 4.36 | ⇥ output `available_balance` via table_cell column="Available Balance" row[Description=Share Savings]: {"redacted": "financial", "fp": "hmac:27ca2ab3c5810eac"} |
| 4.41 | ✓ success checkpoint: screen member_detail |
| 4.41 | ■ **run finished**: status=succeeded, duration_ms=3948 |

## Result (as persisted: masked outputs are placeholders + fingerprints)

```json
{
  "run_id": "rep-20260911-140957-363b",
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
      "condition": "host_timeout",
      "step_id": "click_search",
      "action": "click",
      "attempt": 1,
      "at": "2026-09-11T06:09:59.756667Z"
    },
    {
      "condition": "system_notice",
      "step_id": "click_search",
      "action": "click",
      "attempt": 1,
      "at": "2026-09-11T06:10:00.864392Z"
    }
  ],
  "warnings": [],
  "interventions": [],
  "steps": [
    {
      "id": "click_member_inquiry",
      "status": "done",
      "duration_ms": 353,
      "locator": "role=button name=\"Member Inquiry\""
    },
    {
      "id": "enter_member_number",
      "status": "done",
      "duration_ms": 447,
      "locator": "label=\"Member Number\" role=textbox"
    },
    {
      "id": "click_search",
      "status": "done",
      "duration_ms": 2296,
      "locator": "role=button name=\"Search\""
    },
    {
      "id": "read_member_detail",
      "status": "done",
      "duration_ms": 35
    }
  ],
  "started_at": "2026-09-11T06:09:57.589455Z",
  "finished_at": "2026-09-11T06:10:01.537330Z",
  "duration_ms": 3948,
  "evidence_dir": "/Users/williammac/Desktop/project/understudy/evidence/runs/20260911-140957-replay-lookup-interstitial-and-retry"
}
```
