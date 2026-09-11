#!/usr/bin/env bash
# Regenerates the replay half of evidence/: every run below is deterministic (no model).
# Needs: the Keystone mock running (`uv run understudy mock`) and the capabilities in capabilities/.
# Usage: scripts/demo_replays.sh            (writes to evidence/runs/)
set -uo pipefail
cd "$(dirname "$0")/.."
U="uv run understudy"
LOOKUP=keystone.member.lookup_balance
OPEN=keystone.member.open_share_account
OPEN_ARGS=(-i member_id=104410 -i "product=Money Market Share" -i "nickname=Rainy day fund" -i opening_deposit=1500 -i fund_from=00)

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
reset() { $U fault reset >/dev/null; }

step "1. lookup: success on the tenant it was discovered on"
reset; $U replay $LOOKUP -t lakeshore -i member_id=100234 --label lookup-success

step "2. lookup: business outcome - no such member"
reset; $U replay $LOOKUP -t lakeshore -i member_id=999999 --label lookup-not-found

step "3. lookup: business outcome - restricted member"
reset; $U replay $LOOKUP -t lakeshore -i member_id=100777 --label lookup-restricted

step "4. lookup: bad input is rejected before the UI is touched"
reset; $U replay $LOOKUP -t lakeshore -i member_id=12ab --label lookup-invalid-input

step "5. lookup: session expires mid-flow -> re-sign-on and restart (recoverable)"
reset; $U fault session_expired -t lakeshore --page mbrinq.asp --method POST >/dev/null
$U replay $LOOKUP -t lakeshore -i member_id=100234 --label lookup-session-expired

step "6. lookup: maintenance interstitial + transient host timeout (recoverable)"
reset; $U fault notice -t lakeshore --page mbrdtl.asp >/dev/null; $U fault host_error -t lakeshore --page mbrinq.asp --method POST >/dev/null
$U replay $LOOKUP -t lakeshore -i member_id=100234 --label lookup-interstitial-and-retry

step "7. lookup: application error (hard failure with evidence)"
reset; $U fault server_error -t lakeshore --page mbrdtl.asp >/dev/null
$U replay $LOOKUP -t lakeshore -i member_id=100234 --label lookup-app-error

step "8. lookup on a second tenant (pinecrest), with its vocabulary"
reset; $U replay $LOOKUP -t pinecrest -i member_id=100234 --label pinecrest-with-vocabulary

step "9. lookup on pinecrest WITHOUT its vocabulary: navigation degrades gracefully, the read fails loudly"
reset; $U replay $LOOKUP -t pinecrest -i member_id=100234 --no-overrides --label pinecrest-no-vocabulary

step "10. open account, unsupervised: the irreversible step is refused"
reset; $U replay $OPEN -t lakeshore "${OPEN_ARGS[@]}" --label open-unsupervised

step "11. open account, supervised: an operator approves, automation commits"
reset; $U replay $OPEN -t lakeshore "${OPEN_ARGS[@]}" --supervised --operator-script examples/operators/approve_in_replay.yaml --label open-approved

step "12. open account over the teller limit: supervisor takes over the live session, hands back"
reset; $U replay $OPEN -t lakeshore -i member_id=104410 -i "product=Money Market Share" -i "nickname=Rainy day fund" \
  -i opening_deposit=12000 -i fund_from=00 --supervised --operator-script examples/operators/supervisor_override.yaml --label open-supervisor-override

step "13. open account: business outcome - deposit below the product minimum"
reset; $U replay $OPEN -t lakeshore -i member_id=104410 -i "product=Money Market Share" -i "nickname=Rainy day fund" \
  -i opening_deposit=50 -i fund_from=00 --label open-deposit-rejected

reset
echo; echo "done: see evidence/runs/"
