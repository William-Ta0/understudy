# Replay of keystone.member.lookup_balance@1.0.0 on lakeshore

Run `rep-20260911-140943-c409`. Every line below comes from `events.jsonl`; screenshots are masked before capture.

| t (s) | event |
|---:|---|
| 0.45 | · run_started: capability=keystone.member.lookup_balance, version=1.0.0, content_hash=sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3, lifecycle=approved, tenant=lakeshore, product_version=7.2.4, inputs={'member_id': '999999'}, supervised=False |
| 0.45 | · sign_on_started: tenant=lakeshore, attempt=1 |
| 1.21 | 🔑 sign_on_completed: screen=workstation_home |
| 1.22 | ▶ **click_member_inquiry** (click): Click on Member Inquiry button to access member lookup functionality |
| 1.29 |   · click |
| 1.56 | ▶ **enter_member_number** (fill): Enter the member ID in the Member Number field to search for the member record. |
| 1.60 |   · fill 999999 |
| 2.00 | ▶ **click_search** (click): Click the Search button to find the member record with the entered member number. |
| 2.05 |   · click |
| 2.36 | ⚑ runtime condition `record_not_found` (business): No records match your search criteria. |
| 2.40 | ◆ business outcome **MEMBER_NOT_FOUND**: No records match your search criteria. |
| 2.40 | ■ **run finished**: status=business_outcome, outcome=MEMBER_NOT_FOUND, duration_ms=1953 |

## Result (as persisted: masked outputs are placeholders + fingerprints)

```json
{
  "run_id": "rep-20260911-140943-c409",
  "capability": {
    "id": "keystone.member.lookup_balance",
    "version": "1.0.0",
    "content_hash": "sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3"
  },
  "tenant": "lakeshore",
  "status": "business_outcome",
  "outcome": {
    "code": "MEMBER_NOT_FOUND",
    "description": "No member has this member number.",
    "condition": "record_not_found",
    "message": "No records match your search criteria.",
    "step_id": "click_search",
    "retryable": false
  },
  "recoveries": [],
  "warnings": [],
  "interventions": [],
  "steps": [
    {
      "id": "click_member_inquiry",
      "status": "done",
      "duration_ms": 340,
      "locator": "role=button name=\"Member Inquiry\""
    },
    {
      "id": "enter_member_number",
      "status": "done",
      "duration_ms": 447,
      "locator": "label=\"Member Number\" role=textbox"
    }
  ],
  "started_at": "2026-09-11T06:09:44.319117Z",
  "finished_at": "2026-09-11T06:09:46.273035Z",
  "duration_ms": 1953,
  "evidence_dir": "/Users/williammac/Desktop/project/understudy/evidence/runs/20260911-140943-replay-lookup-not-found"
}
```
