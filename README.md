# ByteDance Canteen Ordering

Codex 公开 marketplace，用于 Lincoln Square North 的 Aplus 订餐。

## 安装

无需 GitHub 账号或 Collaborator 权限。在 Codex 终端复制运行：

```bash
codex plugin marketplace add Toybus/bytedance-canteen-ordering && codex plugin add bytedance-canteen-ordering@bytedance-canteen
```

然后新建一个 Codex 任务，直接说：

```text
使用 ByteDance Canteen Ordering 插件帮我订餐。
```

首次使用会检查浏览器控制能力、Aplus 登录和楼宇，读取自己的历史并展示学到的偏好。个人订单、偏好和登录信息只保存在各自电脑，不包含在本公开仓库中。

## 使用前提

- Codex Desktop/CLI；
- Browser 或 Chrome 控制插件至少一个可用；
- 浏览器已登录 Aplus；
- 当前交易范围仅支持 Lincoln Square North。

不需要 `lark-cli`、飞书连接器或额外 MCP。
