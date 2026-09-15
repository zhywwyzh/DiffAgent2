# dispatcher 其余 ROS 面适配 方案（S4 子方案）

> 摘要：本方案是总纲 `design-dispatcher-architecture-stabilization.md` 的 **S4 期执行版**，
> 范围只做「其余 ROS 面适配」：把**装配面与配置面**的 ROS 依赖隔离到 `ros_adapter/*_ros.py`
> （S4a，零行为），并对**感知层**（`perception/base_policy.py`、`pointcloud_accumulator.py`）
> 先做拆分**评估**（S4b，先评估后执行）。
> 依据：`specs/implemented/inner/l3-ros-adapter-boundary.spec.md`（R1–R6/S1–S4/X1–X4/G7–G9）、
> `l3-core-boundary.spec.md`（B1/B3）、`l3-execution-seam.spec.md`（§3、§6/G12）。
> `engine.py` 与 `core/` 的 ROS 面**已由 S3 方案负责**（`ros_adapter/core_channels_ros.py`），
> 本方案**不重复认领**，仅在接口衔接处引用。姊妹篇：总纲、S2 `design-dispatcher-package-topology.md`、
> S3 `design-dispatcher-engine-relocate-non-core.md`、S5 `design-dispatcher-taskid-retirement-full.md`。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-12 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/`（代码）；本文件为文档交付物 |
| 状态 | done（2026-09-12 S4a 执行完毕；S4b 降级 B 为后续轮次，见 §11 附录） |
| 关联文档 | 总纲 `design-dispatcher-architecture-stabilization.md`（§4.1/§4.2/§4.3/§4.4/§4.5/§4.7）；模板 `_TEMPLATE.md` |
| 期次归属 | 总纲 §4.7 的 **S4**；前置 S3、S1 |
| 路径约定 | 全文用相对路径；不写主机绝对路径与个人标识 |
| 证据纪律 | 所有行号本次实测（2026-09-12，基线为 S2/S3 **执行前**的现状树）；无法核实项显式标注「未核实」 |

## 1. 背景与动机

总纲 §2.A 与 §5 判定：当前 Python 侧的 ROS 收发**未隔离**——领域/核心/配置/装配/感知文件直接
`import rospy`、`from *_msgs import …`、构造 `Publisher/Subscriber/Timer/ServiceProxy`，且 Python 侧
**零 `*_ros.py` 适配文件**，违反 `l3-ros-adapter-boundary` R1/R2/R4（门禁 G7/G8）。

S3 一次性把 **engine 与 core 四类通道**的 ROS 实现落到 `ros_adapter/core_channels_ros.py`。
**剩下的 ROS 面**分两类，正是本期范围：

1. **装配面与配置面**（S4a，零行为）：`utils/config.py`（参数应用面）、`utils/control_plane.py`
   （关停/日志）、`utils/zenoh_rpc.py`（ROS 反馈面订阅与 `ServiceProxy`）、`dispatcher_node.py`
   （组合根：`init_node`/`get_param`/`spin`）。它们让 `utils/`（支撑平面）无法满足总纲 **A1/A2**。
2. **感知层**（S4b，先评估）：`perception/base_policy.py`（3077 行）与
   `perception/pointcloud_accumulator.py` 的收发、解码与消息类型触点极多且与几何/状态推进交织，
   按总纲 §9 风险对策**先评估后执行**。

## 2. 现状事实（问题清单）

> 路径均相对本仓库根；行号为本次实测。`PKG = l3-dispatcher-planner/ros_packages/dispatcher/`。
> 每条为「文件 + 实测行号 + 现象」。

### 2.1 配置面（`config.py`）

- [ ] `PKG/dispatcher/config.py#L15` — `import rospy`（模块级）。
- [ ] `PKG/dispatcher/config.py#L41` — `load_yaml` 内 `rospy.logwarn(f"config_path not found: {path}")`
      （纯 YAML 装载函数携带 ROS 日志）。
- [ ] `PKG/dispatcher/config.py#L61-L64` — `set_ros_params` 内 `rospy.set_param(f"~{key}", value)`（唯一 ROS 参数写入面）。
- [ ] `PKG/dispatcher/config.py#L85-L89`、`#L92-L97` — `flatten_leaf_params` 内两处 `rospy.logwarn`（重复叶子键告警）。
- [ ] `PKG/dispatcher/config.py#L150` — `apply_config` 内 `rospy.logwarn(f"Unknown {section_name} key skipped: {key}")`。
- [ ] 实测：`config.py` 中 `rospy` 命中 **7 行** = 1 import（L15）+ 1 处 `set_param` 调用（L64）+ 4 处 `logwarn` 调用（L41、L85、L93、L150）+ 1 处 docstring 提及（L72，非调用，不迁）。
      消费方唯一：`PKG/dispatcher/engine.py#L27-L38` 导入、`#L1022`/`#L1032`/`#L1035`/`#L1041` 调用
      （`create_dispatcher_engine`，S3 将移入 `dispatcher_node.py`）。

### 2.2 装配面（`tools/control_plane.py`，S2 后为 `utils/control_plane.py`）

- [ ] `PKG/dispatcher/tools/control_plane.py#L45`、`#L75` — 函数内懒 `import rospy`。
- [ ] `PKG/dispatcher/tools/control_plane.py#L47`、`#L77` — `while not rospy.is_shutdown()`（关停探测）。
- [ ] `PKG/dispatcher/tools/control_plane.py#L60-L65` — `rospy.logerr("[tool_runtime] %s %s failed: %s", command.kind, command.call.name, exc)`。
- [ ] `PKG/dispatcher/tools/control_plane.py#L83-L85` — `rospy.logerr("[zenoh_rpc] middleware start failed (%s); retry in 5s", exc)`。
- [ ] 实测：`control_plane.py` 中 `rospy` 命中 **6 行**（2 import + 2 is_shutdown + 2 logerr）。

### 2.3 传输面（`zenoh_rpc.py`，S2 后为 `utils/zenoh_rpc.py`）

- [ ] `PKG/dispatcher/zenoh_rpc.py#L33` — `STACK_RESET_SERVICE = "/agent/stack_reset"`（服务名常量，与 ROS 服务面绑定）。
- [ ] `PKG/dispatcher/zenoh_rpc.py#L180` — `start()` 内调用 `self._start_ros_subscriptions()`（启动序列位点）。
- [ ] `PKG/dispatcher/zenoh_rpc.py#L305-L320` — `_start_ros_subscriptions`：`import rospy`、`from quadrotor_msgs.msg import InstructionResMsg`、
      `from sensor_msgs.msg import CompressedImage`、`from std_msgs.msg import String`，并构造
      `rospy.Subscriber("/Instruct_res", InstructionResMsg, self._on_instruct_res)`（L312）、
      `rospy.Subscriber(os.environ.get("LX_GRASP_RESULT_IMAGE_TOPIC", "/agent/grasp_result_image"), CompressedImage, self._on_grasp_result_image, queue_size=1, tcp_nodelay=True)`（L313-L319）、
      `rospy.Subscriber("/agent_scene_objects", String, self._on_scene_objects_msg)`（L320）——**3 个 Subscriber**。
- [ ] `PKG/dispatcher/zenoh_rpc.py#L426-L452` — `_on_sim_reset` 内懒 `import rospy`、`from std_srvs.srv import Trigger`，
      构造 `rospy.ServiceProxy(STACK_RESET_SERVICE, Trigger)`（L433）与 `rospy.wait_for_service(STACK_RESET_SERVICE, timeout=5.0)`（L434）。
- [ ] `PKG/dispatcher/zenoh_rpc.py#L533-L538`、`#L582-L591`、`#L593-L603` — 三个 ROS 回调改写 middleware 状态
      （`runtime.emit`、`_grasp_images`、`_scene_objects`），即适配层回调直接推进/写入 middleware 状态。
- [ ] 实测：`zenoh_rpc.py` 的 ROS 触点 = 懒 import 2 处 + `*_msgs`/`std_srvs` import 4 处 + Subscriber 3 个 + ServiceProxy 1 个 + `wait_for_service` 1 处。

### 2.4 组合根（`dispatcher_node.py`）

- [ ] `PKG/dispatcher_node.py#L16` — `import rospy`（模块级）。
- [ ] `PKG/dispatcher_node.py#L18` — `from dispatcher.tools.control_plane import ToolControlPlane`（S2 后为 `dispatcher.utils.control_plane`）。
- [ ] `PKG/dispatcher_node.py#L28` — `rospy.init_node("uav_policy_node", anonymous=True)`。
- [ ] `PKG/dispatcher_node.py#L30` — `config_path = rospy.get_param("~config_path", "")`。
- [ ] `PKG/dispatcher_node.py#L41` — `rospy.spin()`；`#L19-L22` 导入 `create_dispatcher_engine`/`start_dispatcher_workers`（S3 将移入本文件）。
- [ ] 实测：`dispatcher_node.py` 中 `rospy` 命中 **4 行**（1 import + init_node + get_param + spin）。

### 2.5 感知层（S4b 评估对象，实测触点）

> 详细计数见 §7.2。以下为关键结构耦合证据。

- [ ] `PKG/dispatcher/perception/base_policy.py#L18-L33` — 模块级 ROS 依赖：`import rospy`（L18）、`from message_filters import Subscriber as MFSubscriber`（L23）、
      `sensor_msgs`（L24、L28、L29）、`nav_msgs`（L25）、`geometry_msgs`（L26）、`visualization_msgs`（L30）、`import cv_bridge`（L33）。
- [ ] `PKG/dispatcher/perception/base_policy.py#L41-L53` — 领域数据结构 `Frame` 直接持有 ROS 消息类型字段
      `cloud_msg: Optional[PointCloud2]`（L47）——R2/G8 的结构性违反，不是单点收发。
- [ ] `PKG/dispatcher/perception/base_policy.py#L88-L146` — `OdometryBuffer` 存原始 `Odometry` 消息并做插值，
      `get_interpolated_odom(self, target_stamp: rospy.Time)`（L108）、`res.header.stamp = rospy.Time.from_sec(...)`（L146）。
- [ ] `PKG/dispatcher/perception/base_policy.py#L244-L618` — `BasePolicyNode.__init__` 集中参数装载（`rospy.get_param` ×49 行）、
      订阅/发布/定时器构造、`cv_bridge.CvBridge()`（L327）。
- [ ] `PKG/dispatcher/perception/base_policy.py#L1144-L1155` — `_track_input_health` 以 `isinstance(self.odom_sub, MFSubscriber)` 判定订阅类型
      （领域层感知 `message_filters` 具体类型）。
- [ ] `PKG/dispatcher/perception/base_policy.py#L2912-L3017` — `_build_pointcloud_from_frame` 在几何换算内部使用
      `rospy.Header`、`rospy.Time.from_sec`、`pc2.create_cloud_xyz32`（几何与 ROS 消息构造交织）。
- [ ] `PKG/dispatcher/perception/pointcloud_accumulator.py#L12-L15` — `import rospy`、`sensor_msgs`、`std_msgs`、`sensor_msgs.point_cloud2`。
- [ ] `PKG/dispatcher/perception/pointcloud_accumulator.py#L122-L138` — `rospy.Publisher`（L122）、`rospy.Subscriber`（L125）、
      `rospy.Timer(rospy.Duration(...))`（L136）、`rospy.loginfo`（L138）。

### 2.6 现状不一致（登记，不属本期修复对象）

- [ ] `l3-dispatcher-planner/tests/tool-registry/test_connection_lease.py#L438-L454` 断言 `queryable_suffixes()` 含
      `connection/acquire` 等，而 `PKG/dispatcher/zenoh_rpc.py#L111-L122` 现值仅返回
      `("sim/reset","grasp_result/*","health","agent_log/snapshot")`（任务面已移 `RpcPlane`）。该用例当前期望与实现不匹配——**未核实**其运行态（本环境未执行 pytest）。与 S4 无关，仅登记。
- [ ] `PKG/dispatcher/engine.py#L186` 等 `task_id` 残留 —— 属 S5；`engine.py`/`core/` ROS 面 —— 属 S3，本方案不认领。

## 3. 目标与约束

- **目标**：
  1. S4a（零行为）把装配面与配置面的 ROS 依赖隔离到 `ros_adapter/{params_ros,clock_ros}.py`
     （及必要的适配落点），使 `utils/`、`dispatcher_node.py` 满足 **A2**（零 `import rospy` / 零 ROS 消息类型）；
  2. 逐条对齐 `l3-ros-adapter-boundary` R1/R2/R4/R5/R6 与门禁 G7/G8/G9；
  3. 对感知层给出可判定的拆分**评估报告**与**门槛判据**（S4b），不满足门槛即降级并登记总纲 §4.7。
- **Non-Goals**：
  - 不改 FSM 语义、不改对外协议（topic/param/消息字段名、zenoh queryable/presence token、slog 事件名与键集）；
  - 不认领 `engine.py` / `core/` 的 ROS 面（S3 已覆盖）；不认领 task_id 退役（S5）；
  - 不实现技能族、不动感知/规划算法内部逻辑；
  - 不新增转接器、不留 re-export 转发桩、不留注释桩、不为「以后可能用」预造端口。
- **硬边界**：
  - **禁止转接器**：新旧接口不统一时重新设计接口，不新设只做转换的层（总纲 §3）。
  - **过期必删（no legacy shim）**：领域文件内的 `import rospy` / `*_msgs` / `Publisher/Subscriber/ServiceProxy` 构造**直接删除**，不留别名、不留注释。
  - **契约优先、门禁绿**：以 `l3-ros-adapter-boundary` R1–R6 与 S1–S4 为准。
  - **不投机设计**：无消费者的端口不预造（见 §7.1「本期不隔离项」对 clock 端口的登记）。
  - **spec 改动需显式放行**：本方案不改 `specs/`；若 S4b 需修订 R2 判定边界，须先走 S1 放行流程。

## 4. 方案决策

### 4.1 目标目录树（对齐总纲 §4.1，本方案只落地其中 S4 行）

```
PKG/dispatcher/
  dispatcher_node.py                    # 组合根：吸收 create_dispatcher_engine/start_dispatcher_workers（S3），
                                        #   本方案把其 rospy bootstrap 端口化（S4a）
  dispatcher/
    ros_adapter/                 ★ S3/S4 # 唯一允许 rospy / ROS 消息类型处（R1）
      __init__.py
      core_channels_ros.py        ★ S3  # 四类 core 通道（急停 / if_handle_yaw / 命令内容监控 / 任务相位）——S3 落，本方案不认领
      params_ros.py               ★ S4a # ROS 私有参数装载与读取（config 的 ROS 面）
      clock_ros.py                ★ S4a # 装配面最小 ROS 端口：关停探测 / 日志 / 进程生命周期
      feedback_ros.py             ★ S4a # ★本节请求总纲 §4.1 追加登记：zenoh middleware 的 ROS 反馈面
      perception_ros.py           ★ S4b # 感知层收发实现（评估后按门槛执行/降级）
    utils/                        ★ S2  # 支撑平面；本方案令其零 rospy
      config.py  control_plane.py  zenoh_rpc.py  …   # 全部零 rospy
```

> **树形变更登记**：总纲 §4.1 的 `ros_adapter/` 只列出 `core_channels_ros/params_ros/clock_ros/perception_ros`。
> 本方案发现 `utils/zenoh_rpc.py` 的 ROS 反馈面（3 个 Subscriber + `ServiceProxy`）**无归属文件**，
> 请求在总纲 §4.1 追加 `ros_adapter/feedback_ros.py`（命名符合 §4.3 `*_ros.py`）。**在该追加被确认前，
> S4a 的 P3 不执行**；其余 P0–P2、P4 不受影响。备选（不推荐）：把反馈面塞进
> `core_channels_ros.py`——会污染 core 四通道语义（B3 白名单），否决。

### 4.2 平面定义与依赖方向（复述总纲 §4.2，验收据此 grep）

| 单元 | 本方案相关约束 |
|---|---|
| `ros_adapter/` | 允许依赖 `core/`（端口 Protocol）、`utils/`、`perception/`、`rospy`/ROS 消息；禁止 `tools/`、`engine` |
| `utils/` | 允许 `utils/` 内部、`tools/`；**禁止 `ros_adapter/`**（不得 import 适配层）；零 `rospy` |
| `perception/` | 禁止 `ros_adapter/`；零 `rospy`（S4b 后） |
| `dispatcher_node.py` | 允许 `engine`、`utils/control_plane`、`ros_adapter/`；零 `rospy`（A2） |

- **依赖倒置**：`utils/` 侧消费者（`config.py`/`control_plane.py`/`zenoh_rpc.py`）**只持有端口引用**，
  由组合根 `dispatcher_node.py` 注入适配层实现；`utils/` 不 import `ros_adapter/`。
- ROS 面方向：**消费方声明/持有端口，`ros_adapter/` 实现端口**。

### 4.3 命名表（对齐总纲 §4.3，本方案新增项）

| 类型 | 规范 | 本方案落点 |
|---|---|---|
| 适配文件 | `*_ros.py`，仅此命名可含 `rospy` 与 ROS 消息类型 | `params_ros.py`、`clock_ros.py`、`feedback_ros.py` |
| 端口实现类 | 大驼峰、`Ros<职责>` | `RosParams`、`RosLog`、`RosShutdown`、`RosNode`、`FeedbackPlane` |
| 端口消费方入参 | 关键字参数、语义名 | `log=`、`shutdown=`、`reset_stack=` |
| middleware 状态写入缝 | 沿用语义动词、不再 `_on_*`（回调迁出） | `record_instruct_res`、`record_grasp_image`、`record_scene_objects` |

### 4.4 端口集合与签名草案

> 全部端口为**鸭子类型**（不新造 `Protocol` 文件，避免在 `utils/` 增加总纲 §4.1 未列模块）；
> `core/ports.py`（S3）已承载 core 四通道 Protocol，本方案不并入。

`ros_adapter/params_ros.py`（config 的 ROS 面 + 组合根私有参数读取）：

```python
def set_ros_params(params: dict) -> None
    # 逐条 rospy.set_param(f"~{key}", value)（键名与顺序逐字不变）

def get_private_param(name: str, default=None)
    # rospy.get_param(f"~{name}", default)；供 dispatcher_node 读 "~config_path"
```

`ros_adapter/clock_ros.py`（装配面最小端口，`RosClock` 本期不建，见 §7.1）：

```python
class RosShutdown:  # 关停探测端口
    def is_shutdown(self) -> bool        # rospy.is_shutdown()

class RosLog:       # 日志端口（文本逐字透传）
    def warn(self, msg, *args) -> None   # rospy.logwarn(msg, *args)
    def info(self, msg, *args) -> None   # rospy.loginfo(msg, *args)
    def err(self, msg, *args) -> None    # rospy.logerr(msg, *args)

class RosNode:      # 进程生命周期端口（组合根专用）
    def init_node(self, name: str, anonymous: bool) -> None   # rospy.init_node(name, anonymous=anonymous)
    def spin(self) -> None                                    # rospy.spin()
```

`ros_adapter/feedback_ros.py`（zenoh middleware ROS 反馈面；待 §4.1 追加登记确认）：

```python
STACK_RESET_SERVICE = "/agent/stack_reset"   # 自 utils/zenoh_rpc.py#L33 迁入（服务名常量归适配层）

class FeedbackPlane:
    def __init__(self, middleware) -> None: ...
    def attach(self) -> None:
        # 懒 import rospy 与三个消息包后，按原参数构造 3 个 Subscriber，
        # 回调翻译消息后调用 middleware 的三个状态写入缝

    def reset_stack(self) -> tuple[bool, str]:
        # 懒 import rospy / std_srvs.srv.Trigger；
        # ServiceProxy(STACK_RESET_SERVICE, Trigger) + wait_for_service(..., timeout=5.0)
        # 返回 (resp.success, resp.message)
```

middleware（`utils/zenoh_rpc.py`）新增/改写的最小缝（全部 ROS-free）：

```python
def __init__(self, command_queue, stack_id=None, router=None, lease_ttl_s=None,
             lease_watchdog_interval_s=1.0, *, log=None, shutdown=None) -> None
def bind_feedback(self, feedback) -> None          # 注入 FeedbackPlane（或 None）
def record_instruct_res(self, call_id: str, detail: str) -> None
def record_grasp_image(self, call_id: str, data: bytes) -> None
def record_scene_objects(self, active: str, objects: list) -> None
```

`config.py`（`utils/`）新增可选 `log` 入参（默认 `None` → stdlib `logging.getLogger(...)`；生产由组合根注入 `RosLog`）：

```python
def load_yaml(path, _seen=None, base_dir=None, *, log=None)
def flatten_leaf_params(cfg, *, _path="", log=None)
def merge_pointcloud_mode_params(pointcloud_cfg, *, log=None)
def apply_config(obj, cfg, section_name="config", key_aliases=None, *, log=None)
```

### 4.5 适配文件职责（R5：适配层无决策）

| 文件 | 只做 | 不做 |
|---|---|---|
| `params_ros.py` | 参数读写翻译（`set_param`/`get_param`） | 不装载/合并/校验配置（仍在 `utils/config.py`） |
| `clock_ros.py` | 关停探测透传、日志透传、`init_node`/`spin` 透传 | 不含线程循环/状态推进（循环在 `control_plane.py`） |
| `feedback_ros.py` | 订阅、`ServiceProxy`、消息→纯数据翻译 | 不含编号映射/状态推进（写状态经 middleware 缝） |

### 4.6 旧接口 → 删除

- `config.py` 的 `import rospy`（L15）与 `set_ros_params`（L61-L64）**直接删除**；`set_ros_params` 仅在 `params_ros.py` 重建（调用方改写为 `params_ros.set_ros_params`）。
- `control_plane.py` 的两处懒 `import rospy`（L45/L75）与 `rospy.is_shutdown`/`rospy.logerr` **直接删除**，改注入端口。
- `zenoh_rpc.py` 的 `_start_ros_subscriptions`（L305-L320）与 3 个 `_on_*` 回调体、`_on_sim_reset` 的 `ServiceProxy`/`wait_for_service`（L428-L434）、`STACK_RESET_SERVICE`（L33）**直接删除**，迁 `feedback_ros.py`。
- `dispatcher_node.py` 的 `import rospy`（L16）与 `init_node`/`get_param`/`spin`（L28/L30/L41）**直接删除**，改端口。
- **不保留**任何 re-export 转发模块或同名薄封装桩。

## 5. 迁移映射表

> 动作：move（位置迁移，沿用原名）/ rewrite（端口化改写调用点）/ delete（删除旧定义）。
> 行号为 S2/S3 执行前现状；S2/S3 后文件路径按总纲 §4.1 收敛，**S3 后 `create_dispatcher_engine`
> 的调用点行号以 S3 落盘为准（未核实）**。

| 旧路径/行号 | 新路径/命名 | 动作 | 备注 |
|---|---|---|---|
| `PKG/dispatcher/config.py#L15` `import rospy` | — | delete | utils 零 rospy |
| `PKG/dispatcher/config.py#L61-L64` `set_ros_params` | `PKG/dispatcher/ros_adapter/params_ros.py::set_ros_params` | move | 逐字沿用 `f"~{key}"` |
| `PKG/dispatcher/config.py#L41`、`#L85-L89`、`#L92-L97`、`#L150` `rospy.logwarn` | `utils/config.py` 同名函数内改为 `log.warn(...)`；`log` 由组合根注入 `RosLog` | rewrite | 文本逐字不变，见 §5.1 |
| `PKG/dispatcher/tools/control_plane.py#L45/#L75 import rospy` | — | delete | |
| `PKG/dispatcher/tools/control_plane.py#L47/#L77 rospy.is_shutdown()` | `shutdown.is_shutdown()`（注入 `RosShutdown`） | rewrite | 循环结构不变 |
| `PKG/dispatcher/tools/control_plane.py#L60-L65/#L83-L85 rospy.logerr` | `log.err(...)`（注入 `RosLog`） | rewrite | 文本/参数逐字不变 |
| `PKG/dispatcher/tools/control_plane.py#L17-L23` 构造 | 增加关键字参数 `log=`、`shutdown=`、`feedback_factory=`，透传给 `ZenohTaskMiddleware` | rewrite | 组合根注入 |
| `PKG/dispatcher/zenoh_rpc.py#L33 STACK_RESET_SERVICE` | `ros_adapter/feedback_ros.py::STACK_RESET_SERVICE` | move | 服务名不变 |
| `PKG/dispatcher/zenoh_rpc.py#L180 self._start_ros_subscriptions()` | `if self._feedback is not None: self._feedback.attach()`（同一序列位点） | rewrite | 启动序列不变 |
| `PKG/dispatcher/zenoh_rpc.py#L305-L320 _start_ros_subscriptions` | `ros_adapter/feedback_ros.py::FeedbackPlane.attach` | move+端口化 | 懒 import 语义保留 |
| `PKG/dispatcher/zenoh_rpc.py#L533-L538 _on_instruct_res` 体 | `utils/zenoh_rpc.py::record_instruct_res(call_id, detail)` | rewrite | 回调翻译在适配层 |
| `PKG/dispatcher/zenoh_rpc.py#L582-L591 _on_grasp_result_image` 体 | `utils/zenoh_rpc.py::record_grasp_image(call_id, data)` | rewrite | `_GRASP_IMAGE_MAX` 裁剪逻辑不变 |
| `PKG/dispatcher/zenoh_rpc.py#L593-L603 _on_scene_objects_msg` 体 | `utils/zenoh_rpc.py::record_scene_objects(active, objects)` | rewrite | JSON 解析在适配层 |
| `PKG/dispatcher/zenoh_rpc.py#L428-L434 ServiceProxy/wait_for_service` | `ros_adapter/feedback_ros.py::FeedbackPlane.reset_stack`（注入为 `reset_stack` 端口） | move+端口化 | 超时 5.0s 不变 |
| `PKG/dispatcher_node.py#L16 import rospy` | — | delete | |
| `PKG/dispatcher_node.py#L28 rospy.init_node` | `node.init_node("uav_policy_node", anonymous=True)`（`RosNode`） | rewrite | 名称/匿名不变 |
| `PKG/dispatcher_node.py#L30 rospy.get_param("~config_path","")` | `params_ros.get_private_param("config_path", "")` | rewrite | 默认值不变 |
| `PKG/dispatcher_node.py#L41 rospy.spin()` | `node.spin()`（`RosNode`） | rewrite | |
| `PKG/dispatcher_node.py#L33-L35 / #L38-L44` 组合 | 构造 `RosLog/RosShutdown/RosNode` 并注入 engine/control_plane（`feedback_factory`） | rewrite | 见 §7.1 P4 |
| `PKG/dispatcher/perception/base_policy.py` ROS 触点 | `ros_adapter/perception_ros.py` | 待评估（S4b） | 见 §7.2，**本期不执行** |
| `PKG/dispatcher/perception/pointcloud_accumulator.py#L12-L15/#L122-L138` | `ros_adapter/perception_ros.py` | 待评估（S4b） | 同上 |

### 5.1 行为不变式（S4a，逐字/逐字节）

- **参数名**：`set_ros_params` 写入集合与顺序不变（依 `ros_params` dict 插入序）；键仍为 `~{key}`；`config_path` 仍读 `~config_path` 默认 `""`。
- **topic / service / 消息字段名**：`/Instruct_res`、`LX_GRASP_RESULT_IMAGE_TOPIC`（默认 `/agent/grasp_result_image`，`queue_size=1, tcp_nodelay=True`）、`/agent_scene_objects`、`/agent/stack_reset`（`timeout=5.0`）；字段名 `frame_id`、`instruction_type`、`is_succeed`、`header.stamp`、`header.frame_id`、`data`。
- **日志事件与文本**（逐字）：
  - `"[tool_runtime] %s %s failed: %s"`（`command.kind`, `command.call.name`, `exc`）；
  - `"[zenoh_rpc] middleware start failed (%s); retry in 5s"`（`exc`）；
  - config：`f"config_path not found: {path}"`、`"Duplicate flattened config key %s from %s overrides previous value."`（×2 触发点）、`f"Unknown {section_name} key skipped: {key}"`；
  - 既有 `print` 语句（`[zenoh_rpc] reply ok …` 等）**不改**（非 ROS 日志）。
- **启动序列**（逐字/逐序）：
  1. `dispatcher_node.main()`：`init_node` → `get_private_param("config_path")` → `print("Program starting...")` →
     `create_dispatcher_engine(config_path)` → `ToolControlPlane(engine)` → `control_plane.start()` →
     `start_dispatcher_workers(engine)` → `spin()` → `inference_thread.join()` → `control_plane.close()`。
  2. `ZenohTaskMiddleware.start()` 顺序：zenoh session → agent-log publisher（含 `TypeError` 回退分支）→ 4 个 queryable →
     `runtime.event_sink` → `RpcPlane` → presence token → **反馈面订阅（原 L180 位点）** → lease watchdog → agent-log worker → `print("[zenoh_rpc] rpc plane up: …")`。
- **懒 import 语义**：`quadrotor_msgs`/`sensor_msgs`/`std_msgs`/`std_srvs` 的导入仍**延迟到使用点**（`attach()`/`reset_stack()` 内），不得提升为模块级导入（避免导入期行为变化）。
- **线程/循环结构**：`ToolControlPlane._consume`/`_serve` 的 `timeout=0.2`、`time.sleep(5.0)`、`emit(...)` 载荷不变。

## 6. 删除清单

| 删除项 | 理由 |
|---|---|
| `PKG/dispatcher/config.py` 的 `import rospy` 与 `set_ros_params` 定义 | utils 零 rospy；参数写入迁 `params_ros.py` |
| `PKG/dispatcher/tools/control_plane.py` 的两处懒 `import rospy` 及 `is_shutdown`/`logerr` 调用 | 端口化；utils 零 rospy |
| `PKG/dispatcher/zenoh_rpc.py` 的 `STACK_RESET_SERVICE`、`_start_ros_subscriptions`、三个 `_on_*` 回调体、`_on_sim_reset` 的 `ServiceProxy`/`wait_for_service` | 迁 `feedback_ros.py`；no legacy shim |
| `PKG/dispatcher_node.py` 的 `import rospy` 与 `init_node`/`get_param`/`spin` 调用 | 端口化；A2 |
| 上述迁移点在原文件残留的同名薄封装/注释桩 | 硬边界「过期必删」 |
| （S4b）`PKG/dispatcher/perception/**` 内 `import rospy`/`*_msgs`/`Publisher/Subscriber/Timer` 构造 | 仅当 S4b 过门槛时执行；否则不删 |

## 7. 实施步骤（S4a P0–P4；S4b 评估）

> 前置：S1（契约裁决 §4.5）、S2（`tools→utils` 归位）、S3（`core/` + `core_channels_ros.py`）已落。
> 每步独立可回退：**「移回 + 还原 import」**；执行前对 `PKG/` 打全量快照（主机本地，不入库）。

### S4a — P0：`params_ros.py`（配置面参数写入）

- 范围：新建 `ros_adapter/params_ros.py`（§4.4）；`utils/config.py` 删除 `import rospy` 与 `set_ros_params`；调用点（S3 后位于 `dispatcher_node.py`）改写为 `params_ros.set_ros_params(ros_params)`。
- 行为不变式：写入 param 名/值/顺序、`~config_path` 读取默认值不变（§5.1）。
- 验收：G8 对 `utils/config.py` 零命中 `*_msgs`；`grep "import rospy" utils/config.py` 零命中；param 集合对比见 §8。
- 回退：还原 `config.py`；删除 `params_ros.py`。

### S4a — P1：`clock_ros.py`（关停 + 日志端口）+ `control_plane.py` 端口化

- 范围：新建 `ros_adapter/clock_ros.py` 的 `RosShutdown`/`RosLog`/`RosNode`（**不建 `RosClock`**，见 §7.1）；
  `utils/control_plane.py` 增关键字参数 `log=`/`shutdown=`/`feedback_factory=`，删两处懒 import，`is_shutdown`/`logerr` 改端口；
  端口 `None` 时用本地回退（关停探测恒 `False`；日志走 stdlib `logging`），**生产由组合根注入 ROS 实现**。
- 行为不变式：两段日志文本逐字、循环与线程名不变（§5.1）。
- 验收：`grep "import rospy" utils/control_plane.py` 零命中；L2 冒烟构造并断言线程名/日志文本（§8）。
- 回退：还原 `control_plane.py`；删除/保留空 `clock_ros.py`（若 `feedback_ros.py` 未落则一并删）。

### S4a — P2：`config.py` 日志端口化（`log=` 注入）

- 范围：`utils/config.py` 的 `load_yaml`/`flatten_leaf_params`/`merge_pointcloud_mode_params`/`apply_config` 增关键字 `log=None`；
  4 处 `rospy.logwarn` 改 `log.warn(...)`（默认 `None` → stdlib `logging.getLogger(__name__).warning`）；组合根注入 `RosLog`。
- 行为不变式：文本逐字、触发条件不变；默认路径仅用于非 ROS 调用（生产恒注入）。
- 验收：`grep "rospy" utils/config.py` 零命中（注释除外的判定命令见 §8）；文本对比。
- 回退：还原 `config.py`。

### S4a — P3：`feedback_ros.py`（zenoh ROS 反馈面）——**待 §4.1 追加登记确认后执行**

- 范围：新建 `ros_adapter/feedback_ros.py`（§4.4）；`utils/zenoh_rpc.py` 删 `_start_ros_subscriptions`/三个 `_on_*` 体/`ServiceProxy`/`STACK_RESET_SERVICE`，
  增 `bind_feedback`、`record_instruct_res`、`record_grasp_image`、`record_scene_objects`，`_on_sim_reset` 改调注入的 `reset_stack` 端口；
  `control_plane.py` 的 `feedback_factory` 透传；组合根构造 `FeedbackPlane` 注入。
- 行为不变式：3 个 topic/队列/`tcp_nodelay`、`reset` 服务与超时、`_GRASP_IMAGE_MAX` 裁剪、`emit` 载荷、启动序列位点不变（§5.1）。
- 验收：G7/G8 对 `utils/zenoh_rpc.py` 零命中；L2 冒烟断言订阅参数与 `queryable_suffixes()` 不变（§8）。
- 回退：还原 `zenoh_rpc.py`；删除 `feedback_ros.py`。

### S4a — P4：`dispatcher_node.py`（组合根端口化）

- 范围：删 `import rospy`；`RosNode.init_node/spin`、`params_ros.get_private_param` 替换 L28/L30/L41；构造 `RosLog/RosShutdown` 并注入 engine（日志）与 `control_plane`。
- 行为不变式：节点名 `uav_policy_node`、`anonymous=True`、启动序列与打印不变。
- 验收：A2 对 `dispatcher_node.py` 零命中；L3 冒烟节点起停。
- 回退：还原 `dispatcher_node.py`。

### 7.1 本期不隔离项 + 理由 + 登记

| 不隔离/不建项 | 理由 | 登记 |
|---|---|---|
| `clock_ros` 的**时钟端口**（`now()`/`from_sec()`） | S4a 三个消费方（config/control_plane/zenoh_rpc/dispatcher_node）**无时钟消费者**；预造即「桩」，违反总纲「不投机设计」 | 登记：待 S4b `perception_ros` 或后续消费方出现时补建；总纲 §4.1 `clock_ros` 注释含「时钟」，本方案只落地有消费者的部分 |
| `engine.py` / `core/` 的 ROS 面 | 属 S3（`core_channels_ros.py`） | 登记：不在本方案范围，仅接口衔接引用 |
| `perception/**` 的收发与消息类型 | S4b，先评估 | 登记：见 §7.2；结果回写总纲 §4.7 |
| `zenoh_rpc.py` 内延迟导入的第三方消息包 | **可**隔离（随 P3 迁 `feedback_ros.py`，保留懒导入时机） | 非不隔离项，仅提示「保留懒导入」不变式 |
| `utils/zenoh_rpc.py` 的 `print(...)` 诊断 | 非 ROS 日志（stdlib），不属 G7/G8 | 不迁移 |

### 7.2 S4b — 感知层拆分评估（**先评估，不直接改**）

#### 7.2.1 触点分类与计数（本次实测）

**`PKG/dispatcher/perception/base_policy.py`（3077 行）**

| 触点类别 | 命中数 | 行号 |
|---|---|---|
| `import rospy` | 1 | L18 |
| `message_filters` import | 1 | L23 |
| `*_msgs` import | 6 | L24、L25、L26、L28、L29、L30 |
| `cv_bridge` import | 1 | L33 |
| `rospy.get_param` 族 | 49 | L253,256,262,266,277,285,287,290,330,338,339,342,346,354,356,359,362,365,368,372,375,378,381,384,387,390,392,394,397,413,415,417,418,430,491,494,497,500,504,506,508,510,554,561,570,573,576,965,967 |
| `rospy.logwarn` | 5 | L420,463,627,632,2881 |
| `rospy.loginfo` | 6（含 2 行注释） | L434,458,460,534（+注释 L540,L2859） |
| `rospy.logerr` / `logerr_throttle` | 9（含 2 行注释） | L825,886,901,917,2833,2841 + `logerr_throttle` L659（+注释 L2832,L2840） |
| `rospy.Subscriber` | 5 | L451,517,585,598,612 |
| `MFSubscriber`（message_filters） | 4 | L474,478,487,525 |
| `rospy.Publisher` | 6 | L513,543,548,552,557,564 |
| `rospy.Timer` | 1 | L514 |
| `rospy.Time.from_sec` | 10 | L146,724,811,2887,2920,3011,3022,3048,3061,3074 |
| `rospy.Time.now` | 1 | L2870 |
| `rospy.Time`（类型注解） | 1 | L108 |
| `rospy.Header` | 5 | L2919,3010,3047,3060,3073 |
| `rospy.Duration` | 2 | L514,3040 |
| `ServiceProxy` / `ActionClient` / `ActionServer` | 0 | — |
| `rospy.Rate` | 0 | — |
| `cv_bridge` 用法行 | 7 | L33,327,1007,1008,1065,2847,2868 |
| **`rospy.` 总命中** | **100** | — |

**`PKG/dispatcher/perception/pointcloud_accumulator.py`**

| 触点类别 | 命中数 | 行号 |
|---|---|---|
| `import rospy` | 1 | L12 |
| `*_msgs` import | 3 | L13、L14、L15 |
| `rospy.Publisher` | 1 | L122 |
| `rospy.Subscriber` | 1 | L125 |
| `rospy.Timer` + `rospy.Duration` | 1（同一行） | L136 |
| `rospy.loginfo` | 1 | L138 |
| `cv_bridge` / `ServiceProxy` / `message_filters` | 0 | — |
| **`rospy.` 总命中** | **6** | — |

#### 7.2.2 拆分策略（可迁 vs 交织）

- **可迁（纯 I/O 面）**：`__init__` 内全部 `get_param` 装载（49 处）→ 适配层参数装载；`Subscriber`/`MFSubscriber`/`Publisher`/`Timer` 构造（16 处）；
  `cv_bridge.CvBridge()` 与 `imgmsg_to_cv2`/`compressed_imgmsg_to_cv2`/`cv2_to_imgmsg`/`cv2_to_compressed_imgmsg`（7 处）；
  出站发布函数 `publish_current_state`（L2884）、`_publish_p2w_marker`（L3019）、`_publish_bbox_cloud`（L3043）、`_publish_mask_cloud`（L3053）、`_publish_road_cloud`（L3066）、`_cloud_timer_cb`（L2901）；
  `pointcloud_accumulator.py` 整文件可迁（自包含收发节点但被感知层调用）。
- **与几何/状态推进交织（难迁）**：
  - `Frame.cloud_msg: Optional[PointCloud2]`（L47）——**领域数据结构持有 ROS 消息**；
  - `OdometryBuffer`（L88-L241）存原始 `Odometry` 并插值；`SensorBuffer` 存原始消息；
  - `get_interpolated_odom(target_stamp: rospy.Time)`（L108）、`_build_buffer_frame`（L714）、`build_world_frame_for_image_stamp`（L798）以 `rospy.Time` 为时间基；
  - `_cloud_to_xyz_array` 依赖 `pc2.read_points`；`_build_pointcloud_from_frame`（L2912-L3017）在几何换算内构造 `rospy.Header`+`pc2.create_cloud_xyz32`；
  - `_track_input_health`（L1144-L1155）以 `isinstance(self.odom_sub, MFSubscriber)` 判定订阅类型。
- **回退粒度**：文件级（`base_policy.py` 整体 / `pointcloud_accumulator.py` 整体）；`base_policy.py` 内部无法按函数安全回退（共享 `Frame`/buffer 结构）。
- **单测可行性**：当前 `l3-dispatcher-planner/tests/` **仅** `tool-registry/test_connection_lease.py` 与 `telemetry-bridge/`，**无 ROS-free 感知/几何测试**；
  完整拆分需**先**建无 ROS 的几何/投影基线测试（工作量在 S4b 之前）。
- **风险**：消息对象存储→自有结构的替换会改动几何管线的数据来源；`strict_all`/`odom_interpolation` 同步语义与时间基耦合；3077 行单文件改动的评审与回归成本高。

#### 7.2.3 执行门槛判据（**全部满足**才在 S4b 内执行完整拆分）

1. **测试基线**：已为几何/投影路径建立无 ROS 单测，重构前后输出（waypoint 坐标、投影点云点集）逐点一致；
2. **去消息化可行**：`Frame`/`OdometryBuffer`/`SensorBuffer` 可用自有结构替换 ROS 消息类型，且 `pc2.read_points` 几何等价；
3. **规模可控**：改动可按文件级回退，且单次评审可覆盖；
4. **契约合规**：不新增转接器；`perception_ros.py` 只做收发/翻译/参数装载（R5），不含几何与状态推进；
5. **门禁可达**：S4b 结束时 `perception/` 零 `rospy.`/`*_msgs`（G7/G8），并有 G9 对应实现。

**初判结论（基于本文证据）**：门槛 1、2 **当前不满足**（无感知测试；消息类型深入 `Frame`/buffer/几何），
门槛 3 亦不满足（3077 行单文件）。故 **S4b 完整拆分本期不执行**，建议**降级**：

- **降级 A（不推荐）**：只隔离收发/解码/参数装载进 `perception_ros.py`，几何与消息存储暂留 ——
  因 `_build_pointcloud_from_frame` 等仍在领域内构造 `Header`/用 `pc2`，**G7/G8 仍不可判绿**，收益有限。
- **降级 B（推荐）**：**另立后续轮次**（含「先建无 ROS 感知测试基线 → 去消息化数据结构 → 再拆收发」三步），
  在总纲 §4.7 登记为 S4b 的后续轮次；本期只登记不执行。

## 8. 验收标准

### 8.1 门禁 grep 判定（等价总纲 A1/A2、契约 G7/G8/G9；相对路径）

```bash
D=l3-dispatcher-planner/ros_packages/dispatcher

# A2 适配面门禁：非 *_ros.py / ros_adapter/ 的文件零 import rospy / ROS 消息类型
grep -rnE "import rospy|from rospy|_msgs|std_srvs|cv_bridge|message_filters" "$D" \
  --include=*.py \
  | grep -vE "/ros_adapter/|_ros\.py"        # 期望：零命中

# G7 领域层零 rospy./Publisher(/Subscriber(
grep -rnE "rospy\.|Publisher\(|Subscriber\(|SimpleActionClient" \
  "$D/dispatcher/engine.py" "$D/dispatcher/core" "$D/dispatcher/utils" \
  "$D/dispatcher/perception" "$D/dispatcher_node.py"  # 期望：零命中（S4b 前 perception 除外，见 §7.2）

# G8 领域层 import 闭包不含 *_msgs（静态 import 面）
grep -rnE "from .*_msgs|import .*_msgs" \
  "$D/dispatcher/utils" "$D/dispatcher_node.py"        # 期望：零命中

# A1 依赖方向门禁
grep -rn "dispatcher\.\(utils\|perception\|core\|ros_adapter\)" "$D/dispatcher/tools/"   # 期望：零命中
grep -rn "dispatcher\.engine" "$D/dispatcher/utils" "$D/dispatcher/core" "$D/dispatcher/perception"  # 期望：零命中

# G9 端口有适配层实现（人工/AST 断言：每个端口名在 ros_adapter/ 有 Ros* 实现，且实现体无状态推进分支）
```

> `grep "_msgs"` 会同时命中 `rospy.*_msgs` 与字符串常量；判定时以 `--include=*.py` + 排除 `ros_adapter/` 为准。
> 注释行（如 `config.py` 文档串中提及 `rospy.get_param`）需在 `grep` 后人工剔除（见 §2.1）。

### 8.2 契约/协议字节级对比

- [ ] **param 集合**：对同一 YAML，`set_ros_params` 前后 `rosparam list`/私有参数快照逐键一致（键名、值、类型）。
- [ ] **topic / service**：`rostopic list` 不变；`/Instruct_res`、`/agent_scene_objects`、`/agent/grasp_result_image`、`/agent/stack_reset` 存在性与类型不变。
- [ ] **payload**：`_on_instruct_res` 产出的 `detail` 字符串、`_on_scene_objects_msg` 写入的 `active`/`objects`、`_on_sim_reset` 返回 dict 逐字段一致。
- [ ] **zenoh**：`queryable_suffixes()`、`presence_token_key`、`owner_watch_key` 不变（S4 不涉 task_id）。
- [ ] **日志文本**：§5.1 四类文本逐字；`/rosout` 中由 `RosLog` 产生。

### 8.3 分级冒烟

- **L1（零 ROS 子集，必过）**：`python3 -m py_compile` 对 `PKG/**/*.py` 与 `dispatcher_node.py` 全绿；无 ROS 环境下 `import dispatcher.utils.config` 成功。
- **L2（无 ROS 装配）**：以 fake `log`/`shutdown` 构造 `ToolControlPlane`/`ZenohTaskMiddleware`（不改测试语义），断言线程名、`queryable_suffixes()`、启动序列位点；`pytest l3-dispatcher-planner/tests/tool-registry` 保持既有结果（S4a 不新增失败）。
- **L3（ROS 主机）**：真实节点起停，核对 §8.2；**本环境无法执行，标注未核实**。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| `feedback_ros.py` 不在总纲 §4.1 目标树 | 越界改树 | 本方案**显式登记**请求 §4.1 追加；未确认前 P3 不执行；备选（塞入 `core_channels_ros.py`）已否决 |
| 端口 `None` 默认回退在生产被漏注入 | 关停探测恒假/日志 sink 变更 | 组合根是唯一生产装配点，P4 强制注入；L2 冒烟断言注入生效；总纲 §4.2 允许 `dispatcher_node→ros_adapter` |
| config `log=` 注入未覆盖某调用点 | 告警静默丢失 | `load_yaml`/`apply_config`/`flatten_leaf_params` 消费方唯一（`create_dispatcher_engine`）；P2 逐调用点核对 |
| S4a 端口化改写 middleware 缝（`record_*`）引入行为差异 | 反馈面状态丢失 | 缝内逻辑逐行搬移、不改判定；L2/L3 断言 `emit` 载荷与 `_grasp_images` 裁剪 |
| S4b 按错门槛执行完整拆分 | 3077 行回归、期不收敛 | §7.2.3 五条门槛全满足才执行；初判**降级 B**，登记总纲 §4.7 |
| `test_connection_lease.py#L438-L454` 期望与现值不符（§2.6） | 误判为 S4 引入 | 登记为非本期既有不一致；S4a 不改其断言，保持既有运行态 |
| grep 门禁命中注释/字符串 | 误报 | 判定命令配人工剔除注释；门禁脚本迁移登记为后续轮次 |

回滚路径：S4a 逐步「还原原文件 + 删除新增 `*_ros.py`」；S4b 未执行，无回滚需求。执行前对 `PKG/` 全量快照（主机本地，不入库）。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|---|---|---|
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-ros-adapter-split.md` | 新增 | 本方案（S4 子方案） |
| `PKG/dispatcher/ros_adapter/params_ros.py` | 新增 | `set_ros_params` / `get_private_param` |
| `PKG/dispatcher/ros_adapter/clock_ros.py` | 新增 | `RosShutdown` / `RosLog` / `RosNode`（不建 `RosClock`） |
| `PKG/dispatcher/ros_adapter/feedback_ros.py` | 新增（待 §4.1 追加确认） | zenoh ROS 反馈面 + `reset_stack` 端口 |
| `PKG/dispatcher/utils/config.py`（S2 后路径；现状 `PKG/dispatcher/config.py`） | 修改 | 删 `import rospy`/`set_ros_params`；4 处 `logwarn` → `log.warn`（`log=` 注入） |
| `PKG/dispatcher/utils/control_plane.py`（现状 `PKG/dispatcher/tools/control_plane.py`） | 修改 | 删懒 `import rospy`；`log=`/`shutdown=`/`feedback_factory=` 注入 |
| `PKG/dispatcher/utils/zenoh_rpc.py`（现状 `PKG/dispatcher/zenoh_rpc.py`） | 修改 | 删 ROS 订阅/回调体/`ServiceProxy`/`STACK_RESET_SERVICE`；增 `bind_feedback`/`record_*`；`reset_stack` 端口 |
| `PKG/dispatcher_node.py` | 修改 | 删 `import rospy`；`RosNode`/`params_ros` 替换 bootstrap；构造并注入端口 |
| `PKG/dispatcher/perception/**` | 不改（S4b 未执行） | 评估见 §7.2，登记总纲 §4.7 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-architecture-stabilization.md#§4.1/§4.7` | 已确认（总纲已更新） | 已追加 `feedback_ros.py`；已登记 S4b 降级后续轮次 |

**未核实项汇总**：① S3 落盘后 `create_dispatcher_engine` 调用点的确切行号；② `test_connection_lease.py#L438-L454`
当前运行态（本环境未执行 pytest）；③ L3 级 `/rosout`、`rostopic`、`rosparam` 字节级对比（需 ROS 主机）；
④ 仓库内 `publish_image`/`publish_compressed_image`/`publish_current_state` 是否有仓库外调用方（仓内无调用方，
主机侧未核实）。

## 11. 附录：执行记录

### 2026-09-12 执行（S4a 置 done；S4b 降级 B 维持）

- **执行者**：code-fixer 子智能体执行 P0–P4（其中 P0/P1 及部分 P2–P4 为上一轮被中断的执行残留，经快照 diff 逐项核对与方案一致后续接补完）；SOLO Agent 独立复验门禁。
- **快照**：`/tmp/diffagent2-s4-snapshot-20260912-172803`。
- **产物**：新建 `ros_adapter/{params_ros,clock_ros,feedback_ros}.py`；改写 `utils/{config,control_plane,zenoh_rpc}.py` 与 `dispatcher_node.py`；perception/** 未触碰（S4b 降级）。
- **门禁实测（主 Agent 独立复跑）**：A2——非 `ros_adapter/` 的 `rospy|_msgs|std_srvs|cv_bridge|message_filters` 命中仅 `perception/{base_policy,pointcloud_accumulator}.py`（S4b 留红，§7.2 已登记）+ `core/task_phase.py#L56`（docstring 文字「std_msgs/String JSON」，非 import，登记剔除）；`utils/`+`NODE` 语义零 rospy（仅 `config.py#L86` docstring 与 NODE 注释提及）；G8（utils+NODE 的 `*_msgs` import）零命中；A1（tools↛支撑面、utils↛ros_adapter、utils/core/perception↛engine）零命中；py_compile 全绿；L1 `import dispatcher.utils.config` OK；pytest 44 通过/6 既有失败（基线一致，TESTS 零改动）。
- **行为不变式自检（diff 快照）**：param 键序（`~{key}`）、`~config_path` 默认 `""`、`/Instruct_res`、`LX_GRASP_RESULT_IMAGE_TOPIC`（默认 `/agent/grasp_result_image`、`queue_size=1, tcp_nodelay=True`）、`/agent_scene_objects`、`/agent/stack_reset`（`timeout=5.0`）、六类日志文本、`print` 面、启动序列（NODE main 与 middleware.start 各位点含 feedback.attach 原 L179/L194 位点）、懒 import 保留在使用点内——全部逐字/逐序一致。
- **勘误（已回写 §4.4）**：`params_ros.get_node_name()` 为方案签名草案未列的必要补项（S3 新增的 `rospy.get_name` 触点，P4 的 `telemetry_node_name` 消费）。
- **R7 事件记录**：执行期间 `config.py`/`zenoh_rpc.py` 出现多次外部并发写回（迟到缓冲覆盖），采用「重编辑+终检补漏+20 秒延时复验」收敛；与 S3 期 specs 回滚事件同源，**已在总执行层面登记为环境风险**。
- **L3 级验收（§8.2/§8.3）**：本机无可用 ROS 节点环境（cv2×NumPy2 不兼容），rosparam/rostopic/`/rosout` 字节级对比**未核实**——静态 diff + L2 pytest 基线一致佐证；登记：随下次带 ROS 环境联调补做。
- **S4b 评估结论（§7.2.3 门槛复核确认）**：门槛 1（无 ROS 感知/几何测试基线）、2（消息类型深入 `Frame`/`OdometryBuffer`/几何构造）、3（3077 行单文件）均不满足 → **维持降级 B**：另立后续轮次（先建无 ROS 感知测试基线 → 去消息化数据结构 → 再拆收发三步），本期只登记不执行；总纲 §4.7/执行计划 §6 已登记。
- **登记的后续轮次待办**：`middleware.__init__` 的 `log`/`shutdown` 端口存而不消费（方案 §4.4 签名要求，control_plane 透传链），待 zenoh_rpc 日志面 print→端口化轮次消费；`test_connection_lease.py#L438-L454` 断言与 `queryable_suffixes()` 现值不一致（既有，非本期）；S4b 三步走轮次。
