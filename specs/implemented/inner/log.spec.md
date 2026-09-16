# 日志 — 规范格式、采集流水线与站点聚合

Status: implemented
Contract-ID: observability/log
Parent: specs/implemented/observability.spec.md

> 整个日志平面的唯一权威：每个 l3 进程发出的规范信封、级别词汇表与语义、
> 生产者输出纪律、fluent-bit → 中继 → zenoh 的采集流水线、带跨通道去重的
> 站点摄入，以及 scene-nav 任务聚合。
> 2026-09-16 由五份叶契约（`log-ingest`、`l3-log-format`、
> `l3-log-level-policy`、`ros-log-buffering`、`l3-scene-nav-task-log`）合并，
> 使日志契约能在一处端到端读完。日志 DISPLAY 仍归
> `specs/implemented/inner/l4-visualizer.spec.md`；record 语义与
> 遥测/结果的区分归 `specs/implemented/domain-lang.spec.md`。

## 1. 范围

> 一条流水线、一份 spec：生产者格式 → 传输 → 站点消费者。

§2–§9 拥有生产者侧（信封、级别、不变量、汇点、迁移）；§10–§11 拥有采集
流水线与站点摄入；§12 拥有 scene-nav 任务聚合；§13–§14 拥有现场经验与
验证。

## 2. 规范信封

> 每行一个 JSON 对象；核心键顺序固定，事件字段自由形式，可选键置尾。

```json
{"seq":1,"ts_ns":1760000000123456789,"level":"info","event":"object_nav_goal",
 "node":"drone_0_mission_executive","layer":"mission","stream":"process",
 "target_obj_id":5,"dist_m":12.3,"msg":"前往电视机"}
```

| 键 | 类型 | 必填 | 含义 |
|-----|------|----------|---------|
| `seq` | int | 是 | 每进程单调递增，在记录创建时盖一次 |
| `ts_ns` | int64 | 是 | 纳秒；`use_sim_time` 下用 ROS 时钟，否则用墙钟 |
| `level` | string | 是 | `debug\|info\|warning\|error\|fatal`（§3） |
| `event` | string | 是 | snake_case，每个组件冻结的词汇表 |
| `node` | string | 是 | 裸 ROS 节点名，进程初始化时设置 |
| `layer` | string | 否 | 来源（dispatcher：`comm\|mission`） |
| `stream` | string | 否 | 记录类别：`process\|action\|stop`（dispatcher 任务记录）；缺失 = 遥测 |
| fields | any | 否 | 事件专属；NaN → `null`，±Inf → `±1e999` |
| `msg` | string | 否 | 一句人类可读的话 |

## 3. 级别词汇表与语义

> 生产者与消费者共用一套词汇表；两个遗留的 mission 级别退役。

集合为 `debug | info | warning | error | fatal`。迁移映射：mission slog 的
`warn` → `warning`（枚举序列化变更）；`trace` 退役，
`level_from_string("trace")` 映射为 `debug`；采用后没有生产者再发
`trace`。

级别分配语义：

| 级别 | 含义 | 示例 |
|-------|-------|----------|
| `info` | **人类可读的状态摘要** —— 一句话、语义化、不倾倒原始数值 | 任务准入、目标设定、状态迁移、结果摘要（`前往 电视机 #5, 距离 12.3 m`） |
| `debug` | 机器可读 / 进程细节 —— 数值 tick、迭代计数、走廊几何、航点序列、VLM 中间产物 | `nav_tick`、`object_path_topo_sequence`、`topo_path_iteration`、`opt_finish` |
| `warning` | 异常，降级但继续 | `replan_failed`、`waypoint_batch_aborted`、`nan_cost` |
| `error`/`fatal` | 失败，终态 | 电池低电量、规划器不可达 |

规则：

- 一行日志只有在人类无需上下文即可读懂时才是 `info`；坐标矩阵、位姿与
  序列按定义属于 `debug`。
- `debug` 事件承载机器字段；伴随的人类可读 `info` 事件可以总结同一动作
  （一行、语义化）。
- 结构化诊断路径中的裸 `printf`/`std::cout`/`ROS_INFO` 是缺陷 ——
  迁移到 slog。

建议的 `info` 形态 —— 语义化字段，绝不使用原始矩阵：

```json
{"event":"object_nav_goal","target_obj_id":5,"target_label":"tv",
 "dist_m":12.3,"path_size":8}
{"event":"state_transition","from":"OBJECT_APPROACH","to":"OBJECT_REACHED"}
```

每个动作一条 `info` 摘要（设定目标 / 完成 / 失败）；数值细节位于配对的
`debug` 事件中。

## 4. seq 与 node 不变量

> seq 是跨通道关联键；node 是聚合键。

- `seq` 只在记录创建时、在规范发射器内部盖一次；每个汇点携带同一个值。
  发布 `seq` 的通道必须是稠密的（不做策略丢弃），这样站点侧的间隙检查
  才成立。
- `node` 在进程初始化时设置（C++ `slog::set_node`，Python 等价物），且
  每条记录上都非空。无法为自己命名的进程是缺陷。

## 5. 汇点、通道与门控

> 一条记录扇出到 N 个汇点；信封与通道无关。

| 汇点 | 门控 | 说明 |
|------|--------|-------|
| stdout | `telemetry/level` 门 | fluent-bit → `lx/<stack-id>/logs`（§10）—— 自 rosout 汇点默认关闭（2026-09-15）以来的唯一结构化通道；`slog_ros::install_rosout_sink` 仍会盖节点名，并保留为显式可选（`telemetry/rosout_en:=true`） |
| 追踪文件 | 从不受门控 | 追加式 JSONL，权威决策轨迹（dispatcher） |
| zenoh `agent_log` | 从不过滤 | 稠密 FIFO put，载荷 `{session_tag, stream, log_path, record, seq}`，其中 `seq` = `record.seq`；`agent_log/snapshot` 查询不变 |
| rosout 汇点 | 默认关闭 | `/rosout` 采集已退役 |

站点侧消费者：l4-visualizer 服务器在自己的会话上订阅
`lx/<stack-id>/agent_log` —— 它检查每流 seq 连续性（间隙会以自己的
`agent_log_seq_gap` 警告条目浮现），并按 `(stack, node, seq)` 与 stdout
通道去重，使一条记录只显示一次（§11）。

## 6. dispatcher 合并（slog + 记录）

> `RecordingService` 决定记录什么；规范发射器是唯一的记录创建点；
> 镜像写路径已删除。

- `_append_process_record` / `_append_action_log` / `_append_stop_log`
  变为 `telemetry.emit(level, event, stream=..., **fields)` 之上的字段装配
  包装；事件保留既有轨迹名 `process_record` / `action_log` / `stop_log`。
- 独立的 `_agent_log_latest_seq` 计数器删除 —— 上行载荷复用 `record.seq`。
- `_trace_append_record` 镜像路径删除（追踪汇点直接从 `emit` 收到记录）。
- 上行策略为稠密：退避记录过滤器删除，`stop_log` 记录像其他记录一样上行。
- 遗留任务记录字段归一化：浮点 `timestamp` → `ts_ns`；记录新增
  `level=info`、`node`、`stream`。快照 JSON 文件（process/action/stop）
  保持其对外形态（`agent_log/snapshot` 契约）。
- 模块级 dispatcher 代码（技能、中间件、vlm 客户端）通过进程单例发射器
  发出，使进程内每条记录共享同一个单调 seq。

## 7. 生产者输出纪律

> 容器中 glibc 对管道 stdout 做块缓冲 —— 每个输出诊断信息的 ROS 节点都
> 必须行缓冲，否则 `kubectl logs` 会滞后数分钟。

ROS 节点的 `ROS_INFO` / `ROS_DEBUG` 消息走 **stdout**；
`ROS_WARN` / `ROS_ERROR` 走 **stderr**。在容器运行时下 stdout 始终是管道，
于是 glibc **块缓冲**它：只有累积约 4 KiB 后、或进程退出时才刷出（根因于
l2-px4ctrl 上发现并修复，2026-08-16）。

强制要求 —— 每个打印诊断信息的 roslaunch `<node>`：

| 属性 | 规则 |
|----------|------|
| 缓冲 | 通过 `launch-prefix="stdbuf -oL -eL"` 让 stdout **和** stderr 行缓冲 |
| 控制台 | 保留 `output="screen"`（roslaunch 把节点输出转发到自己的 stdout） |
| 顺序 | 在**同一个** `<node>` 元素上同时设置 `launch-prefix` 与 `output="screen"` |

```xml
<node pkg="px4ctrl" type="px4ctrl_node" name="px4ctrl" output="screen"
      launch-prefix="stdbuf -oL -eL">
```

适用于 lx-real 容器中运行 ROS 节点的每一层
（l0-mid360-mavros-realsense、l1-lio、l2-px4ctrl、l3-dispatcher-planner）。

缓冲控制的是**可见性**，不是**量**。日志频率由节流
（`SLOG_*_THROTTLE` / `ROS_*_THROTTLE` / FSM 循环节流）设定并独立调优：

- 健康的每节点状态 INFO：低频率（5–10 s）—— 正确缓冲后仍可读。
- 持续性的台架状态警告（安全开关已触发）：高节流周期（约 10 s），
  使其永不刷屏。
- 主动保护 ERROR（危险电量）可保持 1 s —— 罕见且时效关键。

## 8. 非规范行的层级策略

> 两层合法；来自 l3 的未结构化裸输出是缺陷。

- **A 层（目标）**：规范信封 —— 所有 l3 组件。
- **B 层（遗留/第三方）**：rosconsole `ROSCONSOLE_FORMAT`
  `[/node] [LEVEL]` 前缀 —— roslaunch 自身输出、l0/l1/l2 节点，以及剩余
  的 l3 B 层残留（§9）。消费者解析见 §11.1。
- l3 诊断路径中的裸 `cout` / `printf` / `print` / `std::cerr` 是缺陷；
  迁移表（§9）将其移除。

## 9. 迁移状态

> 以整组件为阶段；每个 l3 阶段均于 2026-09-15 交付。唯一未关闭的 B 层
> 残留逐行记录。

| 组件 | 状态 |
|-----------|-------|
| mission C++ slog | 规范词汇表 + `seq`；rosout 汇点默认关闭；`odom_buffer` 已迁移 —— 已交付 |
| mission py 副本 | 与 C++ 字节一致；`bridge_client` RPC 失败发出信封事件 —— 已交付 |
| dispatcher slog + 记录 | 一个发射器 / 一个 seq / 稠密上行（§6）；模块级代码通过进程单例发射 —— 已交付 |
| dispatcher `rospy.log*`/`print` | 全部迁移到信封事件 —— 已交付（已死的 vendored `parallel_serve_*` / `open_serve_count_video` 函数体未改动） |
| ego_planner | 完整 slog 迁移（入口安装 + 全部源文件 + 头文件）—— 已交付 |
| scene_graph | `ROS_*` 站点迁移到语义事件；`INFO_MSG*` 流宏改指向 slog（颜色→级别：RED→error，YELLOW→warning，plain/GREEN/CYAN→info，BLUE→debug）—— 已交付 |
| bridges (drone_bridge) | 仍有 3 处 `rospy.log*` —— B 层；与共享 py 发射器合并一同迁移（dispatcher 未 catkin 安装进 devel，跨包 import 不可用） |

## 10. 采集流水线

> 日志从 pod stdout 经 fluent-bit 与 loopback-TCP 中继流入 zenoh 网络，
> 最终抵达归属站点的 UI。

### 10.0 实体与角色

> 部署位置区分活动站点与产生日志的 drone-host。

| 部署位置 | NetBird / 主机 | 职责 |
|--------|-----------------|------|
| **station host** | 与主机无关 | 活动站点：l4-visualizer 服务器（`:8391` HTTP UI/控制 + rerun gRPC `:9876`/`:9877`）+ web UI |
| **station-host** | station-host | l4 + l4-visualizer 源码归属 |
| **drone-host** | drone-host | k3s `lx-real`（arm64 生产，原生 containerd）fluent-bit 生产者 |

不变量：

- **所有容器 stdout** 只按其逻辑 stack 键（`lx/<stack-id>/logs`）流入 zenoh
  网络一次；生产者不指定任何汇点地址。持有该 stack 独占连接的站点是其
  唯一合规的详细日志订阅者。
- 日志可视化发生在 **l4-visualizer web UI**（`:8391`）。l4-agent 控制台
  （`:8088`）是另一个产品，不消费这些日志。

```text
任意 pod（jetson 上的 k3s lx-real）
  └─ stdout/stderr → /var/log/containers/*.log（按运行时编码：docker json-file | CRI text，§10.2）
  └─ fluent-bit DaemonSet（tail + kubernetes filter + modify；v3 中只有输出这一跳变了）
     └─ tcp out → loopback 127.0.0.1:18391（Format json_lines；loopback 不作为寻址 —— fluent-bit 3.1 的 out_tcp 没有 unix_path）
           └─ lx-log-relay sidecar（原样转发行，零重新序列化）
                └─ zenoh pub lx/<stack-id>/logs  (Reliability=RELIABLE, CongestionControl=BLOCK)
                  └─ zenohd router（唯一的拓扑常量；中继与汇点都向外连接）
                      └─ 归属站点 l4-visualizer 订阅者（自有会话）→ 同一条摄入流水线（§11.1）
                        → rerun "logs" 录制 → gRPC :9877 → 浏览器 web 查看器
```

寻址不变量（v3）：**任何 Jetson 侧配置中都不存在 agent 站点主机地址，也
不存在汇点地址**。

- 中继与 l4-visualizer 服务器各自向路由器引导端点打开自己的 zenoh 会话
  （client 模式，会话分离规则）。设备侧中继解析 `ZENOH_ROUTER`（k3s
  manifest）> 路由器拓扑常量；站点侧 visualizer 解析配置库行
  `lx_zenoh_router` > 路由器拓扑常量（`agent-station-channels.spec.md`
  §1.0）。
- 路由器丢失由 zenoh 重连吸收；fluent-bit 的
  `storage.type filesystem` + `Retry_Limit False` 在磁盘上缓冲整个中断
  期间的记录，因此链路端到端保持至少一次。

### 10.1 规范日志路径 —— 载体说明

> stack 键把任务、遥测与日志平面绑定到同一个逻辑身份。

stack 键 `lx/<stack-id>/logs` 是绑定任务、遥测与日志平面的逻辑身份
（`agent-station-fleet.spec.md`）。

### 10.2 采集器契约（fluent-bit + relay sidecar）

> 一个 pod 两个容器：fluent-bit tail stdout，并通过 loopback TCP 把行
> 交给中继。

一个 pod 两个容器：fluent-bit 与 `lx-log-relay` sidecar（镜像
`lx-log-relay:arm64`，来自 image-registry，manifest 中按 digest 固定；
代码在设备侧仓库 `big_brain/lx-series/lx-log-relay`）。中继在 pod 内监听
loopback `127.0.0.1:18391` —— 无共享卷、无 pod 外部地址。

每个 fluent-bit 部署都必须具备（v3 输出契约）：

| 键 | 值 | 原因 |
|-----|-------|--------|
| `Name` | `tcp` | 原始流输出，无 HTTP 封装 |
| `Host` | `127.0.0.1` | 仅 loopback —— 不是地址；pod 之外无法接收 |
| `Port` | `18391` | 中继的 `LX_LOG_RELAY_PORT` 默认值 |
| `Format` | `json_lines` | 每行一个 JSON 对象；中继原样转发（零重新序列化） |
| `Retry_Limit` | `False` | 永不丢弃分块（中断后清空积压） |
| `storage.type` | `filesystem` | 中继/路由器/汇点不可达时的磁盘积压 |

随 v3 退役：整个 HTTP 输出块（`Host` / `Port 8391` /
`URI /api/logs/ingest` / `Format json` / `Json_date_key off`）。

中继契约（`lx-log-relay`，单进程）：

- 监听 loopback TCP（`LX_LOG_RELAY_HOST`/`LX_LOG_RELAY_PORT`，默认
  `127.0.0.1`/`18391`），读取换行分隔的记录 JSON；
- 把每一行发布到 `lx/<stack-id>/logs`；`LX_STACK_ID` 与任务、遥测平面
  使用同一规范身份；
- 发布者 QoS：`Reliability=RELIABLE` + `CongestionControl=BLOCK`
  （日志量级为 KB/s；耐久优先于延迟；BLOCK 背压由 fluent-bit 的磁盘存储
  吸收）；
- 原样转发记录 —— 中继不拥有解析、不拥有 schema、除 socket 读取外不做
  缓冲；
- 自有 zenoh 会话（client 模式，路由器引导）；
- 中继任何意外失败都会使容器崩溃（k3s 重启它）；期间 fluent-bit 继续
  tail 到磁盘存储。

Tail 输入：`Path /var/log/containers/*.log`，排除 fluent-bit 自身与
`kube-system`。tail 解析器必须匹配节点运行时的日志编码（按运行时选解析器
规则，2026-08-18，issue #87）：

| 节点运行时 | 日志行编码 | Tail 解析器 |
|--------------|-------------------|-------------|
| cri-dockerd（仅历史/其他 stack） | docker json-file `{"log","stream","time"}` | `docker`（json，`time` 键，`Time_Keep On`） |
| 原生 containerd（drone-host，容器标准） | CRI text `<time> <stdout\|stderr> <P\|F> <message>` | `cri`（正则 `time`/`stream`/`flags`/`message`，`Time_Format %Y-%m-%dT%H:%M:%S.%L%z`，`Time_Keep On`） |

解析器/运行时不匹配不会报错。解析按行失败，fluent-bit 把该行整行原样
投递，于是 CRI 信封（stream 标签、`F` 标志、时间戳）泄漏进 `message`，
`ts` 退化为投递时间（2026-08-18 观测到）。modify 过滤器剥离当前变体的
已解析元数据键：docker 为 `stream`；CRI 为 `stream` + `flags`。

`Retry_Limit False` + INPUT 级 `storage.type filesystem` 是契约要求而非
建议：归属站点不可达时，分块绝不能丢弃。

解析器机制（与运行时无关，2026-08-18）：tail 输入不携带解析器；两个叠加
的 parser 过滤器先在原始 `log` 字段上试 `cri` 再试 `docker` —— 过滤器级
解析失败会让记录原样通过，于是第二个过滤器获得机会。这样一份 manifest
同时服务两种运行时。

陷阱：输入级 `Parser` + `Parser_Next` 不是回退链 —— `Parser_Next` 会重新
解析第一个解析器的结果，且第一个解析器失败时该行原样投递、信封泄漏进
message（已在 fluent-bit 3.1 验证）。

`cri` 解析器把部分写入标志捕获为 `flags`，由 modify 过滤器与 `stream`
一同剥离。fluent-bit 仅在启动时读取配置：ConfigMap 变更后必须
rollout-restart DaemonSet。

当前状态：lx-real
`drone_projects/auto_deployer/k3s_config/real/fluentbit.yaml` 合规；
sim DaemonSet 为 `k3s_config/sim/fluentbit.yaml`。`/rosout` 采集器
（`collect/`）已退役（issue #88）：每节点身份经由
`ROSCONSOLE_FORMAT ${node}` 与规范信封走 stdout 通道。

## 11. 站点摄入（l4-visualizer）

> l4-visualizer 服务器拥有自己的 zenoh 会话，订阅其租用的 stack，并通过
> 一条流水线规范化记录。

摄入绑定（v3，实现在 l4-visualizer `1ff9f9a`，2026-09-01；已废弃的
`POST /api/logs/ingest` HTTP 路径已删除，v4 2026-09-10）：

- 服务器侧：`l4-agent/src/copaw/station_sidecar/visualizer/server.py`
  （`ZenohLogIngest`）打开自己的 zenoh 会话（client 模式，配置库
  路由器）并订阅 `lx/<stack-id>/logs` 及
  `lx/<stack-id>/agent_log`（2026-09-15）；一旦桥上报绑定的 stack
  （`agent-station-channels.spec.md` §1.1），就把每条记录送入**同一条**
  §11.1 流水线。agent_log 信封解包为其规范 `record`；稠密通道的 seq
  连续性按流检查（间隙以 `agent_log_seq_gap` 警告条目浮现），
  `(stack, node, seq)` 去重使同时到达两个通道的记录只保留一次
  （§4/§5）。
- 无人机侧：`lx-log-relay` 仓库的 `relay.py` 接收 fluent-bit 的 `tcp`
  输出（json_lines），并把每条记录原样发布到 `lx/<stack-id>/logs`。

### 11.1 摄入规范化流水线（每条 fluent-bit 记录）

> 四个有序步骤：剥离转义、解析 rosconsole 前缀、解析信封、回退。

四个有序步骤：

1. **转义剥离** —— 从原始消息中移除 ANSI SGR（`ESC[...m`）与 OSC 标题
   （`ESC]...BEL`）序列。
2. **ROSCONSOLE 前缀解析** —— 形如 `[/node] [LEVEL] [time]: msg` 的行把
   `node` + `level` 提升为字段；消息只保留 `msg`。剥离后归为空的行被
   DROPPED（丢弃）。
3. **slog 解析** —— 规范信封 JSON 行（§2）映射为
   event/node/level/ts/fields；`seq` 提升进条目以供跨通道去重。
4. **回退级别** —— 扫描 `[INFO]` 式标记；默认 `info`。

携带 `(node, seq)` 的记录是可能**同时**到达 stdout 与 agent_log 两个通道
的规范信封记录 —— 每条只摄入一次。

| 字段 | 类型 | 含义 | 示例 |
|-------|------|---------|---------|
| `ts` | string | RFC3339（保留 CRI 时间） | `2026-08-18T17:43:14.861+08:00` |
| `level` | string | `debug\|info\|warning\|error\|fatal` | `warning` |
| `service` | string | 所属部署（`_deployment_of(pod)`） | `l0-mavros-arm64` |
| `source` | string | 容器名 | `mavros` |
| `node` | string | ROS 节点 —— 前缀解析或 slog 字段 | `mavros` |
| `seq` | int | 规范信封关联 id（仅 slog 行） | `17` |
| `message` | string | 单行，<= 2000 字符 | `Shutdown request received.` |

`service` 由 k3s pod 名推导（剥离两个 hash 后缀）—— 来自 kubernetes
filter 的真值；已退役采集器的手工 `NODE_SERVICE_HINTS` 前缀表绝不能
回来。

### 11.2 可视化交接

> 渲染归属仍属 l4-visualizer 产品 spec。

规范化记录由 l4-visualizer 的 Logs 标签页（rerun TextLog）渲染。实体
映射、gRPC/HTTP 端口与控制标签页规则归
`specs/implemented/inner/l4-visualizer.spec.md` 所有。

### 11.3 单一职责

> 只有 l4-visualizer 渲染日志；第二个呈现面即缺陷。

日志可视化**只**由 l4-visualizer 负责（specs/README.md 规则 6）。
l4-agent copaw 控制台不渲染日志；重复可视化即缺陷（issue #16 跟踪）。

## 12. 场景导航任务聚合

> 完整导航过程记录与聚合契约：一次 scene-graph 导航从触发到结束的
> 全过程记录，供现场回归、故障回溯和验收取证。

### 12.0 记录范围（一次 scene-nav 任务）

> 一次 scene-nav 会话 = 同一 frame_id 关联的一次 navigation.scene_graph_nav 全过程。

本 spec 的 scene-nav 会话是日志聚合单位，采用
`specs/implemented/domain-lang.spec.md` 的 log record / result 区分。
`terminal=auto_hover` 只关闭聚合窗口，不表示飞行成功；执行结果仍由
`l3-dispatcher-mission-action.spec.md` 和 `flight-actions.spec.md` 定义。

一次 scene-nav 日志会话 = 可由同一 `frame_id` 关联的执行记录：一次
`navigation.scene_graph_nav`（label 解析 + object-id nav）。map_search /
smart_nav 两步流已退休（2026-09-09）。

跨调用只有显式关联证据才能合并，不能从任务数字推断为同一会话。

| 阶段 | 生产者 | 事件（slog event / 行） | 关键字段 |
|------|--------|------------------------|----------|
| **触发** | dispatcher (`dispatcher_node.py`) | `SCENE_NAV` 日志行（label resolve / object_id nav） | `frame_id`, prompt |
| **导航开始** | mission_executive | `object_id_nav_start` | `target_obj_id`, `source_task_id`, `task_session_id` |
| **路径规划** | mission_executive | `object_path_request` / `object_path_result` / `object_path_topo_sequence` | `target_obj_id`, `aim_pos`, `aim_yaw`, `path_size` |
| **导航执行** | mission_executive | `object_nav_goal` / `object_topo_waypoint_command` / `waypoint_progress_received` / `waypoint_progress_advance` / `object_topo_progress` | `odom_pos`, `local_aim`, `aim_pos`, `path_index` |
| **异常/重试** | mission_executive | `object_id_nav_replan_needed` / `topo_block_fallback` / `object_topo_final_approach` / `object_force_replan_unreachable_local_goal` | `reason`, `target_obj_id` |
| **完成** | mission_executive | `object_id_nav_finish`（`finish_source` = ego_exec_finish / arrival_dwell） | `odom_pos`, `dis_2_aim_2d`, `dis_yaw` |
| **结束信号** | px4ctrl | `[px4ctrl] State: AUTO_HOVER(2), ...` | `fsm_state` |

### 12.1 事件源与标记规则（fluent-bit）

> fluent-bit 只做单行识别与打标，聚合归接收端。

fluent-bit 是**单行识别器**，不做跨行聚合。规则：对下列匹配行**追加字段**并透传：

| 源 pod | 匹配模式 | 追加字段 |
|--------|----------|----------|
| `l3-dispatcher-arm64` | 行含 `SCENE_NAV` | `scene_nav=1`, `role=trigger` |
| `l3-mission-arm64` | slog event ∈ 表 12.0 的 mission 事件集 | `scene_nav=1`, `role=mission` |
| `l2-px4ctrl` | 行匹配 `State: (AUTO_HOVER\|AUTO_TAKEOFF\|AUTO_LAND)\(` | `scene_nav=1`, `role=fsm` |

实现：fluent-bit `lua` filter（Modify/rewrite 不便于正则匹配）。未命中
原样透传（零影响）。

**明确边界**：

- fluent-bit **不聚合**、不缓存、不写文件——聚合是接收端的职责（§12.3）。
- 只有 `scene_nav=1` 的行参与聚合；其余行走现有链路不受影响。
- px4ctrl 的 `AUTO_HOVER` 行来自其 stdout，经 fluent-bit 已带 k3s pod
  标识，可直接匹配。

### 12.2 会话关联 key

> frame_id 优先，task_session_id 次之，时间窗兜底。

聚合 key 定义（按优先级）：

1. **`frame_id`**（执行记录中的关联字段，包括 TaskAction.frame_id）——
   关联 dispatcher/mission 记录。
2. **`task_session_id`**（mission `active_instruction_session_id_`）——
   mission 侧唯一，日志已带；当 frame_id 不可得时用它。
3. **时序窗口**——同一 pod、`object_id_nav_start` 之后、下一次
   `object_id_nav_start` 之前的 mission 行归为一次导航（兜底）。

实际关联以 frame_id 为主；aggregator 须容忍 frame_id 缺失，此时用
task_session_id + 时间窗合并。

### 12.3 聚合与落盘（owner-station l4-visualizer server）

> 站端按会话聚合 scene_nav 行，四条件之一关闭即落盘 JSON。

聚合器位于 l4-visualizer server（`add_ingest` 入口），对 `scene_nav=1` 的行：

1. 提取会话 key（§12.2）。
2. 维护内存会话表：`key -> {frame_id, task_session_id, events[], state, start_ts, end_ts}`。
3. 按事件类型更新会话状态：
   - `object_id_nav_start` → 会话开始（可覆盖旧会话）。
   - `SCENE_NAV`（trigger）→ 记录 prompt/task_id/frame_id。
   - `object_id_nav_finish` → 导航完成（记录 odom/距离）。
   - px4ctrl `AUTO_HOVER` → **会话结束标记** `terminal=auto_hover`。
4. **会话关闭条件**（任一触发即落盘）：
   - px4ctrl `AUTO_HOVER` 行到达；
   - `object_id_nav_finish` 后 30 s 无新 scene-nav 行；
   - 新 `object_id_nav_start`（旧会话被覆盖）；
   - 会话超时 10 min（force close）。
5. **落盘**：`<l4-visualizer>/logs/scene-nav/<frame_id或session>-<start_ts>.json`：

```json
{
  "frame_id": "copaw/flight_xxx/step_yyy",
  "task_session_id": 0,
  "start_ts": "2026-08-20T03:18:55.000Z",
  "end_ts": "2026-08-20T03:19:05.000Z",
  "terminal": "auto_hover",
  "target": {"object_id": 2, "label": "front_end", "aim_pos": [], "aim_yaw": 0.0},
  "events": [
    {"ts": "...", "node": "dispatcher_node", "event": "SCENE_NAV", "detail": "...", "prompt": "智能导航到front_end"},
    {"ts": "...", "node": "drone_0_mission_executive", "event": "object_id_nav_finish", "dis_2_aim_2d": 0.9}
  ],
  "outcome": {
    "reached_target": false,
    "reached_radius_m": 0.9,
    "yaw_aligned": false,
    "early_terminated_by": "object_force_replan_unreachable_local_goal"
  }
}
```

### 12.4 outcome 判定（验收证据）

> outcome 由事件推导，是回归证据而非验收决定。

`outcome` 由 aggregator 依据事件推导，作为回归审查证据；它不替代
权威执行结果或用户验收决定：

| 字段 | 来源 |
|------|------|
| `reached_target` | 会话内最近的 `object_id_nav_finish` 或 `object_topo_progress` 的 `dis_2_aim_2d` < `fsm/thresh_replan1`(0.5 m) |
| `reached_radius_m` | 会话内最小 `dis_2_aim_2d` |
| `yaw_aligned` | 会话内最小 `dis_yaw`（度）< 5° |
| `early_terminated_by` | 终止类事件：`object_force_replan_unreachable_local_goal` / `topo_block_exhausted` / `object_id_nav_replan_exhausted`；无则 `null` |
| `terminal` | px4ctrl 最终 fsm_state（`auto_hover` / `auto_takeoff` / 超时 `timeout`） |

### 12.5 实现边界与委托

> 契约在 diff-dockers，标记在 auto_deployer，聚合在 l4-visualizer。

| 侧 | 内容 | 归属 |
|----|------|------|
| 本 spec | 契约 | station-host（diff-dockers） |
| `auto_deployer` fluentbit.yaml lua filter | scene-nav 行标记 | station-host（drone_projects/auto_deployer） |
| l4-visualizer server 聚合 + 落盘 | 会话聚合 + JSON 落盘 | l4-visualizer（station-host owner） |

## 13. 现场诊断规则（长期经验）

> 现场经验：stdout 无输出意味着卡片静默，pod 元数据需要 hostNetwork 下
> 可达的 API，诊断自底向上并以真实时间戳推进。

- **静默卡片 = stdout 源头无输出，而非采集器 bug。** fluent-bit 只 tail
  容器 stdout：健康但静默的节点仍会显示死卡片。因此每个 lx-real 部署都在
  bash 心跳守护下运行 `roslaunch --screen`，每 10 s 打印
  `[<layer>] heartbeat`，使 pod 存活期间通道永不干涸。要确认源头干涸，可在
  相隔 3 s 的两次测量中查看 pod stdout 文件大小
  （`/var/log/pods/<ns>_<pod>_<uid>/<container>/<N>.log`）；容器重启后该文件
  是 `N.log`（2/3/…），**不是** `0.log`，而对 `/var/log/containers/` 符号
  链接做 `stat` 得到的是符号链接 inode，不是数据。在信封时代，每个 l3 节点
  还以周期性事件保持自身可见（dispatcher `dispatcher_state`，mission
  `battery_voltage`，planner `ego_cloud_filter`）。
- **fluent-bit 的 pod 元数据需要 hostNetwork pod 可达的 API。**
  `hostNetwork` 的 fluent-bit 往往无法解析 `kubernetes.default.svc`
  （`getaddrinfo err=-3`），于是每条记录都不带 pod/container 字段，所有卡片
  落到 `unknown`。修复：`Kube_URL https://127.0.0.1:6443` +
  `Kube_CA_File`/`Kube_Token_File` 指向投影的 service-account token。
  验证：fluent-bit 日志出现 `local POD info OK`；hostNetwork 的
  `could not get meta for POD <hostname>` 警告无害。
- **以真实时间戳自底向上诊断。** 中继记录 `fluent-bit connected` 并把每条
  已接收行转发到 `lx/<stack-id>/logs`；探测该键以证明投递；rerun Logs 标签页
  保留时间线，因此在断定陈旧前先核对条目 `ts`；`kubectl exec` 的输出永不
  进入 `/var/log/containers`；`api/ctl/status` 的 `bound:true` 意味着连接令牌
  有效，而非记录在流动 —— 先对比两次快照再下结论。

## 14. 验证

> 按平面的门禁：契约测试、主机编译门禁、站点侧信封测试、流水线探针。

### 14.1 生产者（信封、级别、缓冲）

> 契约测试、编译门禁与缓冲延迟检查。

- `uv run pytest`（l3 树）通过；mission-contract 字节 diff 通过
  （提取器范围：排除 `bridge_client.py` —— 仅有 py 的 RPC 适配器，
  无 C++ 对应文件）。
- `drone_projects/auto_deployer/compile/station-host-compile-l3.sh` 通过
  （面向每个已迁移 TU 的开发侧 C++ 编译门禁）。
- 缓冲：`kubectl rollout restart` 后，INFO 行在约 1 s 内出现在
  `kubectl logs -f` 中；`which stdbuf` → `/usr/bin/stdbuf`。
- 默认门禁隐藏 debug 遥测：`kubectl logs --tail=200 | grep -c
  'nav_tick'` → 0；使用 `telemetry/level:=debug` 后事件可见。

### 14.2 流水线（采集器、中继、节点身份）

> 面向采集器、中继与节点身份的可直接复制的 shell 检查。

```bash
# fluent-bit 侧：输出指向 loopback 中继（v3）
sudo -n k3s kubectl get cm fluent-bit-config -n lx-real -o jsonpath='{.data.fluent-bit\.conf}' | grep -E 'Parser|Host|Port'
# 审计：任何采集器配置中都无汇点地址
sudo -n k3s kubectl get cm fluent-bit-config -n lx-real -o jsonpath='{.data.fluent-bit\.conf}' | grep -c '192\.168'   # 必须为 0
# 中继侧：relay 容器存活
sudo -n k3s kubectl logs -n lx-real -l app=fluent-bit -c lx-log-relay --tail=5
# stdout 行携带节点身份（B 层前缀 / 信封 JSON）
sudo -n k3s kubectl logs -n lx-real deploy/l3-mission-arm64 --tail=5 | grep -o '"node":"[a-z_0-9]*"' | head -2
```

### 14.3 站点摄入

> 站点侧信封测试与实况抽查。

- l4 `tests/test_visualizer_log_envelope.py` 通过：seq 提升、跨通道去重、
  agent_log 间隙条目、`_raw` 路由。
- rollout 后设备抽查：每个 l3 pod 的结构化行都能解析为带 `node` + `seq` +
  规范 `level` 的 JSON；stdout 上不再残留 `warn`/`trace` 字符串；
  fluent-bit lua 的 scene-nav 标记仍命中。
- 站点存活：`curl -fsS http://127.0.0.1:8391/api/ctl/status` 报告绑定的
  stack；一次日志探针会推进 rerun 时间线。