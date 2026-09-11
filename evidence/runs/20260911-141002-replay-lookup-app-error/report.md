# Replay of keystone.member.lookup_balance@1.0.0 on lakeshore

Run `rep-20260911-141002-6714`. Every line below comes from `events.jsonl`; screenshots are masked before capture.

| t (s) | event |
|---:|---|
| 0.44 | · run_started: capability=keystone.member.lookup_balance, version=1.0.0, content_hash=sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3, lifecycle=approved, tenant=lakeshore, product_version=7.2.4, inputs={'member_id': '100234'}, supervised=False |
| 0.44 | · sign_on_started: tenant=lakeshore, attempt=1 |
| 1.14 | 🔑 sign_on_completed: screen=workstation_home |
| 1.15 | ▶ **click_member_inquiry** (click): Click on Member Inquiry button to access member lookup functionality |
| 1.22 |   · click |
| 1.49 | ▶ **enter_member_number** (fill): Enter the member ID in the Member Number field to search for the member record. |
| 1.53 |   · fill 100234 |
| 1.93 | ▶ **click_search** (click): Click the Search button to find the member record with the entered member number. |
| 1.97 |   · click |
| 2.27 | ⚑ runtime condition `server_error` (fatal): Server Error in '/Keystone' Application. |
| 2.33 | ✗ failure **APP_ERROR** at `click_search`: server_error: Unhandled server exception (ASP.NET yellow screen). - expected: None; observed: Server Error in '/Keystone' Application. / screen=None, frames={'top': '/t/lakeshore/default.asp', 'banner': '/t/lakeshore/banner.asp', 'nav': '/t/lakeshore/menu.asp', 'main': '/t/lakeshore/mbrdtl.asp?m=100234&_k=0c06f1d8'} [screenshot](screens/001-failure-app_error.png) [ui_map](ui/0018-failure.txt) |
| 2.33 | ■ **run finished**: status=failed, failure=APP_ERROR, duration_ms=1892 |

## Result (as persisted: masked outputs are placeholders + fingerprints)

```json
{
  "run_id": "rep-20260911-141002-6714",
  "capability": {
    "id": "keystone.member.lookup_balance",
    "version": "1.0.0",
    "content_hash": "sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3"
  },
  "tenant": "lakeshore",
  "status": "failed",
  "failure": {
    "code": "APP_ERROR",
    "message": "server_error: Unhandled server exception (ASP.NET yellow screen).",
    "step_id": "click_search",
    "step_index": 2,
    "observed": "Server Error in '/Keystone' Application. | screen=None, frames={'top': '/t/lakeshore/default.asp', 'banner': '/t/lakeshore/banner.asp', 'nav': '/t/lakeshore/menu.asp', 'main': '/t/lakeshore/mbrdtl.asp?m=100234&_k=0c06f1d8'}",
    "retryable": true,
    "evidence": {
      "screenshot": "screens/001-failure-app_error.png",
      "ui_map": "ui/0018-failure.txt"
    },
    "details": {
      "condition": "server_error",
      "code": "APP_ERROR",
      "state": {
        "screen": null,
        "frames": {
          "top": "/t/lakeshore/default.asp",
          "banner": "/t/lakeshore/banner.asp",
          "nav": "/t/lakeshore/menu.asp",
          "main": "/t/lakeshore/mbrdtl.asp?m=100234&_k=0c06f1d8"
        },
        "heading": "Server Error in '/Keystone' Application."
      }
    }
  },
  "recoveries": [],
  "warnings": [],
  "interventions": [],
  "steps": [
    {
      "id": "click_member_inquiry",
      "status": "done",
      "duration_ms": 343,
      "locator": "role=button name=\"Member Inquiry\""
    },
    {
      "id": "enter_member_number",
      "status": "done",
      "duration_ms": 441,
      "locator": "label=\"Member Number\" role=textbox"
    }
  ],
  "started_at": "2026-09-11T06:10:03.001452Z",
  "finished_at": "2026-09-11T06:10:04.894054Z",
  "duration_ms": 1892,
  "evidence_dir": "/Users/williammac/Desktop/project/understudy/evidence/runs/20260911-141002-replay-lookup-app-error"
}
```
