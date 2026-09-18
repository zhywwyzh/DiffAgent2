# l3 与 l4 的 RPC 传输契约

Status: implemented
Contract-ID: l3-dispatcher/l4-rpc
Parent: specs/implemented/l3-dispatcher.spec.md

> 定义站端调用 l3 的线上信封、连接发现和结果投递。通用控制面已由真实站端消费者和隔离传输测试验证；生产飞行能力仍按工具面集合判定。
> 工具集合、准入、租约状态机和终态账本归 `l3-tool-plane.spec.md`；技能和动作
> 完成语义归对应能力契约。本叶不新增另一套注册表、租约账本或任务身份。

## 1. 单入口与身份

- 请求入口唯一为 `lx/<stack-id>/rpc`，JSON 对象包含 `method` 字符串与
  `params` 对象；这不是另一个标准 JSON-RPC 2.0 接口，不新增 `id`/`jsonrpc` 包装。
- 调用方法名直接等于注册工具名，不设 canonical 别名、任务编号或兼容路由。
- 执行参数直接放在 `params` 内，另含 `call_id` 和 `context`；不得要求站端再套
  `arguments`、`name` 或内部工作流字段。剥离传输字段后由唯一工具 schema 校验业务参数。
- `call_id` 是上游给定的非空关联键，l3 不重铸、不改写；空白串拒绝。安全命令携带的
  `safety_` 前缀也是普通关联键，不提供租约豁免。
- `context` 必须携带当前 `station_id`、`station_instance_id`、`lease_id`。
  `stack_id` 由 key 定位，不新增为调用 payload 的必填字段。
- 上游不提供 `flight_session_id`、`step_id`。已有内部诊断字段不得成为额外准入条件、
  RPC 关联键或能力分发依据；它们也不得被当作物理飞行会话或返航原点身份。

## 2. 发现与连接

- l3 在 RPC 接口准备好后声明 `lx/<stack-id>/presence/task/<instance-id>` 的
  liveliness token；实例标识每次运行独立。关闭或启动失败时释放已获取的资源。
- presence 只证明任务控制面在线，不证明生产技能存在、飞控已就绪或飞机可飞。
  不冒充 `telemetry`、`logs` 平面的在线状态。
- `connection.acquire` 参数为 `station_id`、`station_instance_id`；允许站端附带
  `request_id`，它只是连接请求信息，不成为任务编号或工具调用键。
- `connection.renew` / `connection.release` 参数为身份三元组；
  `connection.status` 接受空对象并免租约查询。
- acquire/renew 成功结果在 `rpc_result.result` 内直接携带 `accepted=true`、
  `stack_id`、身份三元组、`ttl_ms`、`expires_at`；不再嵌套 `lease`。
  `expires_at` 是 UTC ISO 时间；超时判定使用单调时钟，墙钟只用于展示。
- TTL 遵循工具面现行默认 15 秒，站端按服务端返回值更新到期时间，每次续约不慢于
  5 秒。不得将站端的 60 秒兜底常量视为必须修改服务端 TTL 的依据。
- release 返回 `released=true` 及被释放身份；活动调用存在时拒绝。status 提供
  `stack_id`、`owned`、`state`、`ttl_ms`、`ts`，有主时再含 `station_id`、
  `expires_at`，不泄漏可用于控制的租约令牌。
- 成功 acquire 后监听当前 owner 的
  `lx/stations/<station-id>/connection/<lease-id>/<stack-id>`；使用历史订阅。
  重复 acquire 不重复叠加监听。旧监听的迟到回调不得影响后续租约。
- acquire 返回后站端才声明 connection token；订阅尚未收到 token 不等同于 DELETE。
  当前 token 的 DELETE 触发现行有序租约丢失流程；TTL watchdog 同时保留。
  监听建立失败必须可观测，TTL 仍保证到期失效；不得伪报监听已生效。
- 租约丢失停止准入，取消当前调用，再请求核心安全停止；失败时保持取消中。
  成功发出安全停请求不等于飞机已经悬停。

## 3. 查询回复

- 成功信封为 `{"type":"rpc_result","method":...,"result":...}`。
- 拒绝信封为 `{"type":"rpc_error","method":...,"reason":...,"message":...}`。
  reason 使用工具面现行传输词表，不为迁移另建错误系统。
- 执行准入结果为 `{"accepted":true,"call_id":...}`，只表示准入；其键集不同于
  进程内 runtime ack。不得用该结果推动“动作已完成”。
- 每个收到的 query 生成一个完整回复；非法 JSON、非对象顶层、缺失或错误类型的
  method/params 均回 `invalid_arguments`，不让解析异常逸出并悬挂请求。
  不可识别的方法回 `method_not_found`；有名称但缺 call_id 的执行请求回
  `invalid_arguments`。无法读取 method 时错误信封中的 method 使用空串。
- 同 call_id 重试也必须先经过当前 owner 门：合法同载荷重放返回原准入结果且不重复
  排队；不同载荷回 `invalid_arguments`；失效租约回 `connection_not_owner`。
- 未准入调用不产生完成事件。网络无回复属于站端传输失败，不伪造成服务端已完成。

## 4. 终态投递

- 唯一任务结果频道为 `lx/<stack-id>/rpc_outcome`；承载终态，不承载 running 相位。
- 信封固定为 `{"type":"rpc_outcome","method":...,"call_id":...,"outcome":...}`。
  method 和 call_id 与准入请求一致，不产生额外关联编号。
- 成功 outcome 含 `ok=true` 和对象类型的 `result`；result 至少含
  `completion`，值采用该工具的 `lx.completion`。能力结果字段由能力契约定义。
- 失败 outcome 含 `ok=false`、`reason`、`message`；租约丢失映射为
  `connection_not_owner`，取消、抢占及执行失败使用 `wrong_state`，message 保留
  可诊断原因。进程内更细的错误码不因 wire 投影而丢失。
- outcome 从同一个 runtime 终态记录产生，不设独立的业务终态写入方；一次准入只提交
  一个终态。快速同步完成、抢占、租约丢失和重复回调均不能丢失关联或重复提交。
- 必须在执行可产生终态前建立关联；不以“admit 返回后再记 method”的顺序依赖线程调度。
  拒绝请求不留下关联；同载荷重放不重新建立已经消费的映射。
- 站端在发送调用前订阅结果，且可接收早于查询回复的 outcome；服务端不应依赖网络
  对两个通道的先后排序。测试必须覆盖 outcome 先于 ack 到达。
- “终态唯一”约束业务提交，不承诺 pub/sub 跨断线恰好一次送达。发布失败必须留诊断，
  不能变更已经提交的动作终态或重复执行动作。上游当前没有结果游标恢复接口；
  本轮不设计无人消费的补发路由，也不声称断线重连能够自动恢复漏收结果。

## 5. 操作面边界

- 当前站端采用静态工具词汇，不调用工具发现、游标 events 或通用 cancel 的 wire 方法。
  runtime 的注册表、revision、事件重放和取消仍按工具面契约保留并验证。
- 本轮不新增 `tools/*`、发现/轮询/取消 RPC 方法，也不恢复已删除的资源入口。
  站端取消批次会提交一个独立 `basic_flight.emergency_stop` 调用；这不等同于
  进程内 cancel，亦不改变“取消不隐含急停”的通用规则。
- 生产工具集合以 l3-tool-plane 契约为准。测试能力只能使用测试注册表，不能以
  “联调探针”名义开放生产空实现。

## 6. 验收

> **统一声明**：除非使用者明确许可，否则跳过验收测试工作（`AGENTS.md` 硬性约束 §9）。

| 标识 | 判据 |
|---|---|
| RPC1 | task presence 被站端解析；acquire/renew/status/release 的真实消费者读取结果正确 |
| RPC2 | 原始请求字节经 queryable 进入 schema 校验，非法输入每次得到一个拒绝信封 |
| RPC3 | 测试能力从准入到站端账本终态闭环；快速完成、outcome 先到、重复回调均不丢关联 |
| RPC4 | 同载荷重试不重复执行，冲突拒绝；租约失效后重试不能绕过 owner 门 |
| RPC5 | 当前 owner token 删除、TTL 到期、旧回调迟到、安全停失败及重试符合有序租约状态机 |
| RPC6 | 生产集合与工具面契约一致；不新增别名、任务编号或站端代码改动 |
| RPC7 | 关闭/启动失败逆序释放 queryable、publisher、presence、watch 与线程；真实传输验证与进程内测试分别留证 |
