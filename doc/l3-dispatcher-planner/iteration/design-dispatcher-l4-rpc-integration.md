# dispatcher 与 l4-agent 对接闭环迁移方案

> 摘要：在 basic-flight 进入生产前，先补齐已有控制面的连接生命周期、请求拒绝和
> 终态投递，并用工作区 `l4-agent` 的真实消费者验证。只改 DiffAgent2 新版 l3；
> `l4-agent/` 是只读接口样本。这里迁移的是通用对接能力，不提前注册飞行占位工具。

## 0. 元信息

| 项 | 值 |
|---|---|
| 日期 | 2026-09-16 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/`、对应测试及统一 `specs/` |
| 状态 | done |
| 当前交付 | 2026-09-17：S1/S2 通用实现、回归和真实回环传输验收完成；生产集合仍空 |
| 执行总纲 | [执行顺序与文档导航](design-dispatcher-migration-execution-order.md)，本方案对应 S1–S2 |
| 上游来源 | 工作区 `l4-agent/`，只读取现有 RPC、fleet、flight bridge 和工具词汇，不修改其任何内容 |
| 关联文档 | [RPC 契约提案](../../../specs/implemented/inner/l3-l4-rpc.spec.md)、[基础飞行方案](design-dispatcher-basic-flight-migration.md)、[工具面契约](../../../specs/implemented/inner/l3-tool-plane.spec.md)、[台账](../rest/dispatcher-deferred-dependencies.md) |
| 路径约定 | `L3/` = `l3-dispatcher-planner/ros_packages/dispatcher/`；`L4/` = `l4-agent/src/copaw/`；其余路径从仓库根起算 |

## 1. 背景与动机

**应先完成对接闭环，再开放 basic-flight。** 新版已有 RPC 和租约骨架，不能把这一轮
写成“整个 l4 接口尚未迁移”。缺口集中在生命周期接线、并发终态关联和真实消费者验收。
这些问题与飞行算法无关，先用测试技能隔离验证，可避免将“上层没收到完成”误判为飞机
没完成动作。方案准备可以并行，生产接入以本轮验收通过为前置。

站端实际协议是单 key 请求和终态推送，不依赖工具发现或 events 游标轮询。
此前工具面方案附录所记“补发现/取消/轮询 wire 方法”，在本轮没有站端消费者，
不作为 basic-flight 的前置项；保留 runtime 内部机制，不恢复旧 `tools/*` 入口。

## 2. 现状事实（问题清单）

| 证据 | 事实与判断 |
|---|---|
| `L4/station_sidecar/rpc_plane.py:93,166,192` | 请求 `{method,params}`；业务参数平铺，携带 call_id/context；订阅 `rpc_outcome`。没有 discovery/events/cancel 客户端方法 |
| `L4/station_sidecar/fleet.py:95,283,440` | 解析 task presence 后才允许 acquire；仅 RPC key 可达不足以让站端选中 stack |
| `L4/station_sidecar/fleet.py:458,624` | acquire 与 renew 读取平铺 result 的 lease_id、ttl_ms、expires_at；60 秒只是本地兜底，服务端返回值优先 |
| `L4/station_sidecar/flight/rpc_bridge.py:102,227,246,319` | 先订阅结果，再发送调用；accepted 只改为 running，嵌套 outcome.ok 才写终态 |
| `L4/station_sidecar/flight/service.py:315` | 取消批次先结束站端记录，再发送独立 basic_flight.emergency_stop，不调用通用 cancel RPC |
| `L3/dispatcher/utils/zenoh_rpc.py:111,119,149` | task presence、RPC 启动、runtime event sink、watchdog 已在新版，无需重搬 |
| `L3/dispatcher/utils/zenoh_rpc.py:270` | `_watch_owner_token` 已定义，但全 l3 符号检索只有定义，成功 acquire 没有调用；提前断开只能等待 TTL |
| `L3/dispatcher/utils/rpc_plane.py:250,258` | admit 入队后才登记 `_method_by_call`；消费者可立即终结，on_event 找不到 method 而丢 outcome |
| `L3/dispatcher/utils/rpc_plane.py:159` | 顶层 payload 的 `.get()` 在异常保护外；JSON 数组导致 AttributeError，不返回完整拒绝 |
| `L3/dispatcher/tools/runtime.py:100` | 同载荷重放先返回 previous.ack，owner 校验在其后；失效租约可以得到 accepted |
| `L3/dispatcher/utils/rpc_plane.py:259` | 仍有 legacy/canonical 注释，但实际 canonical=method；关联表是 call_id→方法，不是任务编号，不应整表机械删除 |
| `l3-dispatcher-planner/tests/tool-registry/test_rpc_plane.py:59` | 现有测试在准入返回后才 emit，未覆盖快速同步完成、真实 station 解析和重放竞态 |

本轮只读复现（未改实现）：在 admit 返回前触发终态，得到 accepted 且 outcome 数为 0；
输入 `[]` 抛 AttributeError 且回复数为 0；租约失效后相同调用仍返回 accepted。
这些是前置修复依据，不是已修复结果。

只读来源摘要（SHA-256 前 12 位，2026-09-16 读取前后保持一致）：

| L4 相对路径 | 摘要 |
|---|---|
| station_sidecar/rpc_plane.py | `27d9fe750783` |
| station_sidecar/fleet.py | `0b8ce1dc0670` |
| station_sidecar/flight/rpc_bridge.py | `7f937c6508a8` |
| station_sidecar/flight/service.py | `491fbff1eca0` |
| station_sidecar/flight/models.py | `8c09be0f4a6e` |
| agents/tools/plan_tools.json | `ee418edb880f` |

## 3. 目标与约束

- 目标：task presence → acquire → renew → 调用准入 → 唯一终态推送 → 站端记录完成，
  以及 release/丢租约安全停，形成可复现的通用闭环。
- 非目标：不修改 `l4-agent/**`；不迁飞行技能、遥测、日志、感知、VLA、场景查询；
  不新增生产探针，不修改飞机侧规划算法，不声称已有实机安全停证明。
- 只读 l4 是此次接口证据，不把其仓库说明或旧版 spec 自动升级为本仓库权威。
  规范先在统一 specs/proposed 落地；采纳后才更新 implemented 归属。
- 无别名、无旧接口桥接层、无编号、无双账本。现有传输适配器直接实现目标接口，
  不新增新旧协议转换服务。ROS 收发边界继续遵循现行适配契约。
- 生产工具集合和 revision 本轮始终为空集基线；测试注入不得改变默认集合。

## 4. 方案决策

### 4.1 目标目录与命名

```text
l3-dispatcher-planner/
  ros_packages/dispatcher/dispatcher/
    utils/
      rpc_plane.py             # 请求信封、原始名字、终态序列化
      zenoh_rpc.py             # session/presence/owner watch 生命周期
      connection_lease.py      # 唯一租约账本
      control_plane.py         # 通用执行消费与关停
    tools/runtime.py           # 唯一调用与事件账本
  tests/tool-registry/
    test_rpc_plane.py
    test_connection_lease.py
    test_l4_rpc_contract.py     # 本轮新增，站端消费者验证
```

| 类型 | 规范 | 示例 |
|---|---|---|
| Python 模块/函数 | snake_case，沿用职责清晰的现有模块 | rpc_plane.py、on_event |
| 类型 | PascalCase | RpcPlane、ToolRuntime |
| 线上方法 | 与站端完全一致，不做别名 | connection.acquire |
| 测试 | test_行为，明确触发条件 | test_terminal_before_admission_reply |
| 测试工具 | test.*，只在测试注册表出现 | test.start |

### 4.2 复用面与接口裁决

复用 RPC key、outcome key、presence 格式、连接四方法、租约与调用账本。
字段和错误信封以 [RPC 提案](../../../specs/implemented/inner/l3-l4-rpc.spec.md) 为目标；
本方案不另立一份 wire schema。默认 TTL 继续 15 秒，验证当前 l4 使用返回值即可，
不因客户端 60 秒兜底而改变现行服务端契约。

只允许测试 fixture 显式注入测试注册表；生产构造仍使用 ToolRegistry.default()。
若装配需要增加注入点，应落通用构造参数，不增加生产可配置的“开放测试工具”开关。

### 4.3 终态关联：消除先入队后登记窗口

直接从唯一 runtime 终态记录中读取原始 `name` 与 `call_id`；现有
`L3/dispatcher/tools/runtime.py:405` 的事件已同时携带这两个字段，移除不再需要的
`_method_by_call`。关联不应依赖第二份可被重放重置的映射。
测试/进程内直接 emit 只通过测试连接发送，生产调用统一经 RPC；如需区分事件是否应
出站，以同一调用记录的来源属性表达，不再新建第二张业务状态表。

若事件字段调整，应同批更新 runtime 事件测试和现行工具面字段说明；先建立完整的
终态数据再允许执行。重复终态由 runtime 拒绝，同载荷重放只返回 ack；已经完成的
调用不得因重放再次提交 outcome。允许 outcome 比查询回复先到，不用跨通道排序
掩盖竞态。发布失败记录诊断，不能重跑飞行动作补结果。

### 4.4 owner 生命周期与重放

成功 acquire 返回的身份用于建立 watch，重复 acquire 复用相同监听。watch 回调捕获
其对应的租约身份，处理 DELETE 前再次确认当前 owner；旧回调不得终结新租约。
释放/丢失/关停均释放 watch，部分启动失败逆序回收资源。不能把未收到 PUT 当作断开。

runtime.admit 在重复调用快速返回前也检查 owner；身份验证、幂等判定和排队的并发边界
一起审查，避免“检查时有效、排队时已失效”执行旧任务。消费端继续使用 can_execute
防止已取消命令重新执行。监听异常由诊断和 TTL watchdog 兜底，安全停异常仍 fail-closed。

### 4.5 完整拒绝与消费者测试

在访问 payload 成员前验证 JSON 对象、method 与 params 类型；所有解析及业务失败走
统一拒绝信封。保留未知工具与缺 call_id 的确定性拒绝，不在传输层追加领域参数。

测试放在 l3，读取当前 l4 的 RpcPlaneClient、FleetController 和 RpcFlightBridge 的
真实消费者代码；用受控 session、时钟及配置替身隔离网络与落盘。不得调用站端生产
配置服务、写站端 ledger 文件或修改其源码。设置 PYTHONDONTWRITEBYTECODE=1，缓存
放临时目录。缺少只读 l4 样本应明确报告此项无法验收，不能跳过后宣称对接通过。

分两层验收：受控 session 验证字节与生命周期；本地隔离 Zenoh 会话验证真实传输。
前置轮次只证明协议闭环和安全停端口被正确调用，R03 的制动悬停仍由飞行轮次验收。

### 4.6 规范归属与有意变更

本次仅新增 proposed RPC 叶。代码轮次交付时将整叶移至 implemented 并加入 l3 根表；
同时调整 tool-plane §3/§7/§8/G25 的范围说明：进程内 ack/event 与线上 admission/outcome
是不同信封，线上格式统一指向新叶。不删除内部事件游标与取消机制，不伪称有线上入口。

有意行为修复为：非法顶层请求由异常变成拒绝；失效租约重放由 accepted 变为拒绝；
当前 owner token 删除能够在 TTL 前触发丢失；快速终态不再丢失。方法名、业务参数、
成功信封及租约 TTL 不变。修复无需 l4 变更，也不提供旧错误行为兼容模式。

## 5. 迁移映射表

| 来源单元 | 目标 | 裁决/动作 | 调用方证据 |
|---|---|---|---|
| 已迁入的 RpcPlane | 原模块 | rewrite，完善信封和终态序列化 | l4 RpcPlaneClient/RpcFlightBridge |
| `_method_by_call` 二次关联 | runtime 终态中的 name/call_id | merge 后删除冗余映射 | l4 outcome 消费者 |
| 未接线 `_watch_owner_token` | 现有中间件连接生命周期 | rewrite，接 acquire/release/丢失 | l4 FleetController 的连接 token |
| runtime 重放快速返回 | 原 admit | rewrite，owner 门先行 | l4 相同 call_id 重试 |
| lease manager、presence、内部 events/cancel | 原归属 | 保留并回归，不搬重复副本 | 现有控制面与核心取消链 |
| 旧别名和 tools/*、发现/轮询新路由 | 无 | 不迁移 | 当前 l4 没有消费者 |
| l4 客户端与账本 | l4 原地只读 | 不迁入、不编辑 | 作为真实接口和验证消费者 |

## 6. 删除清单

| 项 | 理由 |
|---|---|
| 终态事件已能直接关联后，RpcPlane 的重复 method 映射与相关清理 | 消除竞态及重放残留；不是删除 call_id 关联能力 |
| rpc_plane 中不再符合实际的 legacy/canonical/tools 路由注释 | 删除已失效说明，不保留旧入口 |
| 新实现替代的解析或监听旧分支 | 同批删除，禁止兼容开关与空实现 |

这里不授权删除 DiffAgent2 旧版或 l4 的任何内容，不清理 R01–R07 保留字段。

## 7. 实施步骤

### P0 — 契约与基线（当前文档轮次）

- 范围：本方案、RPC 提案、基础飞行方案及关联台账入口。
- 不变式：生产代码、l4、现行集合和 revision 不变；状态为 proposed。
- 验收：文档结构/相对链接/header/隐私检查；记录现有测试限制和只读复现。
- 回退：只撤销本轮文档增量，保留工作区已有修改。

### P1 — 通用 RPC 和租约修复

- 范围：原模块修复解析、快速终态、重放 owner 门、owner watch、关闭与部分启动失败回收。
- 不变式：空生产集合、原始名字、唯一 runtime/lease 账本；不改 core 领域职责。
- 验收：新增竞态/拒绝/生命周期测试，既有 tool-registry 与 core-boundary 全绿。
- 回退：整体撤销此批实现和测试；不得保留半接线监听或第二种协议。

### P2 — 只读 l4 消费者与隔离传输验收

- 范围：l3 的 test_l4_rpc_contract.py；测试注册表闭环，无飞行副作用。
- 不变式：l4 树零写入；真实生产默认仍为空；不对现场飞机执行调用。
- 验收：§8 的测试矩阵，分别记录受控 session 与真实 Zenoh 证据。
- 回退：去除本轮测试装配增量；对接未通过时不开放 basic-flight。

### P3 — 采纳与归档

- 范围：RPC 提案整叶晋升、根表、tool-plane 范围说明、rest 索引和新架构决策记录。
- 不变式：只采纳已验证行为，空集 revision 保持原值。
- 验收：RPC1–RPC7、G24–G28、根叶一致；方案置 done 时附证据和剩余限制。
- 回退：契约与实现整体恢复；不能只回退实现而保留已交付表述。

本轮结束时应可运行测试能力的 l4↔l3 闭环，**真实基础飞行仍不可运行**；恢复轮次为
基础飞行方案 P2–P4。无法完成真实传输验收时保持 in-progress，不把 mock 通过当作 done。

## 8. 验收标准

| 场景 | 必须结果 |
|---|---|
| task presence PUT/DELETE、重复实例 | l4 可发现；无 task token 不可 acquire；身份冲突不误连 |
| acquire/重复 acquire/renew/status/release | 真实消费者读取平铺结果；监听不泄漏；活跃 release 拒绝 |
| 合法测试调用 | accepted 与 outcome.ok 分别被真实站端消费者消费；参数原样进入技能 |
| 即时完成/outcome 先到 ack/重复 emit | 恰一个业务终态，不回退站端 done 到 running |
| 重试/冲突/丢租约后重试 | 不重复执行、冲突拒绝、旧租约拒绝 |
| JSON 数组/null/标量/坏 JSON/缺字段 | 一个完整 rpc_error，无悬挂回调 |
| token DELETE/过期/监听失败/旧回调 | 当前租约正确失效；TTL 有效；旧回调不影响新 owner |
| 安全停异常及重试 | 维持取消中，不释放成无主；恢复后完成有序清理 |
| 空默认集合 | 所有未迁入生产工具仍 method_not_found，revision 不变 |
| pub/sub 中断/发布失败 | 有诊断，不重执行，不承诺无消费者接口支撑的自动恢复 |
| close/启动中途失败 | 资源逆序释放、线程可结束、不留 presence 假在线 |

代码轮次在已安装项目测试依赖的环境，从仓库根执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider l3-dispatcher-planner/tests/tool-registry l3-dispatcher-planner/tests/core-boundary
```

真实传输测试需要隔离 Zenoh 会话和只读 l4 Python 依赖；不得接入生产 router。
spec 门禁脚本尚未迁入，以 header/Parent/根表/链接与既有 pytest 作等价检查。

2026-09-16 文档轮次基线：完整测试收集受 `ModuleNotFoundError: zenoh` 阻塞；缩小到
RPC/registry/core 文件后 64 passed、1 failed，失败同为装配导入缺少 zenoh。未报告全绿。
全 specs 结构检查另发现既有 log.spec.md 的 Parent 指向尚不存在的 observability 根；
属既有独立问题，本轮不改日志契约，不把全库结构检查报告为通过。

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| 将已有骨架当成缺失并重复搬代码 | 依据 §2 逐项修复，复用原账本和原模块 |
| l4 本地样本更新后证据过期 | 测试读取真实消费者，交付时记录来源版本/文件摘要；不复制生产客户端到 l3 |
| mock 验证掩盖传输时序问题 | 将真实 Zenoh 验证单列，缺条件保持未验收 |
| outcome pub/sub 无持久补发 | 明确限制；不以新增无人消费游标方法掩盖丢包风险 |
| 修监听后暴露安全停物理链缺失 | 前置只证明端口调用；R03 由飞行轮次提供制动悬停证据 |
| 测试导入站端时访问配置/写缓存 | 控制配置端口、临时缓存、禁字节码，确认 l4 来源文件未变 |

## 10. 修改点清单汇总

| 文件 | 动作 | 所属阶段 |
|---|---|---|
| 本方案、specs/implemented/inner/l3-l4-rpc.spec.md | 新增 | 当前文档轮次 |
| 基础飞行方案、rest/README.md、rest 台账 | 更新依赖和证据状态 | 当前文档轮次 |
| L3/dispatcher/utils/rpc_plane.py | 修解析和终态序列化 | P1 |
| L3/dispatcher/tools/runtime.py | 重放 owner 门及事件关联核对 | P1 |
| L3/dispatcher/utils/zenoh_rpc.py、connection_lease.py | owner watch 接线与生命周期 | P1，lease 文件仅确需时改 |
| L3/dispatcher/utils/control_plane.py | 启动/关闭线程生命周期和必要测试注入 | P1 |
| l3-dispatcher-planner/tests/tool-registry/ | 新增消费者测试、扩展现有回归 | P1/P2 |
| specs/implemented/inner/l3-l4-rpc.spec.md、l3 根表、l3-tool-plane.spec.md | 晋升新叶与归属说明 | P3 |
| specs/implemented/architecture/日期-dispatcher-l4-rpc-integration.md | 完成时新增冻结决策，不改旧决策 | P3 |

`l4-agent/**` 不在任何阶段的修改清单中。

## 11. 执行记录（2026-09-17）

- S0：临时隔离环境安装测试依赖，原有基线 83 passed；未修改 l4 或生产配置。
- S1：完整请求拒绝、直接由 runtime name/call_id 生成 outcome、重放 owner 门、
  acquire/watch 接线、旧回调身份检查、部分启动失败清理和可中断关闭均已实现。
  租约与 runtime 锁顺序统一为 lease→runtime，准入与失租约/释放串行；TTL 丢失再次
  检查当前有效期，避免旧到期判断误伤续约。
- S2：总计 103 passed。新增测试直接只读加载 l4 的 RpcPlaneClient、FleetController、
  RpcFlightBridge 和模型，禁字节码写入并检查源码摘要。真实 Zenoh 仅监听回环随机端口，
  覆盖 presence、acquire/renew、调用、终态、幂等重放、token DELETE 和失租约拒绝；
  确定性测试覆盖 outcome 先于 ack、重复实例、无 presence、非法输入和发布失败。
- 资源回归验证部分启动失败释放句柄、重试等待可中断并回收工作线程；现有 TTL、
  fail-closed 安全停及恢复测试全部通过。此处安全停为注入端口，未证明实机悬停。
- RPC 叶已整叶晋升并挂根表；tool-plane 明确进程内 ack/event 与 wire 信封边界。
  测试依赖记录在 l3-dispatcher-planner/tests/requirements.txt。

复现命令（仓库根；环境需允许本机回环 socket）：

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --isolated --no-project --with-requirements l3-dispatcher-planner/tests/requirements.txt python -m pytest -q -p no:cacheprovider l3-dispatcher-planner/tests/tool-registry l3-dispatcher-planner/tests/core-boundary
```

未交付范围：飞行技能、planner 物理执行、结果持久补发；默认生产集合和 revision
不变。既有日志 spec 缺失 Parent 问题仍单独保留，不宣称全仓 spec 完全无缺陷。
