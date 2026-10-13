# 站端遥测生产契约

Status: proposed — 对齐当前独立 L4 消费者，未运行验收
Contract-ID: runtime/station-telemetry
Parent: specs/proposed/runtime.spec.md

## 所有权

`telemetry_bridge` 是独立 ROS 数据生产者；不接任务、租约、取消或 planner goal。
ROS 订阅只在 `telemetry_ros.py`；编码与限流为无 ROS 依赖模块。
每个进程独占 Zenoh client 会话，禁用 multicast，连接显式 router。
presence 为 `lx/<stack>/presence/telemetry/<instance>`，每通道使用
BestEffort/Drop；有界最新值槽、通道频率上限和聚合带宽上限，不积压历史图像。

## 线上载荷

通道为 `lx/<stack>/telemetry/<channel>`，与当前 L4 的
`station_sidecar/telemetry_cache/decoders.py`、`bridge.py` 对齐：

- meta：每秒 hello JSON，role=drone_bridge、version=2、uptime_s、params。
- drone_status：JSON，stamp 为 odometry 源秒时间；odom 含位置、四元数和世界系
  线速度；battery、mode 未知用 null；camera_calibration 使用实际 CameraInfo
  内参；外参通过本站端已有环境入口显式同步，不把假电池或假飞控模式作为飞行状态。
- camera：`<d` 小端源秒时戳后接完整 JPEG；限流保留实际 header。
- depth：`<BHH`，codec=1、宽、高，后接 16 位毫米 PNG；0 表示无效。
- cloud：`<BI`，codec=0、点数，后接世界坐标 xyz 小端 float32；有限点、体素
  降采样与数量上限。非 world 坐标显式拒绝，不能改 frame 标签冒充世界点。

不发布无真实生产者的 grid_map、trajectory、scenegraph。original 场景的图像
时间是 L2 接收时间，不能宣称严格采样同步。深度仅用于当前预览消费者，精度
限制仍归原场景输入；不伪造相机和位姿同步证据。

## 生命周期

ROS 回调只提交最新值；后台单线程编码发送，失败节流报告，关停逆序注销订阅、
presence、publisher 和会话。健康文件报告输入年龄及成功发送年龄，缺少数据
不得被 Pod Running 掩盖。日志另由 fluent-bit 和 relay 上传，不复用遥测会话。
