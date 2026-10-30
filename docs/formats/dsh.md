# DeepSeek Harness (DSH) Session 格式与导入规格（v4，2026-10 实测）

> 逆向对象：本机 DSH Desktop 0.2.1-rc.3（`/Applications/DeepSeek Harness.app`，asar 内 `dsh/node_modules/@deepseek-ai/*`；全局 CLI 安装 `~/.local/lib/node_modules/@deepseek-ai/dsh`，Node v24.22.1）。
> 结论均以源码 + 本机真实 session 文件交叉验证；样本见 `samples/dsh/`。
> 本机数据根：`~/.dsh`（`sessions/` 会话日志，`storages/workspace.json` 工作区注册表，`storages/session_projcache/` 投影缓存）。

## 0. TL;DR（导入外部会话要做的三件事）

1. **写文件**：`~/.dsh/sessions/<projectKey(cwd)>/<encodeSegment(sessionId)>/session.v4.jsonl.zstd`
   - 必须 **2 个以上独立 zstd frame**：第 1 帧恰好是 1 行 header（以 `\n` 结尾）；后续帧装事件行（每行一个 JSON）。
   - header 的 `id`、`cwd` 必须与目录路径严格对应，否则读取时报 `corrupt session log`。
2. **写事件**：`seq` 必须从 0 连续递增；5 种 surface 事件（user/assistant/tool/result/system/developer message）必须带 `"surfaceOp":"append"`；必须包含 `turn/start`（否则会话投影为 `blank=true`，侧边栏新会话行会被隐藏）；最后写 `session/end-seed`。
3. **注册（可选但推荐）**：停止 DSH 后编辑 `~/.dsh/storages/workspace.json`，把 id 加进对应 workspace 的 `sessionIds` 数组头部。**不写也能被发现**：`session.list` 直接扫描 `sessions/` 根目录，未归属任何 workspace 的会话在侧边栏 "Ungrouped" 分组里显示。运行中直接改 workspace.json 会被内存态覆盖。

---

## 1. 磁盘布局

```
~/.dsh/sessions/                                  # 持久化 root（desktop 默认）
  --Users-larr-Documents-...-workspace--/          # 项目目录 = "--" + projectKey(cwd) + "--"；cwd 缺失时 _no-cwd
    session-6cb77151-...-67912520d75f/             # 会话目录 = encodeSegment(sessionId)
      session.v4.jsonl.zstd                        # 当前格式（v4）+ zstd；无压缩时为 session.v4.jsonl
      session.v3.jsonl.zstd                        # 历史代际（可选，读取时选数值最高者）
      session.lock                                 # 写租约 flock 文件（导入不需要）
  --Users-larr-Research_Assistant-~30101019~3011~6BD4~9009~6587~4EF6--/
```

- 文件名规范（`dsh-session-format/src/filename.ts`）：`session.jsonl` = v0，`session.vN.jsonl` = vN（N≥1，小写、无前导零）；压缩后缀 `.zstd`。
- 一个 root 只允许一种压缩编码；把 `.jsonl` 明文放进 zstd root 会在启动检查时报 encoding mismatch。
- 平铺文件（`sessions/--x--/<id>.jsonl`）是已废弃布局，读取会被拒绝。

### 1.1 projectKey(cwd)：项目目录名编码（`dsh-session-persistence-jsonl` `projectKey`）

逐个 UTF-16 code unit 处理 `cwd`：

| 输入字符 | 输出 |
|---|---|
| `/`、`\`、`:` | `-`（**连续分隔符折叠成一个** `-`） |
| `A-Z a-z 0-9 . _ -` | 原样 |
| 其他（含 `~`、空格、中文、全角括号…） | `~` + 4 位大写十六进制 code unit，如 `【`(U+3010) → `~3010` |
| 结果去除开头所有 `-`；空则用 `root`；截断到 251 字符 | |
| 最终 | `--` + 上述 + `--` |

示例（真实）：`~/Research_Assistant/【1019】比选文件` → `--Users-larr-Research_Assistant-~30101019~3011~6BD4~9009~6587~4EF6--`
（`【`=`~3010`、`】`=`~3011`、`比选文件`=`~6BD4~9009~6587~4EF6`；注意编码是 4 位大写 hex。）

### 1.2 encodeSegment(sessionId)：会话目录名编码

- `.` → `~002E`，`..` → `~002E~002E`；
- `A-Z a-z 0-9 . _ -` 原样，其余（含 `~`、中文、`/`）→ `~XXXX`（4 位大写 hex，逐 UTF-16 code unit）。
- 现代 DSH 的 id 形如 `session-<uuid>`，全部是安全字符，**目录名 = id 原文**；旧会话用裸 `<uuid>`，同样原样。两种并存，均有效。
- 实测：`~/.dsh/sessions/.../session-6cb77151-...` 与 `.../1542dcda-...` 都存在。

### 1.3 session.id 与目录/workspace 的关系

- 文件 header 的 `id` 决定一切：`generationLogPath(root, header.cwd, header.id, 4)` 必须等于实际路径，否则读取报错 `corrupt session log ... header id and cwd identify <path>`（`assertStoredIdentity`）。
- 同一个 id 出现在**两个不同项目目录**下 → `duplicate JSONL session id` 错误。
- 一个 id 只能被一个 workspace 的 `sessionIds` 记账（workspace 注册表有 one-owner 不变量）。
- workspace 成员校验：`realpath(header.cwd)` 必须等于 workspace 记录的 `path`（记录里存的是创建时 `fs.realpath` 的规范路径），否则该 id 会被过滤并打 warn。

---

## 2. 文件 = zstd 帧序列 + JSONL

- 读取路径 `scanZstdFrames` 扫描**独立 zstd frame 的拼接**（每帧 magic `28 B5 2F FD`）。
- **第 1 帧必须"恰好一行 header"**：`assertZstdHeaderFrame` 要求解码后的明文以 `\n` 结尾且**只有一个** `\n`（> header + `\n` 即报 `first frame is not exactly one header line`）。
- 后续帧的明文被拼接到 JSONL scanner，可一帧多行；也可每事件一帧。推荐：frame1=header 行；frame2=全部事件行（每行都以 `\n` 结尾）。
- **checksum 是否必须？——不必须，但真实写入方总是带。** 证据链：
  - 真实写入代码：`compressZstdFrame()` 用 `{params:{ZSTD_c_checksumFlag:1}}`，即每帧都带 checksum（"独立可解码、带校验和的 zstd frame"）；
  - 读取代码：`scanZstdFrames` 解析帧头 `checksum` 位，只有该位为 1 才多读 4 字节；`decompressZstdFrame` 在带 checksum 时校验。**没有要求该位必须为 1**；
  - 实测位对比：本机真实 `session.v4.jsonl.zstd` 首帧 descriptor=`0x04`（checksum=1）；用 `zstd -q -c`（本机 zstd CLI）生成的帧 descriptor 同样是 `0x04`。→ 用 zstd CLI 直接产出即可与官方文件同构。
- 实证（`samples/dsh`，zstd CLI）：
  ```bash
  head -1 session.jsonl | zstd -q -c >  session.v4.jsonl.zstd   # 第 1 帧：header 单行
  tail -n +2 session.jsonl | zstd -q -c >> session.v4.jsonl.zstd # 第 2 帧：事件行
  ```
  产物 2 帧、解压 18 行；DSH 读路径可接受。
- 只有 header 一帧的日志 = 合法空会话（持久化层 `handle.flush()` 就会产出这种文件）；本机 334/350 字节的 session 即含 header + 3 个初始策略事件。

---

## 3. 行 1：Session Header（严格校验）

示例（真实）：

```json
{"type":"session","version":4,"id":"session-6cb77151-bca6-4783-9588-67912520d75f","createdAt":1792603007338,"cwd":"~/Documents/deepseek-harness/default-workspace","isSeeded":false,"delegationDepth":0,"agentPreset":"standard"}
```

子代理会话还会带 `parentSession` 与 `origin`：

```json
{"type":"session","version":4,"id":"3085d394-...","createdAt":1792651961196,"cwd":"~/Research_Assistant/【1022】教材","parentSession":"session-ef03a779-78b2-406f-be99-26459cbcaf76","isSeeded":false,"origin":"subagent","delegationDepth":1,"agentPreset":"standard"}
```

| 字段 | 必填 | 类型/取值 | 说明 |
|---|---|---|---|
| `type` | ✅ | 固定 `"session"` | |
| `version` | ✅ | `4`（当前 `SESSION_FORMAT_VERSION`） | 写 4；>4 直接拒绝（"升级 harness"）；<4 走内置相邻迁移链 |
| `id` | ✅ | string | 与目录名/文件名一致，见 §1.2/§1.3 |
| `createdAt` | ✅ | 非负安全整数（ms epoch） | 排序/展示基准 |
| `cwd` | ⭕ | 绝对路径 string（`isAbsolute`） | 强烈建议写；缺失则无法挂 workspace，冷列表会跳过 |
| `parentSession` | ⭕ | string | 子代理会话的父 session id |
| `isSeeded` | ✅ | boolean | fork/带继承前缀的会话才有；普通导入写 `false` |
| `origin` | ⭕ | 仅 `"subagent"` | 其他值非法 |
| `delegationDepth` | ✅ | 非负安全整数 | 普通会话 0 |
| `agentPreset` | ⭕ | string（如 `"standard"`） | |

**Header 校验是白名单**（`isHeaderLine`）：只允许上表 key，多任何字段→被当作非法 header（无法读出）。
**明确拒绝**已退休字段 `sandboxMode`、`approvalPolicy`（应改为事件 `sandbox/mode`、`approval/policy`）。
**可选字段缺省时不要写 null**（注释明示 "absent optional fields omitted (never null)"）。

---

## 4. 事件行：统一 envelope

每行一个 JSON 对象（header 之后）：

```json
{"type":"user/message","seq":15,"time":1792603038346,"data":{...},"surfaceOp":"append"}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `type` | ✅ | 事件类型，见 §5；必须在本 build 的 `KNOWN_SESSION_EVENT_TYPES` 内，或带 `"ignorable":true` 才被持久层接受 |
| `seq` | ✅ | 从 **0** 开始连续递增，无空洞（`seed must be contiguous from 0`）；`seq` 就是追加顺序 |
| `time` | ✅ | 非负安全整数（ms epoch） |
| `data` | ✅ | 各类型对象（不可为 undefined） |
| `surfaceOp` | ⭕* | **5 种 surface 事件必填**：`"append"` 或 `{"op":"replace","startSeq":N,"endSeq":M}`；导入只用 `"append"` |
| `sourceEventSeqs` | ⭕ | 「本条由哪些更早事件派生」；必须引用更小 seq。`tool/result` 用 `[对应 tool/call 的 seq]`；assistant/message 禁止携带 |
| `ignorable` | ⭕ | 仅允许 `true`；未知事件类型必须带它（否则日志被拒） |

envelope 也是白名单（只允许以上 7 个 key）。

---

## 5. 事件类型目录

### 5.1 本 build 认识的完整类型集（`KNOWN_SESSION_EVENT_TYPES`）

```
agent-preset/selected, agent/inbox/spliced, approval/asked, approval/decided, approval/policy,
assistant/attempt, assistant/message, command/done, command/run, compaction/end, compaction/prune,
compaction/start, compaction/summary, deliverables/presented, developer/message,
feedback/message-delete, feedback/message-put, feedback/record, goal/change, hook/invoked, hook/result,
image/offload, job/registered, job/settled, llm/retry, llm/retry-started, model/selection,
permission/preset, plan/mode, request/context, request/header, sandbox/mode, schedule/change,
session-log-deepseek/delivery-accepted, session/end-seed, session/title, session/title-llm-request,
step/end, step/start, subagent/catalog, subagent/descriptor, subagent/model-selection-policy,
system/message, team/member, team/message/delivered, team/message/queued, team/task, todo/write,
tool-workflow/agent-end, tool-workflow/agent-start, tool-workflow/run-end, tool-workflow/run-start,
tool/call, tool/ptc-dispatch, tool/ptc-dispatch-start, tool/result, turn/end, turn/start,
user/message, web/deepseek-search-llm-request, working-directory/change, workspace/changes
```

真实日志中实测出现 32 种（样本 `samples/dsh/03-observed-event-catalog.json` 有每种一条截断实例）。

### 5.2 导入用关键事件 payload

**会话初始策略**（本体 350B 空会话的三件套，建议照抄）：

```json
{"type":"permission/preset","seq":0,"time":1792692672336,"data":{"preset":"workspace-write"}}
{"type":"sandbox/mode","seq":1,"time":1792692672337,"data":{"mode":"workspace-write"}}
{"type":"approval/policy","seq":2,"time":1792692672337,"data":{"policy":"ask"}}
```
（子代理会话会多带 `"source":"delegation"`；可选值如 `preset: danger-full-access`、`policy: never`。）

**回合/步骤边界**：

```json
{"type":"turn/start","seq":10,"time":1792603038333,"data":{"turn":1}}
{"type":"step/start","seq":13,"time":1792603038345,"data":{"turn":1,"step":1}}
{"type":"step/end","seq":36,"time":1792603040753,"data":{"turn":1,"step":1}}
{"type":"turn/end","seq":788,"time":1792604843497,"data":{"turn":1,"reason":{"kind":"completed"}}}
```
`turn/end.reason.kind`：`completed` / `error`（带 `error:{message,code}`）/ `cancelled` 等；`turn` 从 1 递增，`step` 每回合从 1 递增。

**user/message**（`data` 本身就是 message）：

```json
{"type":"user/message","seq":15,"time":1792603038346,"data":{"content":[{"type":"text","text":"帮我…"}],"source":{"kind":"user","rpcId":"3e0b1518-…","clientTimeZone":"Asia/Shanghai"},"role":"user","id":"76d6a1ff-…"},"surfaceOp":"append"}
```
约束：`role:"user"`、`id` 非空 string、`source.kind` 非空（用户输入用 `"user"`，系统注入可用 `"user-approval"` 等）、`content` 数组。

**system/message**（真实会话第一条 surface 是渲染后的系统提示词；导入**可省略**）：

```json
{"type":"system/message","seq":14,"time":…,"data":{"turn":1,"step":1,"message":{"role":"system","content":[{"type":"text","text":"You are an AI agent…"}],"source":{"kind":"system-prompt"},"id":"…"}},"surfaceOp":"append"}
```
约束：`source.kind` 必须 `"system-prompt"`。

**assistant/message**（关键：`message` + `usage` + `stream`；settlement 字段 turn/step/stream 为必填校验）：

```json
{"type":"assistant/message","seq":27,"time":1792603040676,"data":{
  "turn":1,"step":1,
  "message":{"role":"assistant",
    "content":[
      {"type":"reasoning","text":"Let me start by…"},
      {"type":"tool-call","id":"call_00_8ON6…","name":"bash","arguments":"{\"command\":\"env | grep…\"}"}
    ],
    "source":{"kind":"model","provider":"deepseek-account","model":"deepseek-flash"},
    "id":"19c149c6-…"},
  "usage":{"inputTokens":2116,"outputTokens":385,"cacheReadTokens":11904,"cacheWriteTokens":0,"totalTokens":14405},
  "stream":[…]},
 "surfaceOp":"append"}
```
- `source.kind` 必须 `"model"` 且 provider/model 非空；
- `turn`、`step` 非负整数；`stream` **必须是数组**（可写 `[]`；真实日志是紧凑的 provider stream 片段，用于回放/诊断，UI 与 deriveMessages 不依赖其内容）；
- `content` block 常见类型：`{"type":"text","text":…}`、`{"type":"reasoning","text":…}`、`{"type":"tool-call","id":…,"name":…,"arguments":"<JSON 字符串>"}`；
- 官方 schema：`message`、`step`、`stream`、`turn` required；`usage` **optional**（但强烈建议记录，是 token/context 表与其他投影的输入）。`usage` 内 `inputTokens`、`outputTokens` required，`cacheReadTokens/cacheWriteTokens/totalTokens/reasoningTokens` optional。

**tool/call（durable 调用记录）**：

```json
{"type":"tool/call","seq":28,"time":1792603040677,"data":{"turn":1,"step":1,"callId":"call_00_8ON6…","name":"bash","arguments":"{\"command\":\"env | grep…\"}"}}
```
配对机制：`assistant/message` 的 `tool-call` block 与同回合的 `tool/call` 事件通过 **`callId`** 关联（`block.id === tool/call.data.callId`）；`tool/call` 是崩溃恢复（`ToolCallRecovery`）与 UI job 关联的持久依据。官方 schema 中 `callId/name/arguments/turn/step` **全部 required**（`arguments` 为 JSON 字符串）。

**tool/result**：

```json
{"type":"tool/result","seq":31,"time":1792603040696,"data":{
  "turn":1,"step":1,
  "message":{"role":"tool",
    "source":{"kind":"tool","callId":"call_00_8ON6…"},
    "toolCallId":"call_00_8ON6…",
    "content":[{"type":"text","text":"(no output)"}],
    "isError":false,
    "id":"9acbdd6c-…"},
  "meta":{"cwd":"~/Documents/deepseek-harness/default-workspace"}},
 "sourceEventSeqs":[28],"surfaceOp":"append"}
```
约束：`message.source.kind === "tool"`、`source.callId === message.toolCallId`、两者均非空；`sourceEventSeqs` 指向产生它的 `tool/call` 的 seq（样本中 `[28]`）；可选 `meta`（如 `cwd`、job 详情）。

**request/context**（路由/容量元数据，显示与恢复辅助，可省略）：

```json
{"type":"request/context","seq":21,"time":…,"data":{"provider":"deepseek-account","model":"deepseek-flash","contextWindow":1048576,"systemPromptUpdate":"in-history"}}
```

**request/header**（请求封装快照；体积大，导入可省略；`data.reason` 必须是 `initial|resume|change|series` 之一，`header.config` 必须含 provider/model，禁止 `header.system`、禁止空 `tools:[]`、禁止空 `adapterDefaults:{}`）：

```json
{"type":"request/header","seq":20,"time":…,"data":{"header":{"config":{"provider":"deepseek-account","model":"deepseek-flash","reasoningEffort":"max","maxTokens":256000},"adapterDefaults":{"maxTokens":true},"tools":[…]},"reason":"initial"}}
```

**session/title**（标题的唯一权威来源；投影取最后一条）：

```json
{"type":"session/title","seq":22,"time":…,"data":{"title":"使用环境变量里的阿里云AK、SK","messageSeqs":[16],"source":{"kind":"fallback"}}}
```
官方 schema（`event:session/title`）三个字段都 required：`title: string`、`messageSeqs: [number]`、`source`（union：`{"kind":"fallback"}` | `{"kind":"user"}` | `{"kind":"provider","provider":string,"model"?:{provider,model}}`）。运行时投影只读 `title`，但为通过 schema 校验请写全（`messageSeqs` 填首个 user/message 的 seq）。
另有 `session/title-llm-request`（仅供 LLM 起题诊断，导入不需要）。

**job/registered + job/settled**（工具执行的生命周期，UI 依赖它展示工具卡片状态；导入建议成对补齐，也可省略）：

```json
{"type":"job/registered","seq":29,"time":…,"data":{"jobId":"bash-98cb4a5d91334fca","owner":"session-6cb77151-…","kind":"bash","label":"env | grep …","startedAt":…,"toolCall":{"callId":"call_00_8ON6…","rootCallId":"call_00_8ON6…"}}}
{"type":"job/settled","seq":30,"time":…,"data":{"jobId":"bash-98cb4a5d91334fca","owner":"session-6cb77151-…","kind":"bash","label":"env | grep …","startedAt":…,"finishedAt":…,"status":"completed","cause":"producer","producerReported":true,"detail":"exit code: 0","toolCall":{"callId":"call_00_8ON6…","rootCallId":"call_00_8ON6…"}}}
```

**其它高频日志事件**（可选，UI/统计用，导入可省略）：
`agent/inbox/spliced`（注入到下一 step/turn 的 inbox）、`session-log-deepseek/delivery-accepted`（深寻日志投递水位 `{sessionId,sessionFormatVersion,throughSeq}`）、`todo/write`、`workspace/changes`、`deliverables/presented`、`agent-preset/selected`、`model/selection`、`command/run`/`command/done`、`subagent/descriptor`/`subagent/catalog`、`team/*`、`goal/change`、`plan/mode`、`compaction/*`、`image/offload`、`llm/retry*`、`feedback/*`、`hook/*`、`working-directory/change`、`schedule/change`。

**session/end-seed**：`{"type":"session/end-seed","seq":N,"time":…,"data":{}}`——真实日志基本都以它结尾。读取时若缺少，`Session` 构造函数会在内存尾部补一条（实测 events=16 时 `session.seq===17`）；建议落盘时显式写入，避免后续追加/比较差异。

---

## 6. 最小可加载事件序列模板（已实测通过）

### 6.1 L0：header-only

只写 header 帧即可被 `list()` 发现；会话 `blank`，不显示对话。适合"空会话占位"。

### 6.2 L1：最小可见对话（不含工具）

```
L1  header
    permission/preset      seq 0
    sandbox/mode           seq 1
    approval/policy        seq 2
    turn/start             seq 3   ← 必须；否则 sessionListMetadata.blank 恒为 true，侧边栏按空白会话隐藏
    step/start             seq 4
    user/message           seq 5   surfaceOp:"append"
    session/title          seq 6   建议紧跟首个用户消息
    assistant/message      seq 7   surfaceOp:"append"；data 含 turn/step/message/stream:[]（usage 建议）
    step/end               seq 8
    turn/end               seq 9   reason:{kind:"completed"}
    session/end-seed       seq 10
```

完整可直接使用的 JSONL：`samples/dsh/01-minimal-valid-session.jsonl`（17 条事件，含两个 step 与一次工具调用）。
用真实 DSH 代码验证（`dsh-session` 的 `Session.fromRestore` + 当前消息投影）：

```
OK header: session-5f0c9b2e-… events: 17 seq: 17 messages: 4
  user      [{"type":"text","text":"帮我把这份 Qoder 会话导入 DSH"}]
  assistant [{"type":"reasoning",…},{"type":"text",…}]
  assistant [{"type":"tool-call","id":"call_import_0001",…}]
  tool      [{"type":"text","text":"--Users-larr-...--"}]
```

### 6.3 L2：带工具调用的完整回合（复制 6.2 的 step 模式）

```
assistant/message (content 含 tool-call block, id=callId)   surfaceOp:"append"
tool/call        {turn,step,callId,name,arguments}
job/registered   {jobId,owner,kind,label,startedAt,toolCall:{callId,rootCallId}}   # 可选
job/settled      {…,finishedAt,status:"completed",…}                              # 可选，需与 registered 配对
tool/result      {turn,step,message:{role:"tool",source:{kind:"tool",callId},toolCallId,content,isError,…}}
                 sourceEventSeqs:[tool/call 的 seq]，surfaceOp:"append"
step/end
```
多工具并行：一个 assistant/message 里多个 tool-call block → 每个 block 一条 `tool/call` → 各自 `tool/result`（本机真实会话：assistant/message 68 条、tool/call 124 条、tool/result 124 条，一一配对）。

### 6.4 可选增补（提升还原度）

- `request/context`：放首个用户消息前后；显示模型/上下文容量。
- `request/header`：放首个 step 前；用于"请求检查器"和 resume 时 envelope 对照。缺失不崩（客户端 `inspectRequestPrompt` 有 `previous===undefined` 分支）。
- `system/message`：真实会话第一条 surface；导入时可省略（否则客户端会显示系统提示词节点）。
- `agent/inbox/spliced`、`session-log-deepseek/delivery-accepted`：纯日志/投递水位，可省略。

### 6.5 严格性结论（"校验是否严格"）

| 检查 | 结果 | 出处 |
|---|---|---|
| header 白名单（多字段即非法） | 严格 | `isHeaderLine` |
| 退休字段 `sandboxMode/approvalPolicy` | 拒绝 | `assertNoRetiredHeaderFields` |
| header id/cwd 与物理路径一致 | **严格**（不一致=corrupt，拒绝加载） | `assertStoredIdentity` |
| seq 从 0 连续无空洞 | **严格** | `Session` 构造 + `assertContiguous` |
| 未知事件类型 | 持久层**拒绝**，除非 `"ignorable":true` | `validateStoredEvents` |
| surface 事件缺 `surfaceOp` | 拒绝 | `validateSurfaceMetadata` |
| assistant/message 缺 turn/step/stream | 拒绝 | `assertAssistantSettlementShape` |
| tool/result source/callId 配对 | 拒绝 | `assertMessageEventShape` |
| request/header `reason` 非法/含 system/空 tools | 拒绝 | `validateSessionEventData` / `assertCurrentLlmShape` |
| 未知 envelope 字段 | 拒绝 | `assertSessionEventEnvelope` |
| 缺少 request/header、job/*、turn 边界、session/title | **不拒绝**（只是显示/统计降级） | 实测 + 代码分支 |
| 缺少 `turn/start` | 能加载，但 `blank=true` → 侧边栏过滤 | `applySessionListMetadata` |
| 格式版本 | >4 拒绝；<4 自动迁移（只读打开不落盘，写打开会发布 `session.v4`） | `sessionFormatVersionRefusal` / generation 逻辑 |
| zstd 帧结构 | 第 1 帧必须 = 单行 header；尾部撕裂帧可恢复 | `assertZstdHeaderFrame` |

---

## 7. 发现 / 注册 / 展示机制（是否要改 workspace.json）

### 7.1 发现：纯目录扫描，不依赖 workspace.json

- `ctx.sessionPersistence.list()`：扫 `<root>` 下项目目录 → 会话目录 → 取**数值最高**的规范 generation → **只解析 header 帧**（不读事件），返回 header 列表。
- `ctx.sessionQuery.listSessions()`：persistence.list() ∪ 内存 live sessions。
- Web API `session.list`（`ApiSessionList.list`）用上述结果生成摘要，按 `updatedAt` 降序。
- 因此：**发现机制 = 纯扫 `<root>` 目录，不读 workspace.json、不依赖 projcache**。只把合法 session 文件放进 root，重启（或列表刷新）后就能被发现；损坏/不支持的 header 不会出现在 list 里（只有直接访问才报错）。workspace.json 只影响侧边栏分组/顺序/归档/置顶（见 §7.2/§7.3）。

### 7.2 展示：按 workspace.sessionIds 分组，未归属 → "Ungrouped"

- 侧边栏 `groupByWorkspace`：每个 workspace 按 `sessionIds` 顺序取成员；不在任何 workspace 记账的会话进入 **"Ungrouped"** 组（有 stray 才出现）。
- `archivedSessionIds` 中的会话默认隐藏（归档过滤）；`pinnedSessionIds` 置顶且与归档互斥。
- 因此 workspace.json **不是加载的必要条件**；只影响分组/顺序/归档/置顶。想要"像本地会话一样出现在某项目下"，才需要把 id 加进对应 workspace 的 `sessionIds`。

### 7.3 workspace.json（`single` JSON 存储域，version 2）

结构（见 `samples/dsh/04-workspace.json`）：

```json
{"unit":{"name":"workspace","version":2},
 "global":{"initialized":true,"defaultWorkspaceId":"…","workspaceIds":["…"],"archivedSessionIds":[],"pinnedSessionIds":[]},
 "tables":{"workspaces":{"<workspaceId>":{"path":"/abs/canonical","title":"…","sessionIds":["session-…"],"createdAt":"ISO","updatedAt":"ISO"}}}}
```
- `path` = 创建时 `fs.realpath` 的规范路径；`sessionIds` 数组顺序即显示顺序（新会话 attach 时**前插**）。
- 只有 `initialized=false`（首次启动）时 registry 才会用扫描到的 header **自动 bootstrap** 生成 workspace 记录；`initialized=true` 后**不会**自动把新文件收养进已有 workspace —— 新会话靠创建 API 的 `workspace.attachSession()` 记账。这也是"只放文件 → 出现在 Ungrouped 而不是项目下"的原因。
- `attachSession` 会校验 `realpath(header.cwd) === workspace.path`；因此 header.cwd 应写 workspace 记录的同一规范路径。

### 7.4 标题 / updatedAt / blank 来源（导入时怎么填）

| 摘要字段 | 来源 | 导入建议 |
|---|---|---|
| `title` | 投影 `title`（fold 最后一条 `session/title` 的 `data.title`）；列表先用 projcache 缓存，冷会话打开/拉投影时从日志重算 | **写一条 `session/title`**；未写则侧边栏标题可能暂空，打开会话后才有 |
| `updatedAt` | `max(header.createdAt, sessionListMetadata.lastPromptAt)`；`lastPromptAt` = **最后一条 `source.kind==="user"` 的 user/message 的 `time`** | user/message 的 `time` 用真实时间；header.createdAt 别写 0 |
| `blank` | 投影 `sessionListMetadata.blank`：初始 true，遇到任何 `turn/start` 后变 false；空白会话在侧边栏被隐藏（除当前新建行） | **必须写 `turn/start`** |
| `running` | 仅 live agent | 导入后为 false |
| `formatStatus` | 历史代际迁移状态 | 写 v4 即 `current` |
| 会话排序 | workspace.sessionIds 顺序（组内手动序）+ updatedAt 决定 Ungrouped 序 | 前插到 sessionIds 数组头 |

### 7.5 projcache（`~/.dsh/storages/session_projcache/sessions/<sessionId>.json`）

- 域 `session_projcache` version 7，`per-record` 布局：一条 record = `{version, record:{identity:{formatVersion,createdAt,cwd,isSeeded,inheritedEventCount}, rows:{key:{ver,seq,val}}}}`（样本 `05-projcache-excerpt.json`）。
- **纯派生缓存，可缺省**：缺失→冷读重放事件重建；identity 不匹配/`ver` 不匹配→整行丢弃（甚至坏文档会备份为 `.json.bak.<stamp>` 并跳过）；不迁移。
- 导入后无需手写；打开会话触发投影读/checkpoint 后会自动生成。手写风险高（`ver` 必须等于对应投影单元 stateVersion、`seq` 水位要对、identity 必须与 header 完全一致），不建议。

---

## 8. 官方 导入 / 导出 / 迁移 能力盘点

**导出（有）**：`@deepseek-ai/dsh-session-log-export`
- UI：Session Header 更多菜单 → `下载 Session 日志`；命令 `/export`。
- HTTP：`HEAD` 预检 + `GET /api/session.export?sessionId=<id>&includeDescendants=true`，返回 ZIP：
  - 根：`session[.v4].jsonl`（canonical JSONL，header + 顺序事件，**明文不压缩**）
  - `subagents/<id>/session.vN.jsonl`、`media/<attachmentId>.<ext>`、`files/<prefix>/<digest>/<name>`
  - 文件名 `dsh-session-<id>.zip`；流式生成，导出前对 live 会话做 flush 屏障。
- 这是**唯一官方导出格式**，可直接作为 DSH↔DSH 备份/迁移；导出不含 workspace.json / projcache。

**导入 / 迁移（没有）**：
- 未发现任何官方 import/upload/migrate session 的 API、CLI 或插件钩子（asar 与全局安装的 306 个 `@deepseek-ai/*` 包中无 `importSession` 实现；`exportSession` 命中只出现在 Anthropic SDK 无关代码）。
- 唯一的"迁移"是内部 session 格式代际迁移：`dsh-session-format-v0-to-v1 … v3-to-v4` 相邻链，在**读取历史代际日志**时自动执行（只读打开不落盘；写打开会生成 `session.v4.jsonl.zstd` 后继），不是用户级命令。
- 相关实验插件（可作参考）：`dsh-experimental-session-inspector`（会话日志检查）、`dsh-experimental-session-search`（内容检索）、`dsh-session-query` / `-sqlite`（宿主侧查询）。
- CLI：`dsh` 只负责 profile 启动（`dsh web|tui|headless|--resume`）与 `dsh plugin` 包管理；**没有 session 子命令**。

**结论**：外部会话（Qoder/OMP/Codex）导入 = 自研转换器，产出 DSH canonical JSONL → 写目录 +（可选）注册。导出样本可作格式校验对照。

---

## 9. 最小导入操作步骤（可直接照做）

前提：**先退出 DSH 桌面端**（至少保证不写 `~/.dsh` 期间它不运行），因为运行中的 app 以内存态为准，会覆盖外部对 `workspace.json` 的修改、并可能与新文件的扫描/缓存写入竞争。

1. 选定目标 workspace（`workspace.json` 里某条 `path`，或新建一个）。取 `cwd =` 该 `path` 的规范绝对路径（必须真实存在）。
2. 生成 `sessionId = "session-<uuid4>"`（或复用合法 uuid；不要与已有目录/id 冲突）。
3. 计算目录：
   - 项目目录名：`projectKey(cwd)`（§1.1 算法）；
   - 会话目录名：`encodeSegment(sessionId)`（现代 id 原样）。
4. 组装事件：按 §6.2/6.3 模板；`seq` 从 0 连续；surface 事件加 `"surfaceOp":"append"`；`time` 用转换后的真实时间（ms）；`session/title` 放首个 user/message 之后；末尾 `session/end-seed`。
5. 写 JSONL（UTF-8、无 BOM、LF 换行）→ 压缩成**双帧**（§2）：
   ```bash
   D="$HOME/.dsh/sessions/$(python3 -c 'project_key(...)')/$SID"
   mkdir -p "$D"
   head -1 "$SID.jsonl"     | zstd -q -c  > "$D/session.v4.jsonl.zstd"
   tail -n +2 "$SID.jsonl"  | zstd -q -c >> "$D/session.v4.jsonl.zstd"
   chmod 600 "$D/session.v4.jsonl.zstd"       # 与现有文件一致
   ```
6. （可选，推荐）编辑 `~/.dsh/storages/workspace.json`：在该 workspace 的 `sessionIds` **数组最前面**插入新 id；同步更新 `updatedAt`（ISO-8601）。保持 `unit/global/tables` 其余字段原样；整文件原子替换（写临时文件 + `mv`）。
   - 也可不改：会话将以 "Ungrouped" 出现。
   - 不要加入 `archivedSessionIds`。
7. 启动 DSH → 侧边栏出现会话（项目组或 Ungrouped）→ 点击打开：客户端 `session.follow` 拉事件流并 fold surface → transcript 渲染；投影读取会补标题并（触发 checkpoint 时）生成 projcache。
8. 验收检查（不启动 GUI 时也可用）：
   - `session.v4.jsonl.zstd` 解压行数 = 1 + 事件数；
   - 第 1 帧解压只有 1 行且以 `\n` 结尾；
   - header `id/cwd` 与目录推导一致；
   - seq 连续；每行 JSON parse 通过；surface 事件有 `surfaceOp`。

若想**先在临时环境验证**：把 `~/.dsh/profiles` 用软链复制、`DSH_HOME=/tmp/dsh-home-test` 起独立实例（`dsh --profile <name>`，换端口），把转换后的 sessions 根指向临时目录（避免写生产 `~/.dsh/sessions`）。本任务未起服务，验证使用 DSH 自身 `Session.fromRestore` 只读加载（见 §6.2 输出）。

---

## 10. 并发风险与安全写入建议（DSH 正在运行时）

| 风险 | 说明 | 建议 |
|---|---|---|
| workspace.json 内存态权威 | `dsh-storage-json` 的 `single` 布局把整单元常驻内存，每次写原子替换文件；外部编辑不会被感知，**下一次任意 workspace 变更会把你的修改整文件覆盖** | 只在 app 完全退出后编辑；或改用 API/UI 操作 |
| 追加中的 session 文件 | 运行中的 live session 持有 `session.lock`（flock）与写链，追加用「临时文件 + 硬链接无覆盖发布」；外部覆写会破坏 append 位置/触发 corruption/`write handle` 错误 | 不要动正在运行的会话文件；导入只写**新** id |
| 缓存不匹配 | projcache 由运行中进程写；你手写的缓存若 identity/ver 不匹配会被丢弃/备份（不崩，但无意义） | 导入不写 projcache，交给 DSH 重建 |
| 重复 id | 同一 id 在两个项目目录 → `duplicate JSONL session id`；id 已在 workspace.file 但文件被换 → 摘要与文件不一致 | 新 id 全局唯一；先 `grep -r "<id>" ~/.dsh/sessions` 确认 |
| 扫描时机 | list 按需扫描目录；新文件可能在下次列表刷新/重启后才出现 | 导入后重启 app 或重新连接前端 |
| 压缩编码 | root 为 zstd；放明文 `.jsonl` 会让整个 root 的编码检查失败（启动发现阶段拒绝） | 统一 zstd（双帧） |
| cwd 不存在 | header.cwd 指向不存在目录 → 会话无法挂 workspace（`missingSessionPaths`），冷列表里仍可能出现但分组/attach 失败 | cwd 必须是当前真实存在的绝对路径 |
| 权限 | 现有 session 文件 600；`.dsh` 目录 700 | 保持 600/700 |

**安全写入顺序**（推荐）：退出 DSH → 在临时目录生成并本地校验（JSONL parse、seq、zstd 帧）→ `cp`（或 `mv`，同一文件系统）到目标目录 → 可选改 workspace.json → 启动 DSH 验证 → 若失败删掉目录（DSH 没有删除接口，需手工 `rm`）。

---

## 11. 参考源码位置（本机可查）

**官方公开仓库**：<https://github.com/deepseek-ai/deepseek-harness>（默认分支 **master**，不是 main）。
- 权威 **v4 持久化 JSON Schema**：`docs/persistence-schema.json`（`sessionFormatVersion: 4`，65 个 root / 626 个 node，根含 header/envelope/各 `event:*` 的完整 required/optional 结构）。实测 `curl -sL https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/persistence-schema.json` 可下载（约 216KB）；本文 §12 的对照即来自它。
- 相关目录：`packages/session/session-persistence-jsonl/`、`packages/session/session-format*/`、`packages/core/session/`、`packages/storage/…`；`docs/persistence-changes/`（格式代际变更记录）。
- 本机等价可读实现有两份：桌面 app asar 内 `dsh/node_modules/@deepseek-ai/…`（可用 Python 解析 asar header 直接按偏移读取，无需解包 182MB）与全局 CLI 安装 `~/.local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/…`（推荐，明文可 grep）。


- 全局 CLI 安装（**完整可读包树，优先看这里**）：`~/.local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/`
  - `dsh-session/lib/index.js`：`SessionEventMap`、envelope/消息校验、`Session.fromRestore`、surface 折叠。
  - `dsh-session/lib/types/types.js`：`SESSION_FORMAT_VERSION = 4`。
  - `dsh-session/lib/types/known-event-types.js`：`KNOWN_SESSION_EVENT_TYPES` 全集。
  - `dsh-session-format/lib/index.js`：`session[.vN].jsonl` 文件名、header 快照校验、迁移链。
  - `dsh-session-persistence-jsonl/lib/index.js`：**磁盘布局、projectKey/encodeSegment、zstd 帧、listing、identity 校验**（约 740–960 行布局函数，2880–3560 行读取/枚举）。
  - `dsh-session-persistence/lib/index.js`：`validateStoredEvents`、版本拒绝、append 连续性。
  - `dsh-session-persistence-jsonl/README.zh.md`、`dsh-session/README.zh.md`：官方中文行为说明（磁盘布局、格式代际、持久性语义）。
  - `dsh-workspace/lib/index.js`：workspace 域 schema、`attachSession`、bootstrap、`archivedSessionIds`/`pinnedSessionIds`。
  - `dsh-api-session-controller/lib/types/list.js` + `lib/client.js`：`session.list` 摘要、`blank/updatedAt/title` 规则、投影刷新。
  - `dsh-client-ui-workspace/lib/client.js`：侧边栏分组（workspace 成员 + Ungrouped）。
  - `dsh-session-log-export/lib/index.js` + README.zh.md：官方 ZIP 导出格式（可作为 canonical JSONL 参考）。
  - `dsh-session-projection-cache/lib/index.js`：projcache 域（version 7、per-record、可丢弃）。
  - `dsh-storage-json/README.zh.md`：`single/`per-record` 布局与原子写语义。
- 桌面 app asar（同版本代码，可用 Python 解析 asar header 读取）：`/Applications/DeepSeek Harness.app/Contents/Resources/app.asar` 内 `dsh/node_modules/@deepseek-ai/…`。

## 12. 官方持久化 Schema 对照（权威）

来源：DSH 公开仓库 master 分支 `docs/persistence-schema.json`（`sessionFormatVersion: 4`，`schemaVersion: 1`，**65 个 root / 626 个 node**，`roots` 带有各记录的 sha256 digest 与 `surface` 标记）。它把 v4 的物理 header、envelope union、每个 `event:*` 的 data 形状全部展开为 JSON Schema；本地可用脚本展开任意 root 成字段树（`python3 dump2.py SessionEventEnvelope event:user/message …`）。

已用该 schema 核对本规格，关键结论：

| root / 事件 | 官方 schema 要点（无 `?` = required） |
|---|---|
| `JsonlHeaderLine` | `type:"session"`, `version:number`, `id:string`, `createdAt:number`, `isSeeded:boolean`, `delegationDepth:number` 必填；`cwd?`, `parentSession?`, `origin?:"subagent"`, `agentPreset?` 可选。**与 §3 实测一致** |
| `SessionEventEnvelope` | union：①带 `surfaceOp`（`"append"` 或 `{op:"replace",startSeq,endSeq}`）②带 `surfaceOp` + `sourceEventSeqs?:[number]`（assistant/message）③log-only（无 surfaceOp、无 sourceEventSeqs）。三者都必填 `type/seq/time`，`ignorable?: true` |
| `event:user/message` | data 必填 `content:(text\|reasoning\|image\|file\|tool-call\|tool-addition\|tool-removal …)[]`, `id`, `role:"user"`, `source`（大 union，含 `runtime-context` / `user-approval` / `team-message` / `dsh-session-title-llm` … 至少要有判别 `kind`） |
| `event:system/message` | message 必填 `content/id/role:"system"/source:{kind:"system-prompt"}`；envelope 必须带 surfaceOp |
| `event:assistant/message` | data 必填 `message{content,id,role:"assistant",source:{kind:"model",provider,model}}`, `step`, `stream:[…]`, `turn`；`usage?`（内部 inputTokens/outputTokens 必填） |
| `event:tool/call` | data 必填 `arguments:string`, `callId:string`, `name:string`, `step`, `turn` |
| `event:tool/result` | data 必填 `message{content,id,role:"tool",source:{kind:"tool",callId},toolCallId}`, `step`, `turn`；`message.isError?`、`data.error?{code,name,reason?}`（仅 isError=true 时允许 error）、`meta?`（任意 JSON）、envelope 带 surfaceOp，可带 `sourceEventSeqs` |
| `event:session/title` | data 必填 `title:string`, `messageSeqs:[number]`, `source`（`fallback`/`user`/`provider`） |
| `event:turn/end` | data 必填 `turn` + `reason` union：`completed` / `blocked` / `interrupted` / `max-tokens` / `forked` / `error{code,message,…}` / `aborted{reason:{kind:"user"|"parent"|"hook"|"disposed"|"legacy"}}` |
| `event:turn/start`, `event:step/start`, `event:step/end` | data 必填 `turn`（step/* 还要 `step`） |
| `event:session/end-seed` | data 允许 `{inherited?: true}`（空对象合法） |
| `event:request/header` | data 必填 `header.config{provider,model, maxTokens?,reasoningEffort?,temperature?,stop?}` 与 `reason:"initial"|"resume"|"change"|"series"`；`startsSeries?:true`、`adapterDefaults?{maxTokens?:true,reasoningEffort?:true}`、`tools?[{name,description,parameters}]`；**禁止 `header.system`**（`never`） |
| `event:request/context` | data 必填 `provider`, `model`；`contextWindow?`, `systemPromptUpdate?:"in-history"` |
| `event:permission/preset` | data 必填 `preset:string`（**任意字符串，无枚举校验**） |
| `event:sandbox/mode` | data 必填 `mode:"read-only"|"workspace-write"|"danger-full-access"`，`source?:"delegation"` |
| `event:approval/policy` | data 必填 `policy:"never"|"ask"`，`source?:"delegation"` |
| `event:job/registered` | data 必填 `jobId/kind/label/owner/startedAt`；`toolCall?{callId,rootCallId}` |
| `event:job/settled` | data 必填 `jobId/kind/label/owner/startedAt/finishedAt/status:"completed"|"failed"|"killed"/cause:"producer"|"teardown"|"kill"/producerReported`；`detail?`, `toolCall?` |

> 注意：**runtime 的 `Session` 构造/读取校验比 JSON Schema 更宽**（例如 `permission/preset.preset` 不校验枚举、`session/title` 缺少 `messageSeqs` 也能被投影读取），但**要生成与 DSH 自产文件不可区分的日志，应以官方 schema 为准**。本规格 §6 的模板已按官方 schema 写全必需字段。

## 13. 样本清单（`samples/dsh/`）

| 文件 | 内容 |
|---|---|
| `01-minimal-valid-session.jsonl` | 本规格 §6 的最小会话（17 事件，含工具调用），已用 DSH `Session.fromRestore` 验证通过；可直接转 zstd 导入 |
| `02-real-session-excerpt.jsonl` | 真实会话前 38 行 + 收尾 2 行（长字符串截断到 260 字符），展示真实字段/顺序/stream 结构 |
| `03-observed-event-catalog.json` | 5 个真实 session 汇总出的 32 种事件类型，各 1 条截断示例 + 出现次数 |
| `04-workspace.json` | 本机真实 `~/.dsh/storages/workspace.json`（结构参考；id/路径为原值） |
| `05-projcache-excerpt.json` | 真实 projcache 记录（identity + title/turnBoundary/sessionStats/tokenUsage 等行，值截断） |
| `06-import-template.py` | 生成最小 session 目录（含 projectKey/encodeSegment 实现与双帧压缩），仅演示，默认写到 /tmp |
