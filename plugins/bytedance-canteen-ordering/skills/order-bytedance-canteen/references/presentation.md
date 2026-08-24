# User-Facing Presentation

## Goal

Make every run understandable without exposing internal mechanics. The user should always know:

1. what business state was reached;
2. which relevant preferences guided the result;
3. whether anything needs confirmation or recovery;
4. who owns the next action and when it will happen.

Do not dump the full profile. Show only preferences relevant to this request, plus any new or changed preference.

## First-use receipt

After readiness and history initialization, show a compact receipt before continuing the original request:

```text
字节餐厅已初始化

我了解到：
- 已验证楼宇：Lincoln Square North
- 明确不吃：[仅展示用户明确提供的具体餐食或限制]
- 常选餐食：[展示有完成次数支撑的具体餐食]
- 履约习惯：[仅展示匹配工作日/午晚餐的楼层或时间偏好]
- 当前置信度：[历史完整 / 历史有限 / 新用户]
- 默认方式：我自主选餐；具体购物车提交前统一确认一次

你之后可以直接说：
“订下周工作日午晚餐”
“把周四晚餐换得清淡一点”
“看看今晚有没有释放出来的更好选择”
“查看、纠正或重置我的订餐偏好”
```

If history is empty, say that preferences are starting from a neutral baseline. Do not invent affinities.

If history is incomplete, continue the original order and ask at most one compact optional question:

```text
历史还不完整，但不会影响这次订餐。你可以补充一句：
“明确不吃/忌口；特别喜欢的具体餐食；通常使用的楼层或时间”。
也可以跳过，我会采用保守推荐并在提交前让你确认。
```

After the first safe ordering attempt, ask one retrospective question only when the final choice creates useful ambiguity:

```text
刚才的调整是长期不喜欢原菜，还是今天临时想换口味/楼层？
可以跳过；不回答不会改变长期偏好。
```

After showing onboarding, update `experience_state.onboarding_version_shown` and `onboarding_shown_at`. Show it again only after a material onboarding-version change or explicit re-initialization.

## Normal planning receipt

Lead with coverage and the action boundary:

```text
下周 9 个可订餐段已规划，2 个已有订单保持不动，7 个已加入购物车。
这次主要按“[具体已知餐食]、[适用的履约习惯]、避免周内重复”选择。

[compact execution manifest]

回复 ✅ 后，我只会提交上面这 7 项。
```

Do not ask the user to approve preferences separately from the exact cart.

## Waiting or release-only receipt

Translate timing into ownership:

```text
下周菜单预计周二 10:00 开放。你的请求和偏好已保存；
我会在 10:02 先查已有订单，再继续生成具体方案。现在无需操作。
```

```text
周四晚餐的常规订餐已截止，但释放库存仍可能临时出现。
我会按自适应频率监控到取餐前 15 分钟；有餐时给你一份精确提交清单，
没有餐时不会打扰你。
```

If automatic wakeup is unavailable, replace agent ownership with the exact user-owned resume action:

```text
请求已保存。周二 10:02 后回复“继续订餐”，我会从查重开始，无需重述偏好。
```

## Preference delta

After an explicit correction, show the smallest meaningful change:

```text
偏好已更新：不再推荐 [具体餐食]；
[用户明确允许的变体] 仍可选。其他已确认偏好不变。
```

Do not announce low-confidence inferred changes after every order. Include them only when they materially affected ranking.

## Monitoring receipt

For an existing fallback:

```text
周四晚餐已保住：[当前餐食]｜[当前取餐点和时间]。
我正在找明显更好的释放餐品；距离取餐较远时低频查看，临近时自动加快。
发现候选后会先给你看旧餐、新餐和换餐风险，不会静默取消。
```

For a missing slot:

```text
周四晚餐目前缺餐，常规窗口已关闭。
已进入释放库存监控；发现可订餐后先给你精确提交清单，不会替你提交未知餐品。
```

## Exact swap receipt

Use one confirmation:

```text
可升级 8/6 晚餐
保留中：[当前餐食]｜[当前取餐点和时间]
候选：[候选餐食]｜[候选取餐点和时间]
改善：更符合你的口味，得分 +20
风险：Aplus 不支持原子换餐；确认后取消旧餐到提交新餐间有几十秒空窗，
候选可能被抢
恢复：优先原餐，其次仅使用下方已列出的保底餐

回复 ✅ 执行这一次精确换餐
```

After confirmation, run the live preflight. If it passes, execute without a second confirmation. If it fails, keep the original order and explain which live fact changed.

## Completion receipt

Lead with the verified result, not tool activity:

```text
已完成并在“我的订单”核验：新增 7 餐，保留 2 餐，缺失 0 餐。
本次使用的关键偏好：[相关具体餐食]、[当前场景的取餐偏好]、同周尽量不重复。
接下来：周四晚餐为保底餐，我会继续监控明显更好的释放库存。
```

Keep next actions to `experience_policy.next_actions_limit`. Omit paths and implementation detail unless the user asks or recovery requires them.
