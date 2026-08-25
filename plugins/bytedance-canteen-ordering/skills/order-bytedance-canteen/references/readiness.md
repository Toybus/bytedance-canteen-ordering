# Readiness and Recovery

## Dependency contract

### Hard requirements

1. Codex can load this Skill or its containing plugin.
2. Browser or Chrome control is installed and callable.
3. The controlled browser can reach Aplus.
4. The user has a valid ByteDance corporate login in that browser.
5. Codex can write the local profile, guide, run records, and pending intent.

### Included or replaceable helpers

- Python 3 standard library is used by the included bootstrap, lifecycle, and validation scripts.
- If Python is unavailable, Codex may create and validate the small JSON files directly. Python is not a reason to abandon the request.

### Optional capability

- Native task automation enables automatic wakeup when future menus open.
- Without it, persist the same intent and return the exact resume time and prompt. Ordering remains usable, but resumption is user-triggered.

### Not required

- Lark CLI;
- Lark apps or connectors;
- external MCP servers;
- cookie, credential, or local-storage inspection;
- a source-code checkout after the plugin is installed.

## First-use gate

Perform these checks in order:

1. Capture the original request, target week, coverage, and any corrections.
2. Confirm that Browser or Chrome control is available.
3. If neither is available, preserve intent and offer installation of the relevant browser-control plugin.
4. Open `https://aplus.bytedance.com/canteen/ordering`.
5. If the user did not explicitly choose a browser and the first controlled browser is logged out, check the other installed controlled browser before interrupting the user.
6. If every available controlled browser is logged out or access is denied, ask the user to sign in once in the selected browser. Do not ask for credentials.
7. Verify that ordering or My Orders loads and discover the live building label.
8. Resolve the user's IANA timezone from reliable local context; ask only if it cannot be determined.
9. Resolve the user-wide canonical profile before considering any current-project profile.
10. If only a legacy project profile exists, migrate it to canonical state. If both exist, conservatively merge explicit preferences and the more complete history.
11. Verify the live building is `Lincoln Square North`. For another building, stop before transaction and state that this release has not verified it.
12. Bootstrap the portable data directory when no profile exists and validate schema v6. Migrate v3 to v4, v4 to v5, and v5 to v6 only when those versions are present.
13. Read available order history. Treat empty or partial history as a valid new-user state, not an error.
14. When history is insufficient, ask at most one compact optional preference question. If an ordering request is active, do not wait for an answer: continue conservative planning and ordinary submission, then include the question with the final verified receipt when it remains useful.
15. Continue the original request without asking the user to repeat it.

## Per-run gate

Before each ordering run, verify:

- the canonical profile exists and passes schema-v6 structural validation;
- the controlled browser is reachable and authenticated;
- the building is supported and the target week is explicit;
- My Orders can be evaluated;
- the live menu state can be classified.

A stale login, page error, or missing browser controller produces `needs_recovery`. Preserve the request and name one next action.

## Recovery outcomes

Good recovery messages contain:

- the business state reached;
- the one missing capability or user action;
- what has already been saved;
- exactly how work resumes.

Examples:

- “订餐请求已保存；请在当前 Chrome 登录 Aplus。登录后回复‘继续’，我会从订单查重开始。”
- “下周菜单预计周二 10:00 开放；请求已保存并安排 10:02 自动重试。届时我会先查重，完成普通订餐后统一回报。”

Do not say only “无法继续” or expose an internal tool failure without translating it into the recoverable business state.

Use [presentation.md](presentation.md) after first-use setup so the user sees the saved preference summary, the destructive-action confirmation boundary, and a few example requests. When setup is part of an active ordering request, merge this summary into the final verified post-submit receipt instead of pausing before cart work.
