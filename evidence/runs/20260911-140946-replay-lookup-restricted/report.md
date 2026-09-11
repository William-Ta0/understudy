# Replay of keystone.member.lookup_balance@1.0.0 on lakeshore

Run `rep-20260911-140946-a78b`. Every line below comes from `events.jsonl`; screenshots are masked before capture.

| t (s) | event |
|---:|---|
| 0.45 | · run_started: capability=keystone.member.lookup_balance, version=1.0.0, content_hash=sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3, lifecycle=approved, tenant=lakeshore, product_version=7.2.4, inputs={'member_id': '100777'}, supervised=False |
| 0.45 | · sign_on_started: tenant=lakeshore, attempt=1 |
| 1.20 | 🔑 sign_on_completed: screen=workstation_home |
| 1.21 | ▶ **click_member_inquiry** (click): Click on Member Inquiry button to access member lookup functionality |
| 1.28 |   · click |
| 1.54 | ▶ **enter_member_number** (fill): Enter the member ID in the Member Number field to search for the member record. |
| 1.58 |   · fill 100777 |
| 1.98 | ▶ **click_search** (click): Click the Search button to find the member record with the entered member number. |
| 2.03 |   · click |
| 2.32 | ▶ **read_member_detail** (extract): Read the declared outputs from the screen |
| 2.34 | ⚑ runtime condition `member_restricted` (business): *** ACCOUNT RESTRICTED: FRAUD ALERT - REFER TO BSA OFFICER *** |
| 2.38 | ◆ business outcome **MEMBER_RESTRICTED**: *** ACCOUNT RESTRICTED: FRAUD ALERT - REFER TO BSA OFFICER *** |
| 2.38 | ■ **run finished**: status=business_outcome, outcome=MEMBER_RESTRICTED, duration_ms=1933 |

## Result (as persisted: masked outputs are placeholders + fingerprints)

```json
{
  "run_id": "rep-20260911-140946-a78b",
  "capability": {
    "id": "keystone.member.lookup_balance",
    "version": "1.0.0",
    "content_hash": "sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3"
  },
  "tenant": "lakeshore",
  "status": "business_outcome",
  "outcome": {
    "code": "MEMBER_RESTRICTED",
    "description": "The member record is restricted and balances are withheld. Refer the request to a supervisor.",
    "condition": "member_restricted",
    "message": "*** ACCOUNT RESTRICTED: FRAUD ALERT - REFER TO BSA OFFICER ***",
    "step_id": "read_member_detail",
    "retryable": false
  },
  "recoveries": [],
  "warnings": [],
  "interventions": [],
  "steps": [
    {
      "id": "click_member_inquiry",
      "status": "done",
      "duration_ms": 337,
      "locator": "role=button name=\"Member Inquiry\""
    },
    {
      "id": "enter_member_number",
      "status": "done",
      "duration_ms": 440,
      "locator": "label=\"Member Number\" role=textbox"
    },
    {
      "id": "click_search",
      "status": "done",
      "duration_ms": 333,
      "locator": "role=button name=\"Search\""
    }
  ],
  "started_at": "2026-09-11T06:09:47.414180Z",
  "finished_at": "2026-09-11T06:09:49.347253Z",
  "duration_ms": 1933,
  "evidence_dir": "/Users/williammac/Desktop/project/understudy/evidence/runs/20260911-140946-replay-lookup-restricted"
}
```
