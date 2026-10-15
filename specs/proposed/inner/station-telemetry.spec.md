# 站端遥测生产契约

Status: proposed — 待评审，尚未采纳
Contract-ID: runtime/station-telemetry
Parent: specs/proposed/runtime.spec.md

## 范围与非目标

约束独立 telemetry_bridge 的遥测生产，不拥有任务、租约、取消或 planner goal；日志使用独立流水线。

## 术语与身份

stack 绑定遥测频道与 presence；instance 是进程在线身份，不能证明飞行能力。各频道名及载荷字段见线上载荷。

## 输入、输出与配置

### 线上载荷

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

## 行为规则

### 所有权

`telemetry_bridge` 是独立 ROS 数据生产者；不接任务、租约、取消或 planner goal。
ROS 订阅只在 `telemetry_ros.py`；编码与限流为无 ROS 依赖模块。
每个进程独占 Zenoh client 会话，禁用 multicast，连接显式 router。
presence 为 `lx/<stack>/presence/telemetry/<instance>`，每通道使用
BestEffort/Drop；有界最新值槽、通道频率上限和聚合带宽上限，不积压历史图像。

## 失败、取消与资源生命周期

### 生命周期

ROS 回调只提交最新值；后台单线程编码发送，失败节流报告，关停逆序注销订阅、
presence、publisher 和会话。健康文件报告输入年龄及成功发送年龄，缺少数据
不得被 Pod Running 掩盖。日志另由 fluent-bit 和 relay 上传，不复用遥测会话。

## 归属与依赖

本叶唯一拥有站端消费者对应的遥测载荷；ROS 与编码边界按所有权章节，任务和日志不由本叶定义。

### 变更关联

```contract-links
{
  "implementation": [
    "l3-dispatcher-planner/ros_packages/telemetry_bridge/**",
    "l3-dispatcher-planner/bringup/k3s/unity/telemetry.deployment.yaml"
  ],
  "depends_on": [
    "runtime"
  ]
}
```

## 条款检查判据

ST1：按频道核对源时戳、坐标、二进制布局和真实值；ST2：核对限流、最新值槽及逆序关闭；ST3：核对无输入时的年龄报告。端到端证据归实施记录，未获许可不执行检查。

检查执行与证据记录遵循 `specs/README.md` 的统一许可边界；本文件不记录通过结论。
