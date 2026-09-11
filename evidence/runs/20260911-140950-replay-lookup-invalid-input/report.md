# Replay of keystone.member.lookup_balance@1.0.0 on lakeshore

Run `rep-20260911-140950-6321`. Every line below comes from `events.jsonl`; screenshots are masked before capture.

| t (s) | event |
|---:|---|
| 0.46 | · run_started: capability=keystone.member.lookup_balance, version=1.0.0, content_hash=sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3, lifecycle=approved, tenant=lakeshore, product_version=7.2.4, inputs={'member_id': '12ab'}, supervised=False |
| 0.46 | · input_rejected: problems={'member_id': 'does not match pattern ^[0-9]{4,10}$'} |
| 0.46 | ■ **run finished**: status=failed, failure=INVALID_INPUT, duration_ms=0 |

## Result (as persisted: masked outputs are placeholders + fingerprints)

```json
{
  "run_id": "rep-20260911-140950-6321",
  "capability": {
    "id": "keystone.member.lookup_balance",
    "version": "1.0.0",
    "content_hash": "sha256:bb1fca2cf4b25cf59ab689337067eb73c07c6493d6df45739ae63de55bc499a3"
  },
  "tenant": "lakeshore",
  "status": "failed",
  "failure": {
    "code": "INVALID_INPUT",
    "message": "inputs do not satisfy the capability contract",
    "expected": "see capability inputs",
    "observed": "member_id: does not match pattern ^[0-9]{4,10}$",
    "retryable": false,
    "evidence": {},
    "details": {
      "problems": {
        "member_id": "does not match pattern ^[0-9]{4,10}$"
      }
    }
  },
  "recoveries": [],
  "warnings": [],
  "interventions": [],
  "steps": [],
  "started_at": "2026-09-11T06:09:50.496930Z",
  "finished_at": "2026-09-11T06:09:50.497839Z",
  "duration_ms": 0,
  "evidence_dir": "/Users/williammac/Desktop/project/understudy/evidence/runs/20260911-140950-replay-lookup-invalid-input"
}
```
