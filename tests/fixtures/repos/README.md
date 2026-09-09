# target repos for integration tests

- `case_a_simple`: trivial change surface; expected flow Design -> Initial Review -> PASS.
- `case_b_blocker`: initial review raises a correctable blocker; expected flow
  Initial Review -> Revision -> Closure -> PASS.
- `case_c_tradeoff`: real REQUIREMENT/TRADE_OFF decision required; expected flow
  Human Gate -> decision -> task revision -> redesign -> review -> DONE.
