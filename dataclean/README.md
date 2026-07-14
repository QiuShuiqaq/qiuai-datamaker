# OpenClaw Dataclean

这个目录现在有两类脚本:

1. `start_openclaw_multi.ps1`
   用真实进程隔离多开 OpenClaw。

2. `openclaw_gateway_cli.mjs`
   通过 OpenClaw 官方 CLI 跑真实会话，并补上基础验收、补轮、汇总、导出。

## 1. 多开 OpenClaw

```powershell
.\start_openclaw_multi.ps1 -OpenClawExe "D:\Program\OPENCLAW\openclaw\OpenClaw.exe" -InstanceCount 4
```

也可以直接双击 `start_openclaw_multi.bat`。

隔离规则:

- 每个实例都有自己的 `profile`
- 每个实例都有自己的 `.openclaw`
- 每个实例都有自己的 `workspace` 和 `temp`
- 只启动真实 OpenClaw，不生成伪造产物

启动结果在 `dataclean\runs\openclaw-multi-时间戳\` 下。

## 2. 网关自动化

前提:

- 本机有 Node 20+
- OpenClaw 自带的 WSL 网关环境已经正常安装
- `openclaw agent` 命令在这台机器上已经能真实跑通

### 连通性探测

```powershell
node .\dataclean\openclaw_gateway_cli.mjs probe
```

这个命令会直接调用 OpenClaw 官方 CLI，读取真实 session 列表。

### 列出会话

```powershell
node .\dataclean\openclaw_gateway_cli.mjs list-sessions --limit 20
```

### 检查某个 session 是否达标

```powershell
node .\dataclean\openclaw_gateway_cli.mjs inspect-session --session-key agent:main:main --min-assistant-turns 5 --min-thinking-turns 5
```

### 手动导出某个已有 session

```powershell
node .\dataclean\openclaw_gateway_cli.mjs export-session --session-key agent:main:main
```

### 批量跑任务

```powershell
node .\dataclean\openclaw_gateway_cli.mjs run-tasks --tasks .\dataclean\tasks.sample.jsonl --concurrency 2 --timeout-ms 900000
```

默认验收规则:

- `minUserTurns = 5`
- `minAssistantTurns = 5`
- `minThinkingTurns = 5`
- `minThinkingChars = 0`
- `maxAutoTurns = 3`

也就是:

- 先按任务里给的 `turns` 跑
- 跑完后读取真实 session `.jsonl`
- 如果轮次或 thinking 不达标，就自动补轮
- 补到达标或者补轮次数到上限为止

你也可以覆盖这些默认值，例如:

```powershell
node .\dataclean\openclaw_gateway_cli.mjs run-tasks `
  --tasks .\dataclean\tasks.sample.jsonl `
  --concurrency 4 `
  --min-assistant-turns 5 `
  --min-thinking-turns 5 `
  --max-auto-turns 5 `
  --auto-followup-prompt "请继续围绕当前主题推进一轮新的有效对话，不要重复前文。"
```

如果只想跑，不想导出 accepted 产物:

```powershell
node .\dataclean\openclaw_gateway_cli.mjs run-tasks --tasks .\dataclean\tasks.sample.jsonl --skip-export true
```

## 3. 任务文件格式

`tasks.jsonl` 每行一个 JSON。

最小示例:

```json
{"label":"task-001","turns":["第1轮提示词","第2轮提示词","第3轮提示词","第4轮提示词","第5轮提示词"]}
```

可以直接参考 `tasks.sample.jsonl` 改。

可选字段:

- `sessionKey`
- `agentId`
- `model`
- `thinkingLevel`
- `verboseLevel`
- `timeoutSeconds`
- `minUserTurns`
- `minAssistantTurns`
- `minThinkingTurns`
- `minThinkingChars`
- `maxAutoTurns`
- `autoFollowupPrompt`

## 4. 输出结果

每次 `run-tasks` 会在 `dataclean\runs\gateway-batch-时间戳\` 下生成:

- `results.jsonl`
  全部任务逐条结果
- `accepted.json`
  通过验收的任务
- `rejected.json`
  未通过或执行失败的任务
- `summary.json`
  本次汇总
- `accepted\<任务名>\`
  通过项的真实 session 产物

通过项目录里会尽量带上:

- `session.jsonl`
- `trajectory.jsonl`
- `trajectory-export\`
- `session-metadata.json`

说明:

- 这是走 OpenClaw 官方 CLI 和真实网关，不是伪造 session JSON
- 当前版本已经覆盖“批量发送、基础验收、自动补轮、通过项导出”
- 如果后面要继续加“按你的甲方验收规则做更细的质检字段”“自动统计有效 session 数”“自动整理成你最终交付目录”，可以继续叠加在这个 CLI 上
