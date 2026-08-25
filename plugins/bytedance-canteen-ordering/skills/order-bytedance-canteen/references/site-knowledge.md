# Aplus Canteen Page Knowledge

## Routes

- Ordering: `https://aplus.bytedance.com/canteen/ordering`
- My Orders: `https://aplus.bytedance.com/canteen/my-order`

Use the authenticated browser session. Do not inspect cookies, local storage, or credentials.

Transactional support in this release is limited to `Lincoln Square North`. Discover the live building before any cart or cancellation action and stop safely for other buildings.

## Access and ordering lifecycle

- A first-time user may need to sign in to ByteDance SSO in the same Browser or Chrome session that Codex controls.
- Browser/Chrome control and Aplus authentication are required; Lark CLI and Lark connectors are not.
- Next-week ordering is expected to open Tuesday at 10:00 in the user's configured timezone.
- The opening rule is predictive only. The selected date's live page state is authoritative.
- Before the expected opening, save the request and resume at open time plus grace.
- After the expected opening, retry a page that still says unopened only within the configured bounded horizon; then classify it as a window anomaly.
- Read My Orders before waiting: a user who already filled all target slots has an `already_complete` result even if another future week is closed.

## Ordering page

The page contains:

- building selector;
- horizontal date strip;
- separate lunch and dinner tabs;
- pickup-site tabs;
- independently scrolling menu;
- fixed cart footer and submit control.

Pickup labels may encode a floor and time, for example `Fxx 12:00 Pickup`.

## Observed failure modes

### Date and menu loading

- A gray date can still accept a click but show `该日期或楼宇尚未开放订餐`.
- Gray may mean future/not-open, unavailable, stale rendering, or a genuinely disabled business state. Classify it using selected styling, message text, cutoff, current time, and the configured opening rule rather than color alone.
- Switching date or meal can leave the menu empty or briefly retain old content.
- Click the whole date box, not only the inner date number, when text clicks do not change the yellow selection.
- Verify selected date, cutoff, site titles, and body state before continuing.

### Independent scrolling

- The menu uses an inner scroll container.
- Pickup-tab navigation is smooth, not instantaneous.
- Wait until the intended pickup tab is active; two to three seconds may be necessary.
- Clicking a dish while another pickup tab is still active can silently fail.

### Weak disabled semantics

- `button.disabled` can remain false while the submit control is visually disabled.
- Treat the `ud-button--disabled` class, cart count, and business state as authoritative together.
- Sold-out dishes may retain a radio-like icon; read `已订完`.

### Overlays and dialogs

- A pickup-point change can open a dialog such as:
  `你上一次使用的取餐点是 ... 确定要从当前取餐点 ... 下单吗？`
- The overlay can make the underlying click appear ineffective.
- Confirm only after verifying the dialog names the intended pickup point.
- Cart details use a bottom modal; close it with its header close control.

### Meal-type batching

- The cart can accumulate multiple dates for one meal type.
- A non-empty lunch cart can block dinner selections without an explicit error.
- Plan both meal types before cart work. Build, submit, and verify them as separate batches in one uninterrupted run; never ask the user a routine question between batches.

### Replacement is non-atomic

- An occupied `(date, meal)` slot shows `此餐段已预订` and prevents selecting a replacement while the old order remains.
- A better released meal cannot be held before canceling the current order.
- Revalidate the new candidate after exact swap approval and before canceling.
- If the candidate disappears, keep the old order and continue monitoring.
- After cancellation, execute only the recovery options disclosed in the confirmed swap manifest.

### Time rendering mismatch

The following was a single historical observation on 2026-08-05, not a stable global rule: the cart displayed a nine-hour offset:

- lunch `03:00 - 04:30`;
- dinner `09:00 - 10:30`.

After explicit user confirmation and submission, My Orders showed the correct times:

- lunch `12:00 - 13:30`;
- dinner `18:00 - 19:30`.

Always disclose cart-time conflicts and verify My Orders after submission.

## My Orders

- The list has its own infinite scroll container.
- Default status filters may omit completed history.
- Load more by scrolling `.my-order-list-wrapper` to its bottom and waiting.
- Select every relevant status, not only the default filter.
- Prefer a 60–90 day baseline. When long-range loading is unstable, read one calendar month at a time and merge normalized rows by order ID or stable row fingerprint.
- Keep scrolling until the page visibly reports that no more orders remain; a temporarily unchanged row count is not proof of completion.
- Record the requested date range, actual first/last row dates, monthly counts, and whether the end-of-list signal appeared.
- Verify the dates against the profile timezone before writing the analysis period.
- Prefer history from before the agent began selecting meals. If that is impossible, label the period `mixed`; do not pretend it is an uncontaminated baseline.
- Verify final state here rather than relying only on a result page.
- Never click `取消` or `释放` during read-only inspection.
