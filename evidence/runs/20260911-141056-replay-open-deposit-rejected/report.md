# Replay of keystone.member.open_share_account@1.0.0 on lakeshore

Run `rep-20260911-141056-ffd7`. Every line below comes from `events.jsonl`; screenshots are masked before capture.

| t (s) | event |
|---:|---|
| 0.44 | · run_started: capability=keystone.member.open_share_account, version=1.0.0, content_hash=sha256:ac1a88a3ec2072ae7bab01cc4145b66be1ed911cede496d8e35f04312851bdd4, lifecycle=verified, tenant=lakeshore, product_version=7.2.4, inputs={'member_id': '104410', 'product': 'Money Market Share', 'nickname': 'Rainy day fund |
| 0.45 | · sign_on_started: tenant=lakeshore, attempt=1 |
| 1.15 | 🔑 sign_on_completed: screen=workstation_home |
| 1.16 | ▶ **click_member_inquiry** (click): Open Member Inquiry to select the member first, as required by the Open Sub-Account screen |
| 1.24 |   · click |
| 1.51 | ▶ **enter_member_number** (fill): Enter the member number to look up the member record |
| 1.56 |   · fill 104410 |
| 1.96 | ▶ **click_search** (click): Submit the member inquiry search to retrieve member {{inputs.member_id}} |
| 2.00 |   · click |
| 2.30 | ▶ **click_open_sub_account** (click): Open the new sub-account form for this member, from the member detail screen |
| 2.35 |   · click |
| 2.64 | ▶ **choose_product** (select): Select the share product to open, from the declared input |
| 2.67 |   · select Money Market Share |
| 3.07 | ▶ **enter_account_nickname** (fill): Enter the member-facing account nickname for the new sub-account. |
| 3.10 |   · fill Rainy day fund |
| 3.52 | ▶ **enter_opening_deposit** (fill): Enter the opening deposit amount for the new sub-account |
| 3.54 |   · fill [financial:opening_deposit] |
| 3.97 | ▶ **choose_fund_from** (select): Choose the member's funding account by suffix for the opening deposit |
| 4.00 |   · select 00 |
| 4.42 | ▶ **click_continue** (click): Submit the sub-account opening form to reach the review screen |
| 4.46 |   · click |
| 4.76 | ⚑ runtime condition `validation_error` (business): Opening deposit of $[financial:opening_deposit] is below the minimum of [amount] for Money Market Share. |
| 4.81 | ◆ business outcome **DEPOSIT_REJECTED**: Opening deposit of $[financial:opening_deposit] is below the minimum of [amount] for Money Market Share. |
| 4.81 | ■ **run finished**: status=business_outcome, outcome=DEPOSIT_REJECTED, duration_ms=4367 |

## Result (as persisted: masked outputs are placeholders + fingerprints)

```json
{
  "run_id": "rep-20260911-141056-ffd7",
  "capability": {
    "id": "keystone.member.open_share_account",
    "version": "1.0.0",
    "content_hash": "sha256:ac1a88a3ec2072ae7bab01cc4145b66be1ed911cede496d8e35f04312851bdd4"
  },
  "tenant": "lakeshore",
  "status": "business_outcome",
  "outcome": {
    "code": "DEPOSIT_REJECTED",
    "description": "The application rejected the product, deposit, or funding account (message says why).",
    "condition": "validation_error",
    "message": "Opening deposit of $[financial:opening_deposit] is below the minimum of [amount] for Money Market Share.",
    "step_id": "click_continue",
    "retryable": false
  },
  "recoveries": [],
  "warnings": [],
  "interventions": [],
  "steps": [
    {
      "id": "click_member_inquiry",
      "status": "done",
      "duration_ms": 354,
      "locator": "role=button name=\"Member Inquiry\""
    },
    {
      "id": "enter_member_number",
      "status": "done",
      "duration_ms": 445,
      "locator": "label=\"Member Number\" role=textbox"
    },
    {
      "id": "click_search",
      "status": "done",
      "duration_ms": 344,
      "locator": "role=button name=\"Search\""
    },
    {
      "id": "click_open_sub_account",
      "status": "done",
      "duration_ms": 335,
      "locator": "role=link name=\"Open Sub-Account\""
    },
    {
      "id": "choose_product",
      "status": "done",
      "duration_ms": 433,
      "locator": "label=\"Product\" role=combobox"
    },
    {
      "id": "enter_account_nickname",
      "status": "done",
      "duration_ms": 446,
      "locator": "label=\"Account Nickname\" role=textbox"
    },
    {
      "id": "enter_opening_deposit",
      "status": "done",
      "duration_ms": 452,
      "locator": "label=\"Opening Deposit\" role=textbox"
    },
    {
      "id": "choose_fund_from",
      "status": "done",
      "duration_ms": 446,
      "locator": "label=\"Fund From\" role=combobox"
    }
  ],
  "started_at": "2026-09-11T06:10:57.377651Z",
  "finished_at": "2026-09-11T06:11:01.744824Z",
  "duration_ms": 4367,
  "evidence_dir": "/Users/williammac/Desktop/project/understudy/evidence/runs/20260911-141056-replay-open-deposit-rejected"
}
```
