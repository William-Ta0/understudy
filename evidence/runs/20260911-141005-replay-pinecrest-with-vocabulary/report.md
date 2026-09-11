# Replay of keystone.member.lookup_balance@1.0.0 on pinecrest

Run `rep-20260911-141005-7aca`. Every line below comes from `events.jsonl`; screenshots are masked before capture.

| t (s) | event |
|---:|---|
| 0.44 | · run_started: capability=keystone.member.lookup_balance, version=1.0.0, content_hash=sha256:35f846d4ee6c00ef8d563711d25c5b0d0e0f6b7565015956cf04f1e9f1f93ded, lifecycle=approved, tenant=pinecrest, product_version=7.2.6, inputs={'member_id': '100234'}, overrides=['vocabulary: Current Balance -> Ledger Balance', 'vo |
| 0.44 | · sign_on_started: tenant=pinecrest, attempt=1 |
| 1.20 | ⚑ runtime condition `daily_bulletin` (recoverable): Daily Security Bulletin |
| 1.46 | ↻ recovery for `daily_bulletin`: click (attempt 1) |
| 2.08 | 🔑 sign_on_completed: screen=workstation_home |
| 2.08 | ▶ **click_member_inquiry** (click): Click on Member Inquiry button to access member lookup functionality |
| 2.14 |   · click |
| 2.42 | ▶ **enter_member_number** (fill): Enter the member ID in the Member Number field to search for the member record. |
| 2.46 |   · fill 100234 |
| 2.85 | ▶ **click_search** (click): Click the Search button to find the member record with the entered member number. |
| 2.91 |   · click |
| 3.20 | ▶ **read_member_detail** (extract): Read the declared outputs from the screen |
| 3.22 | ⇥ output `member_name` via label="Name" role=cell: {"redacted": "pii", "fp": "hmac:7bdae3f3680cb3c0"} |
| 3.23 | ⇥ output `savings_balance` via table_cell column="Ledger Balance" row[Description=Primary Savings]: {"redacted": "financial", "fp": "hmac:3667b28d4af5ffb7"} |
| 3.23 | ⇥ output `available_balance` via table_cell column="Available Balance" row[Description=Primary Savings]: {"redacted": "financial", "fp": "hmac:27ca2ab3c5810eac"} |
| 3.28 | ✓ success checkpoint: screen member_detail |
| 3.28 | ■ **run finished**: status=succeeded, duration_ms=2838 |

## Result (as persisted: masked outputs are placeholders + fingerprints)

```json
{
  "run_id": "rep-20260911-141005-7aca",
  "capability": {
    "id": "keystone.member.lookup_balance",
    "version": "1.0.0",
    "content_hash": "sha256:35f846d4ee6c00ef8d563711d25c5b0d0e0f6b7565015956cf04f1e9f1f93ded"
  },
  "tenant": "pinecrest",
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
      "condition": "daily_bulletin",
      "step_id": "sign_on",
      "action": "click",
      "attempt": 1,
      "at": "2026-09-11T06:10:07.044118Z"
    }
  ],
  "warnings": [
    {
      "kind": "override_applied",
      "message": "vocabulary: Current Balance -> Ledger Balance",
      "details": {}
    },
    {
      "kind": "override_applied",
      "message": "vocabulary: Member Inquiry -> Member Lookup",
      "details": {}
    },
    {
      "kind": "override_applied",
      "message": "vocabulary: Member Number -> Member #",
      "details": {}
    },
    {
      "kind": "override_applied",
      "message": "vocabulary: Share Savings -> Primary Savings",
      "details": {}
    }
  ],
  "interventions": [],
  "steps": [
    {
      "id": "click_member_inquiry",
      "status": "done",
      "duration_ms": 339,
      "locator": "role=button name=\"Member Lookup\""
    },
    {
      "id": "enter_member_number",
      "status": "done",
      "duration_ms": 438,
      "locator": "label=\"Member #\" role=textbox"
    },
    {
      "id": "click_search",
      "status": "done",
      "duration_ms": 341,
      "locator": "role=button name=\"Search\""
    },
    {
      "id": "read_member_detail",
      "status": "done",
      "duration_ms": 36
    }
  ],
  "started_at": "2026-09-11T06:10:06.024038Z",
  "finished_at": "2026-09-11T06:10:08.862741Z",
  "duration_ms": 2838,
  "evidence_dir": "/Users/williammac/Desktop/project/understudy/evidence/runs/20260911-141005-replay-pinecrest-with-vocabulary"
}
```
