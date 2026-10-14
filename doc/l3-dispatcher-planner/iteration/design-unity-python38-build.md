# Unity 镜像解释器编译兼容修复方案

> 摘要：沿用已可靠运行的 ROS Noetic 镜像及 Python 3.8，修复新版源码导入失败，完成用户授权的 prepare 构建验证。

## 0. 元信息

- 日期：2026-10-14
- 目标路径：`l3-dispatcher-planner/ros_packages/dispatcher/` 及编译装配
- 状态：已完成，prepare 构建验证通过
- 关联文档：`design-unity-compile-resources.md`

## 1. 背景与动机

最新日志已完成 EGO C++ 编译，但依赖检查在导入 dispatcher.execution.composition 时因 Python 3.8 不支持立即求值的联合类型注解失败。

## 2. 现状事实（问题清单）

- `ros_packages/dispatcher/dispatcher/execution/ports.py:9`：联合注解缺少延迟求值。
- `ros_packages/dispatcher/dispatcher/ros_adapter/feedback_ros.py:1`、`support/tracking_data.py:1`、`tools/track/service/uetrack_api.py:1`：同类注解风险。
- `.artifacts/k3s-unity/compile-l3.log`：C++ 已到 100%，依赖导入返回失败。

## 3. 目标与约束

使用现有解释器编译并导入真实运行闭包，不升级镜像、不设计转接器、不改变任务语义。用户明确授权重复构建直至通过，不扩展到业务启动或飞行验收。

## 4. 方案决策

既有目录和文件名不变。对使用现代注解的模块统一加入 future annotations，消除运行时注解立即求值。若 prepare 暴露其他真实兼容问题，在本方案补充后修复。

依赖探针仍引用不存在的 planner_execution_ros，修正为正式装配实际导入的 planner_action_ros；保留导入检查，不引入转发模块。

## 5. 迁移映射

立即求值的类型注解 → 延迟求值：直接修正，无兼容桥。

## 6. 删除清单

无旧接口需要删除，不增加替代层。

## 7. 实施步骤

先记录方案，修复注解，再执行 make sim-prepare；每次失败读取日志定位。保留编译缓存，按现有入口重建编译 Job。回退仅撤销本方案新增代码。

## 8. 验收标准

用户本轮已明确许可构建验证：make sim-prepare 必须成功，包括 L3、Unity、L2 消息兼容检查及制品记录。除此之外不运行测试套件或业务栈验收。

## 9. 风险与对策

后续依赖可能继续暴露 Python 版本差异，以真实日志逐项修复。不得用移除依赖检查替代修复。

## 10. 修改点清单汇总

- execution/ports.py、ros_adapter/feedback_ros.py、support/tracking_data.py、tools/track/service/uetrack_api.py：延迟注解。
- 本方案：记录后续失败、修复及最终构建结果。


## 执行记录

2026-10-14：已执行完整 make sim-prepare，退出码为 0，入口报告“制品准备完成；业务栈尚未启动”。
L3 与 Unity 编译 Job 均完成，L3 依赖导入报告 Python 3.8.10、ok=true；L2-wire 消息 MD5 检查通过，prepared.json 与 rendered 清单已生成。
修复四个模块的注解立即求值问题，以及 runtime_probe_ros.py 中失效的 planner_execution_ros 引用，改为正式入口实际使用的 planner_action_ros。
本轮未启动业务栈、未运行飞行或端到端验收，也未执行测试套件。
