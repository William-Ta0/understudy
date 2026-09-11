# Replay of keystone.member.lookup_balance@1.0.0 on pinecrest

Run `rep-20260911-141009-7d88`. Every line below comes from `events.jsonl`; screenshots are masked before capture.

| t (s) | event |
|---:|---|
| 0.47 | · run_started: capability=keystone.member.lookup_balance, version=1.0.0, content_hash=sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3, lifecycle=approved, tenant=pinecrest, product_version=7.2.6, inputs={'member_id': '100234'}, overrides=['capability-level tenant vocabulary and overrides di |
| 0.47 | · sign_on_started: tenant=pinecrest, attempt=1 |
| 1.24 | ⚑ runtime condition `daily_bulletin` (recoverable): Daily Security Bulletin |
| 1.50 | ↻ recovery for `daily_bulletin`: click (attempt 1) |
| 2.09 | 🔑 sign_on_completed: screen=workstation_home |
| 2.09 | ▶ **click_member_inquiry** (click): Click on Member Inquiry button to access member lookup functionality |
| 2.12 | ≈ locator drift at `click_member_inquiry`: primary role=button name="Member Inquiry" missed, used attr onclick=contains:mbrinq.asp |
| 2.15 |   · click |
| 2.42 | ▶ **enter_member_number** (fill): Enter the member ID in the Member Number field to search for the member record. |
| 2.45 | ≈ locator drift at `enter_member_number`: primary label="Member Number" role=textbox missed, used attr name=txtMbrNo |
| 2.46 |   · fill 100234 |
| 2.86 | ▶ **click_search** (click): Click the Search button to find the member record with the entered member number. |
| 2.91 |   · click |
| 3.21 | ▶ **read_member_detail** (extract): Read the declared outputs from the screen |
| 3.23 | ⇥ output `member_name` via label="Name" role=cell: {"redacted": "pii", "fp": "hmac:7bdae3f3680cb3c0"} |
| 18.32 | ✗ failure **TARGET_NOT_FOUND** at `read_member_detail`: could not find output 'savings_balance' ("Current Balance" cell of the row where Description = Share Savings in the main frame) - expected: table_cell column="Current Balance" row[Description=Share Savings]; observed: screen=member_detail, frames={'top': '/t/pinecrest/default.asp', 'banner': '/t/pinecrest/banner.asp', 'nav': '/t/pinecrest/menu.asp', 'main': '/t/pinecrest/mbrdtl.asp?m=100234&_k=474c599b'} [screenshot](screens/001-failure-target_not_found.png) [ui_map](ui/0024-failure.txt) |
| 18.32 | ■ **run finished**: status=failed, failure=TARGET_NOT_FOUND, duration_ms=17848 |

## Result (as persisted: masked outputs are placeholders + fingerprints)

```json
{
  "run_id": "rep-20260911-141009-7d88",
  "capability": {
    "id": "keystone.member.lookup_balance",
    "version": "1.0.0",
    "content_hash": "sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3"
  },
  "tenant": "pinecrest",
  "status": "failed",
  "failure": {
    "code": "TARGET_NOT_FOUND",
    "message": "could not find output 'savings_balance' (\"Current Balance\" cell of the row where Description = Share Savings in the main frame)",
    "step_id": "read_member_detail",
    "step_index": 3,
    "expected": "table_cell column=\"Current Balance\" row[Description=Share Savings]",
    "observed": "screen=member_detail, frames={'top': '/t/pinecrest/default.asp', 'banner': '/t/pinecrest/banner.asp', 'nav': '/t/pinecrest/menu.asp', 'main': '/t/pinecrest/mbrdtl.asp?m=100234&_k=474c599b'}",
    "retryable": false,
    "evidence": {
      "screenshot": "screens/001-failure-target_not_found.png",
      "ui_map": "ui/0024-failure.txt"
    },
    "details": {
      "output": "savings_balance",
      "matches_per_locator": [
        0
      ],
      "state": {
        "screen": "member_detail",
        "frames": {
          "top": "/t/pinecrest/default.asp",
          "banner": "/t/pinecrest/banner.asp",
          "nav": "/t/pinecrest/menu.asp",
          "main": "/t/pinecrest/mbrdtl.asp?m=100234&_k=474c599b"
        },
        "heading": "Member Detail - 100234"
      }
    }
  },
  "recoveries": [
    {
      "condition": "daily_bulletin",
      "step_id": "sign_on",
      "action": "click",
      "attempt": 1,
      "at": "2026-09-11T06:10:11.051212Z"
    }
  ],
  "warnings": [
    {
      "kind": "override_applied",
      "message": "capability-level tenant vocabulary and overrides disabled for this run",
      "details": {}
    },
    {
      "kind": "locator_drift",
      "step_id": "click_member_inquiry",
      "message": "primary locator missed (role=button name=\"Member Inquiry\"); resolved by fallback #1 (attr onclick=contains:mbrinq.asp)",
      "details": {
        "primary": "role=button name=\"Member Inquiry\"",
        "used": "attr onclick=contains:mbrinq.asp",
        "matches": [
          0,
          1
        ]
      }
    },
    {
      "kind": "locator_drift",
      "step_id": "enter_member_number",
      "message": "primary locator missed (label=\"Member Number\" role=textbox); resolved by fallback #1 (attr name=txtMbrNo)",
      "details": {
        "primary": "label=\"Member Number\" role=textbox",
        "used": "attr name=txtMbrNo",
        "matches": [
          0,
          1,
          1
        ]
      }
    }
  ],
  "interventions": [],
  "steps": [
    {
      "id": "click_member_inquiry",
      "status": "done",
      "duration_ms": 330,
      "locator": "attr onclick=contains:mbrinq.asp"
    },
    {
      "id": "enter_member_number",
      "status": "done",
      "duration_ms": 435,
      "locator": "attr name=txtMbrNo"
    },
    {
      "id": "click_search",
      "status": "done",
      "duration_ms": 344,
      "locator": "role=button name=\"Search\""
    }
  ],
  "started_at": "2026-09-11T06:10:10.023208Z",
  "finished_at": "2026-09-11T06:10:27.871116Z",
  "duration_ms": 17848,
  "evidence_dir": "/Users/williammac/Desktop/project/understudy/evidence/runs/20260911-141009-replay-pinecrest-no-vocabulary"
}
```
