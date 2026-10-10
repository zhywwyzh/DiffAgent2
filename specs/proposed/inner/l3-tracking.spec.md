# 连续目标跟踪契约

Status: proposed
Contract-ID: l3-dispatcher/tracking
Parent: specs/implemented/l3-dispatcher.spec.md

## 1. 能力与边界

`navigation.track` 消费站端一次选定的目标，机上连续进行视觉跟踪、深度定位和运动跟随。
输入必填 `object`、`prompt`、原图像素 xyxy `bbox`、`image_stamp` 和 `session_id`。
未知参数拒绝；框须有限、正面积、在对应图像内；种子必须匹配缓存原图。
技能异步、`requires_perception=false`，自行检查专属观测，持有 flight-exclusive 槽。
完成语义为 workflow_result：业务稳定条件和执行停止确认同时满足才能成功。
未通过获许可后的验收前只提供显式 tracking 装配入口，不加入默认生产注册表。

## 2. 职责

TrackSkill 持有 STARTING、ACTIVE、HOLD、STOPPING，core 保持六态。
UETrack 服务独立进程执行串行推理；会话 epoch、请求序号隔离重复和迟到请求。
ROS 适配层写入有界 RGB 历史，宿主经端口提供原始种子与最新帧。
Elastic 领域库持有深度投影、目标滤波、可见路径与轨迹优化；从原生地图查询端口读取 EGO 地图。
首期 EGO 和 Elastic 同进程，共享 planner_execution 的运动资源、CommandOutput 和停止门。
普通动作与连续动作不得同时准入，不复制地图，不恢复 mission 或 MotionGate。

## 3. 原生连续执行

`/planner/track_target` 使用 TrackTarget action。目标携带视觉会话身份、执行身份、
跟随距离及容差、目标高度、观测有效期和有限执行期限。期限不超过部署允许的上界。
`/planner/tracking_observation` 直接承载 TrackingObservation：同帧 bbox、内外参、
图像尺寸、源时戳、递增序号与执行身份。只接收当前执行且新鲜的观测。
Feedback 携带目标有效性、源观测序号、源时戳、目标位置和速度；不得作为工具成功事件。
Result 包含 reason、stop_confirmed、state_valid。取消后 PREEMPTED 只有在保持接管且
连续动态停稳后才允许 stop_confirmed=true。超时、定位/地图失效均停止并失败。

## 4. 业务完成和恢复

默认距离 2.5 m、距离容差 0.3 m、偏航容差 0.2 rad；飞机和目标速度分别不超过
0.1 m/s、0.2 m/s，连续 3 s 才形成完成候选。位姿和目标观测必须新鲜、递增。
目标 z 默认固定为世界系 1 m；仅声明固定高度跟随，不声明任意三维运动跟随。
初始化 30 s、短时丢失 5 s、调用总期限 600 s，均使用单调时钟。
短时失效先停旧运动，确认停稳后才可在同一视觉会话内重启新的执行代次。
正常收尾可内部取消连续 action，但须有业务完成候选和确认停止结果，才提交工具成功。
外部取消、租约丢失和覆盖优先，清除完成候选，恰好一个失败终态。
取消立即释放任务引用，设备停止确认独立跟踪；建图、定位、原点和常驻通信不释放。

## 5. 配置和资源

技能参数归 `~track/*`；执行停止归 `/planner_execution/*`；算法参数归 `/elastic_tracker/*`。
跟随距离与目标高度随 action 传入，不在 planner 保存第二份业务默认值。
推理 HTTP 和图像编码在 worker 中进行，不占 engine 生命周期锁。
注册返回幂等逆操作，关闭时停 worker、注销端点；旧 HTTP reset 不得清除新会话。
模型服务需要 CUDA 和校验通过的本地权重，不在任务调用过程中下载模型。
遥测 `/tracking/observation` 与 `/tracking/image/compressed` 不驱动控制，图框绑定同一推理帧。

## 6. 交付状态

按迁移方案实施，未运行测试、构建或验收。首期仅 EGO 装配 Elastic；其他后端不提供
连续 action 时明确不可执行，不通过兼容桥转发至旧接口。默认工具集合不因未验收实现变化。

## 7. 首期几何与输出限制

深度必须对齐 RGB，时戳差不超过 0.04 s，位姿按图像时间插值。框内正有限深度取中位数，
再固定目标世界高度；尚未引入目标分割或深度有效比例门，背景污染仍是适用限制。
外参必须显式给出：`camera_rotation` 是光学轴转换之后的安装旋转，
`camera_translation` 是相机原点在机体系的偏移（米），不得把光学轴转换重复计入旋转。
算法局部查询允许屏蔽目标附近占据；轨迹交付检查使用未屏蔽的 EGO 膨胀地图，并覆盖终点，
不删除共享地图占据。搜索耗尽或轨迹不可行明确失败，不绕过碰撞或动态上限。
跟踪采样使用与 EGO 相同的 PositionCommand 增益语义，不另设控制器增益默认值。
