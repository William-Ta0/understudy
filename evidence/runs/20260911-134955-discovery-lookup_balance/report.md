# Discovery: Look up a member's savings balance

Run `dis-20260911-134955-aba7`. Every line below comes from `events.jsonl`; screenshots are masked before capture.

| t (s) | event |
|---:|---|
| 0.77 | · discovery_started: goal=Look up member {{inputs.member_id}} and read the current balance and the available balance of the member's primary savings account (the "Share Savings" account), and the member's name as shown on the member record., capability=keystone.member.lookup_balance, tenant=lakeshore, model=glm-4.6v, in |
| 0.77 | · sign_on_started: tenant=lakeshore, attempt=1 |
| 1.56 | 🔑 sign_on_completed: screen=workstation_home |
| 11.76 | 🧠 turn 1 on `workstation_home`: **click**(ref=n2) - "Click on Member Inquiry button to access member lookup functionality" ([screen](screens/001-turn01.png)) |
| 25.07 | 🧠 turn 2 on `member_search`: **fill**(ref=m3, value={{inputs.member_id}}) - "Enter the member ID in the Member Number field to search for the member record." ([screen](screens/002-turn02.png)) |
| 31.74 | 🧠 turn 3 on `member_search`: **click**(ref=m8) - "Click the Search button to find the member record with the entered member number." ([screen](screens/003-turn03.png)) |
| 42.82 | 🧠 turn 4 on `member_detail`: **extract**(output=member_name, ref=m5) - "Extract the member's name from the Name field on the member detail screen" ([screen](screens/004-turn04.png)) |
| 51.78 | 🧠 turn 5 on `member_detail`: **extract**(output=savings_balance, ref=m27) - "Extract the current balance value for the Share Savings account from the member detail page" ([screen](screens/005-turn05.png)) |
| 58.71 | 🧠 turn 6 on `member_detail`: **extract**(output=available_balance, ref=m28) - "Extract the available balance value from the Share Savings account row in the accounts table" ([screen](screens/006-turn06.png)) |
| 74.84 | 🧠 turn 7 on `member_detail`: **finish**(status=success) - "I can see that all the required information has been successfully extracted from the member detail page. The member record for 100234 is displayed, showing the member's name, and the Share Savings account details including the current balance of [financial] and available balance of [financial]. All outputs have been collected, so I will finish the task." ([screen](screens/007-turn07.png)) |
| 74.85 | ■ **agent finished**: status=success, summary=Successfully looked up member 100234 and extracted all required information: member name, Share Savings current balance ([financial]), and Share Savings available balance ([financial]). |
| 74.85 | · **discovery finished**: status=success, agent_steps=6, human_steps=0 |
