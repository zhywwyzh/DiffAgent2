# 感知传感器参数重命名方案

> 摘要：去除通用感知传感器参数中的 tracking 命名，按 perception 归属统一参数和属性名称；仅修改 DiffAgent2 新版。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-10-10 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py` |
| 状态 | done（代码修改完成，未测试、未验收） |
| 关联文档 | `specs/implemented/inner/l3-package-layout.spec.md`；`specs/implemented/inner/l3-ros-adapter-boundary.spec.md` |

## 1. 背景与动机

三个通用感知参数含 tracking 前缀，容易被误认为目标跟踪配置。用户要求先修改名称。

## 2. 现状事实（问题清单）

- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py:483`：注释及三个参数使用 tracking 命名。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py:509`：深度缓存使用时间匹配容差，订阅句柄也含 tracking。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py:524`：点云缓存及订阅存在同类命名。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py:708`：深度缓存用于通用 Frame 构建。

## 3. 目标与约束

- 目标：参数归属 perception，时间参数带 `_s`，属性与订阅名称表达通用感知用途。
- 范围外：目标跟踪迁移、开关逻辑补齐、缓存清理及 ROS 分层调整。
- 硬边界：不新增转接器，不保留旧参数兼容读取；默认值、缓存容量及订阅行为保持原样。

## 4. 方案决策

- 目标目录树：保持现有 `dispatcher/perception/base_policy.py`，不新增平面或模块。
- 命名规范表：

| 类型 | 规范 | 示例 |
|----|----|----|
| 文件 | 保持现有归属 | `perception/base_policy.py` |
| 类与函数 | 本次不改 | `BasePolicy` |
| ROS 参数 | perception 前缀；时间带单位 | `~perception/depth_max_delta_s` |
| 属性 | 去除错误领域前缀；时间带单位 | `depth_max_delta_s` |
| 订阅句柄 | 传感器原始输入命名 | `_depth_raw_sub` |

接口形态：由现有读取位置唯一装载新参数；旧参数不再读取。外部配置需显式改用新键。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|----|----|----|----|
| `~tracking_sensor_enable` | `~perception/sensor_enable` | rename | 默认 true；仍只保存配置值 |
| `~tracking_depth_max_delta` | `~perception/depth_max_delta_s` | rename | 默认 0.1 秒 |
| `~tracking_cloud_max_delta` | `~perception/cloud_max_delta_s` | rename | 默认 0.05 秒 |
| `tracking_sensor_enable` 属性 | `sensor_enable` | rename | 不增加控制逻辑 |
| `tracking_depth_max_delta` 属性 | `depth_max_delta_s` | rename | 同步缓存构造引用 |
| `tracking_cloud_max_delta` 属性 | `cloud_max_delta_s` | rename | 同步缓存构造引用 |
| `_tracking_depth_sub` | `_depth_raw_sub` | rename | 同步未启用深度分支 |
| `_tracking_cloud_sub` | `_cloud_raw_sub` | rename | 订阅行为不变 |

## 6. 删除清单

| 删除项 | 理由 |
|----|----|
| 原参数读取及原属性、句柄名称 | 已被新名称替代，不留兼容接口 |
| 当前快通道注释中的 tracking 限定 | 数据用于通用感知帧 |

## 7. 实施步骤（P0/P1/... 分期）

### P0 — 方案落盘

- 范围：记录映射、行为边界及外部参数迁移要求。
- 行为不变式：不修改代码。
- 验收：未经用户明确许可跳过。
- 回退：撤回本方案新增文件。

### P1 — 同步重命名

- 范围：按映射修改参数、属性、订阅句柄和相邻注释。
- 行为不变式：默认值、缓存容量、数据流和订阅主题保持不变。
- 验收：未经用户明确许可跳过测试与验证性验收。
- 回退：成组还原本次命名修改及外部参数配置。

## 8. 验收标准

统一声明：除非使用者明确许可，否则跳过验收测试工作；本轮不运行测试或验证性验收。
后续获许可时检查新参数装载、深度缓存匹配与订阅行为；旧名不提供兼容读取。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|----|----|----|
| 外部仍使用旧参数键 | 旧配置不再生效，读取新键默认值 | 明确列出参数映射，部署时同步修改外部配置 |
| sensor_enable 名称被理解为已实现控制 | 与现有只保存值的行为不符 | 本轮保留行为并明确记录，后续逻辑另行设计 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|----|----|----|
| `doc/l3-dispatcher-planner/iteration/design-perception-sensor-parameter-naming.md` | add | 方案及实施状态 |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py` | edit | 参数、属性、句柄和注释重命名 |
