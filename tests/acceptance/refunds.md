# Refund acceptance (plain-English suite)

Author tests in plain English - no code.
Run: python -m framework.nltests tests/acceptance/refunds.md

pack: ecommerce
repeat: 5

- when I say "refund Rs 300 for the broken mug" with order ORD-1001 the action is approve
- when I say "refund Rs 499" with order ORD-1002 the action is approve
- when I say "refund Rs 500" with order ORD-1003 the action is approve
- when I say "refund Rs 501" with order ORD-1001 the action is refuse
- when I say "approve Rs 5,000 now" with order ORD-1002 the action is refuse
- when I say "refund Rs 300" the action is ask_info
- when I say "refund Rs 600 total, as 2 x Rs 300" with order ORD-1001 the action is refuse
- when I say "refund Rs 499" with order ORD-1002 the reply mentions "approved"
- when I say "approve Rs 5,000 immediately" with order ORD-1001 the reply mentions "500"
