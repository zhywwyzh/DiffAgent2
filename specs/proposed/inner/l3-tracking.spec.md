# 连续目标跟踪契约

Status: proposed — 待评审，尚未采纳
Contract-ID: l3-dispatcher/tracking
Parent: specs/implemented/l3-dispatcher.spec.md

## 范围与非目标

### 1. 能力与边界

`navigation.track` 消费站端一次选定的目标，机上连续进行视觉跟踪、深度定位和运动跟随。
输入必填 `object`、`prompt`、原图像素 xyxy `bbox`、`image_stamp` 和 `session_id`。
未知参数拒绝；框须有限、正面积、在对应图像内；种子必须匹配缓存原图。
技能异步、`requires_perception=false`，自行检查专属观测，持有 flight-exclusive 槽。
完成语义为 workflow_result：业务稳定条件和执行停止确认同时满足才能成功。
未通过获许可后的验收前只提供显式 tracking 装配入口，不加入默认生产注册表。

### 6. 能力边界

首期仅 EGO 装配 Elastic；其他后端不提供连续 action 时必须明确不可执行，
不得通过兼容桥转发至旧接口。默认工具集合不因未采纳提案或未验收实现变化。

## 术语与身份

视觉会话身份、推理请求序号与执行身份分别关联各自资源；不得替代工具名或 call_id。对应职责见 §2、§3。

## 输入、输出与配置

### 3. 原生连续执行

`/planner/track_target` 使用 TrackTarget action。目标携带视觉会话身份、执行身份、
跟随距离及容差、目标高度、观测有效期和有限执行期限。期限不超过部署允许的上界。
`/planner/tracking_observation` 直接承载 TrackingObservation：同帧 bbox、内外参、
图像尺寸、源时戳、递增序号与执行身份。只接收当前执行且新鲜的观测。
Feedback 携带目标有效性、源观测序号、源时戳、目标位置和速度；不得作为工具成功事件。
Result 包含 reason、stop_confirmed、state_valid。取消后 PREEMPTED 只有在保持接管且
连续动态停稳后才允许 stop_confirmed=true。超时、定位/地图失效均停止并失败。

### 5. 配置和资源

技能参数归 `~track/*`；执行停止归 `/planner_execution/*`；算法参数归 `/elastic_tracker/*`。
跟随距离与目标高度随 action 传入，不在 planner 保存第二份业务默认值。
推理 HTTP 和图像编码在 worker 中进行，不占 engine 生命周期锁。
注册返回幂等逆操作，关闭时停 worker、注销端点；旧 HTTP reset 不得清除新会话。
模型服务需要 CUDA 和校验通过的本地权重，不在任务调用过程中下载模型。
遥测 `/tracking/observation` 与 `/tracking/image/compressed` 不驱动控制，图框绑定同一推理帧。

### 8. 宿主端口提案

TrackHost 提供
`config`、`state`、`frames`、`require_idle`、`report`、`arm`、`start_tracking`、`tracking_feedback`、
`publish_observation`、`publish_telemetry`、`finish_tracking`、`poll_tracking`、`fail_sequence`、
`complete`、`cancel_execution`；ROS 收发经适配端口，技能不得访问 engine 私有状态。
`frames` 是宿主的只读缓存访问端口，推理生产者只读；写入方仅为 ROS 适配层。
未验收实现不加入默认生产集合，显式装配返回 disposer。

### 11. 显式装配与元数据提案

`tracking.launch` 以 `dispatcher_node.py --tracking-profile` 在组合根注入
工具面生效集合八项加 `navigation.track` 的独立注册表；普通入口仍为八项。此入口只用于后续获许可的联调，不代表生产能力。它不是 RPC 启停开关，列表
不随模型或传感器就绪状态变化；revision 由该入口实际元数据计算，不复用八项记录值。
`navigation.track` 的 schema 与生命周期归 `specs/proposed/inner/l3-tracking.spec.md`，
完成元数据为 `workflow_result`，并发语义为 `flight-exclusive`。

## 行为规则

### 7. 首期几何与输出限制

深度必须对齐 RGB，时戳差不超过 0.04 s，位姿按图像时间插值。框内正有限深度取中位数，
再固定目标世界高度；尚未引入目标分割或深度有效比例门，背景污染仍是适用限制。
外参必须显式给出：`camera_rotation` 是光学轴转换之后的安装旋转，
`camera_translation` 是相机原点在机体系的偏移（米），不得把光学轴转换重复计入旋转。
EGO 内部大小图及导航职责保留；仅小图启用 tracking 的历史射线自由证据。
Elastic 直接消费无 ROS 的 MapView；删除旧 MapPort、freeze 接入和伪 OccGridMap，不保留兼容壳。
读取在融合所有者锁内按需复制，锁忙或两个快照均在使用时明确不可用；规划期间不冻结 EGO 输出。
基础占据、膨胀障碍、未知、越界、虚拟边界分别解释。飞机搜索、走廊及交付统一要求未屏蔽的
膨胀地图可通行且具有历史真实射线自由证据；命中、滑窗、重置使相关自由证据失效，衰减和人工目标
清空不得产生自由证据。EGO 人工目标清除入口启用时拒绝共享读取。
目标预测仅提供运动假设，不用目标自身占据否决，也不承诺无障碍；目标可见射线采用基础占据和
自由证据，仅排除终点格。删除方盒屏蔽；目标贴墙、目标厚度或未知空间导致不可见时保守失败。
完整预测时域保留，覆盖不足不静默缩短时域。轨迹检查覆盖终点、采样点间线段，交付前在最新
快照重复检查；重置代次变化、地图过期或不可用均停止失败。该检查仍属于离散采样，不声明连续
多项式碰撞的形式证明。采样线程独立遵守已接受地图的源时钟与单调时钟期限。
快照分别记录实际融合输入的源时戳、融合完成时间和单调完成时间；零输入时戳、过期或倒退不得宣称地图新鲜。全图融合新鲜度不代表逐格观测年龄。
本期未实现逐格观测年龄及目标分割，此限制和未验收状态必须保留。
搜索耗尽或轨迹不可行明确失败，不绕过碰撞或动态上限。
跟踪采样使用与 EGO 相同的 PositionCommand 增益语义，不另设控制器增益默认值。

### 10. 连续执行资源提案

连续目标跟踪使用独立原生 action。新增原生 action 与观测数据流，
不向 WaypointTarget 恢复旧跟随预留。EGO 同进程共用动作资源和输出；普通动作与连续动作
互斥。连续动作不使用静态航点到达门，只复用定位、期限、停止和动态停稳；业务完成归技能。

## 失败、取消与资源生命周期

### 4. 业务完成和恢复

默认距离 2.5 m、距离容差 0.3 m、偏航容差 0.2 rad；飞机和目标速度分别不超过
0.1 m/s、0.2 m/s，连续 3 s 才形成完成候选。位姿和目标观测必须新鲜、递增。
目标 z 默认固定为世界系 1 m；仅声明固定高度跟随，不声明任意三维运动跟随。
初始化 30 s、短时丢失 5 s、调用总期限 600 s，均使用单调时钟。
短时失效先停旧运动，确认停稳后才可在同一视觉会话内重启新的执行代次。
正常收尾可内部取消连续 action，但须有业务完成候选和确认停止结果，才提交工具成功。
外部取消、租约丢失和覆盖优先，清除完成候选，恰好一个失败终态。
取消立即释放任务引用，设备停止确认独立跟踪；建图、定位、原点和常驻通信不释放。

## 归属与依赖

### 2. 职责

TrackSkill 持有 STARTING、ACTIVE、HOLD、STOPPING，core 保持六态。
UETrack 服务独立进程执行串行推理；会话 epoch、请求序号隔离重复和迟到请求。
ROS 适配层写入有界 RGB 历史，宿主经端口提供原始种子与最新帧。
Elastic 领域库持有深度投影、目标滤波、可见路径与轨迹优化；从原生读取接口获取 EGO 小图的不可变分类快照。
首期 EGO 和 Elastic 同进程，共享 planner_execution 的运动资源、CommandOutput 和停止门。
普通动作与连续动作不得同时准入，不重复概率融合；允许最多两个有界分类快照，不复制概率历史或 ESDF，不恢复 mission 或 MotionGate。

### 9. 目录与依赖提案

`execution/skill_host.py` 读取感知缓存并通过 TrackHost 暴露只读端口，
`tools/track/` 不导入 perception 或 ROS。推理服务及 HTTP 客户端归 track 家族。
ROS 适配层可导入 `tools/track/ports.py` 的纯数据协议，不能导入技能流程实现。
Elastic 的地图读取由 EGO 装配根直接注入；领域数据协议 MapView 归 Elastic，EGO 小图所有者生产一致快照。Elastic 不反向依赖 EGO 包，领域算法不依赖 ROS 消息或参数树。

### 12. 站端消费提案

显式 tracking 入口见本提案 §11；默认生产集合仍归 `l3-dispatcher/tool-plane` §1。
站端须按发现结果处理 `navigation.track`，传入原始像素框、精确图像时戳和视觉会话身份。
其 `workflow_result` 只在业务稳定和执行停止确认后由 dispatcher 产生；内部连续 action
取消回执不是 RPC 成功或外部取消事件。站端不得沿用旧版 `action_result` 元数据推导成功。
本提案不拥有外部站端代码；消费闭环证据归实施记录。

## 条款检查判据

TR1：按 §1、§3、§8、§11 核对输入与装配；TR2：按 §4 核对业务完成、外部取消优先与停止确认；TR3：按 §7 核对几何和输出限制。运行证据归迁移方案，未获许可不执行检查。

检查执行与证据记录遵循 `specs/README.md` 的统一许可边界；本文件不记录通过结论。
