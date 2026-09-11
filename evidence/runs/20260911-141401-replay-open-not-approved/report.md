# Replay of keystone.member.open_share_account@1.0.0 on lakeshore

Run `rep-20260911-141401-0ad9`. Every line below comes from `events.jsonl`; screenshots are masked before capture.

| t (s) | event |
|---:|---|
| 0.82 | · run_started: capability=keystone.member.open_share_account, version=1.0.0, content_hash=sha256:ac1a88a3ec2072ae7bab01cc4145b66be1ed911cede496d8e35f04312851bdd4, lifecycle=verified, tenant=lakeshore, product_version=7.2.4, inputs={'member_id': '104410', 'product': 'Money Market Share', 'nickname': 'Rainy day fund |
| 0.82 | ■ **run finished**: status=failed, failure=NOT_APPROVED, duration_ms=1 |

## Result (as persisted: masked outputs are placeholders + fingerprints)

```json
{
  "run_id": "rep-20260911-141401-0ad9",
  "capability": {
    "id": "keystone.member.open_share_account",
    "version": "1.0.0",
    "content_hash": "sha256:ac1a88a3ec2072ae7bab01cc4145b66be1ed911cede496d8e35f04312851bdd4"
  },
  "tenant": "lakeshore",
  "status": "failed",
  "failure": {
    "code": "NOT_APPROVED",
    "message": "keystone.member.open_share_account@1.0.0 is verified; unattended runs need an approved capability",
    "retryable": false,
    "evidence": {},
    "details": {}
  },
  "recoveries": [],
  "warnings": [],
  "interventions": [],
  "steps": [],
  "started_at": "2026-09-11T06:14:02.170012Z",
  "finished_at": "2026-09-11T06:14:02.172053Z",
  "duration_ms": 1,
  "evidence_dir": "/Users/williammac/Desktop/project/understudy/evidence/runs/20260911-141401-replay-open-not-approved"
}
```
