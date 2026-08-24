# Aplus Site Guide

This file is initialized for one user and updated from live, read-only exploration.

## Environment

- Building:
- Transaction support verified: Lincoln Square North only
- Timezone:
- Last verified:

## Page structure

- Ordering route: `https://aplus.bytedance.com/canteen/ordering`
- My Orders route: `https://aplus.bytedance.com/canteen/my-order`
- Building selector:
- Date strip:
- Meal tabs:
- Pickup tabs:
- Menu scroll container:
- Cart:

## My Orders history

- Status filters:
- Date-range behavior:
- Infinite-scroll end signal:
- Monthly fallback behavior:
- Timezone/date verification:

## Ordering-window evidence

- Expected next-week opening: Tuesday 10:00 local time
- Last live observation:

## Known interaction risks

- Gray dates require business-state verification; color alone is inconclusive.
- Pickup-site navigation may smooth-scroll for several seconds.
- Visually disabled controls may not expose a native `disabled` property.
- Lunch and dinner may require separate cart batches.
- Cart time can differ from final My Orders time; disclose and verify.

## Local observations

Record only reusable UI behavior. Do not store credentials, cookies, or session data.
