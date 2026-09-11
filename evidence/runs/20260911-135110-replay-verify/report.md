# Verification replay of keystone.member.lookup_balance@1.0.0

Run `rep-20260911-135110-03ee`. Every line below comes from `events.jsonl`; screenshots are masked before capture.

| t (s) | event |
|---:|---|
| 0.49 | · run_started: capability=keystone.member.lookup_balance, version=1.0.0, content_hash=sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3, lifecycle=draft, tenant=lakeshore, product_version=7.2.4, inputs={'member_id': '100234'}, supervised=False |
| 0.49 | · sign_on_started: tenant=lakeshore, attempt=1 |
| 1.24 | 🔑 sign_on_completed: screen=workstation_home |
| 1.24 | ▶ **click_member_inquiry** (click): Click on Member Inquiry button to access member lookup functionality |
| 1.42 |   · click |
| 1.74 | ▶ **enter_member_number** (fill): Enter the member ID in the Member Number field to search for the member record. |
| 1.83 |   · fill 100234 |
| 2.22 | ▶ **click_search** (click): Click the Search button to find the member record with the entered member number. |
| 2.37 |   · click |
| 2.69 | ▶ **read_member_detail** (extract): Read the declared outputs from the screen |
| 2.71 | ⇥ output `member_name` via label="Name" role=cell: {"redacted": "pii", "fp": "hmac:7bdae3f3680cb3c0"} |
| 2.72 | ⇥ output `savings_balance` via table_cell column="Current Balance" row[Description=Share Savings]: {"redacted": "financial", "fp": "hmac:3667b28d4af5ffb7"} |
| 2.72 | ⇥ output `available_balance` via table_cell column="Available Balance" row[Description=Share Savings]: {"redacted": "financial", "fp": "hmac:27ca2ab3c5810eac"} |
| 2.77 | ✓ success checkpoint: screen member_detail |
| 2.77 | ■ **run finished**: status=succeeded, duration_ms=2278 |

## Result (as persisted: masked outputs are placeholders + fingerprints)

```json
{
  "run_id": "rep-20260911-135110-03ee",
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
  "recoveries": [],
  "warnings": [],
  "interventions": [],
  "steps": [
    {
      "id": "click_member_inquiry",
      "status": "done",
      "duration_ms": 505,
      "locator": "role=button name=\"Member Inquiry\""
    },
    {
      "id": "enter_member_number",
      "status": "done",
      "duration_ms": 473,
      "locator": "label=\"Member Number\" role=textbox"
    },
    {
      "id": "click_search",
      "status": "done",
      "duration_ms": 466,
      "locator": "role=button name=\"Search\""
    },
    {
      "id": "read_member_detail",
      "status": "done",
      "duration_ms": 37
    }
  ],
  "started_at": "2026-09-11T05:51:10.928645Z",
  "finished_at": "2026-09-11T05:51:13.207110Z",
  "duration_ms": 2278,
  "evidence_dir": "/Users/williammac/Desktop/project/understudy/evidence/runs/20260911-135110-replay-verify"
}
```
