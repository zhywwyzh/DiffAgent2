# l3 dispatcher 与 EGO 直连运行

本轮已实现六个 `basic_flight.*` 工具。dispatcher 持有六态任务 FSM，经普通 ROS
消息直接驱动 EGO，输出到 `/setpoint_cmd`；不启动 mission_executive 或任何 action
转换节点。cmd 下游处理不属于此处交付范围。

维护入口见[执行总纲](../doc/l3-dispatcher-planner/iteration/design-dispatcher-migration-execution-order.md)。动作规则归[基础飞行动作契约](../specs/implemented/inner/flight-actions.spec.md)，线上
信封归[RPC 契约](../specs/implemented/inner/l3-l4-rpc.spec.md)。

## 环境与构建

需要 ROS Noetic、Python 3.10 或更新的兼容解释器、catkin、Eigen/PCL/OpenCV 及
EGO 的标准 ROS 依赖。构建脚本使用系统 Python 生成 ROS 消息；运行解释器必须能
导入该环境生成的消息和 rospy。Python 依赖列在 ros_packages/dispatcher/requirements.txt。

从编排仓库根执行。先在被忽略的本地配置中设置 ROS_SETUP（ROS 环境脚本）、
L3_BUILD_DIR（源码树之外的构建目录）、L3_PYTHON_ENV（运行虚拟环境目录），以及
LX_STACK_ID、ZENOH_ROUTER 和 GROUND_Z；不要将机器路径、实际连接信息写入文档。

```bash
source "$ROS_SETUP"
l3-dispatcher-planner/tools/build_ego.sh "$L3_BUILD_DIR"
source "$L3_BUILD_DIR/devel/setup.bash"
python3 -m venv --system-site-packages "$L3_PYTHON_ENV"
source "$L3_PYTHON_ENV/bin/activate"
python3 -m pip install -r l3-dispatcher-planner/ros_packages/dispatcher/requirements.txt
```

构建只包含 dispatcher、EGO 和所需的最小消息/可视化依赖，不拉入场景图、
遥测 bridge、mission 或 waypoint action 转发脚本。其他 planner 的代码仍在仓库，
但本轮只完成 EGO 的构建和六能力验收，不承诺直接切换到其他后端后能力等价。

## 启动

确认 LX_STACK_ID、ZENOH_ROUTER 已导出到进程环境。GROUND_Z 必须是输入 world
坐标系中已校准的地面高度；未知时不要填猜测值。默认 odometry/cloud 输入分别为
`/ekf_quat/ekf_odom` 和 `/cloud_registered`，可通过同名 launch 参数覆盖。

```bash
roslaunch l3-dispatcher-planner/bringup/launch/basic_flight.launch ground_z:="$GROUND_Z"
```

该入口启用 headless dispatcher，不要求视觉感知配置；飞行仍要求新鲜、有限、坐标系
正确的 odometry。默认世界坐标系名为 world。输入过期或坐标系不符会失败，不能靠
关闭视觉模块绕过状态检查。只读 l4 通过发现和租约连接调用，未持有租约的调用拒绝。

起降工具只表示命令已经转交 `/px4ctrl/takeoff_land`，对应消费者不在此入口内启动。
没有该消费者时起降调用失败。返航只接受空参，返回本飞行会话的起飞点水平位置，
保持当前合法高度，不自动降落；无确认原点时失败。重启不恢复历史原点。

## 验证

先安装测试依赖，再在已加载 ROS 与外部构建环境的解释器中执行：

```bash
python3 -m pip install -r l3-dispatcher-planner/tests/requirements.txt
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  l3-dispatcher-planner/tests/basic-flight \
  l3-dispatcher-planner/tests/core-boundary \
  l3-dispatcher-planner/tests/tool-registry \
  l3-dispatcher-planner/tests/ros
```

完整测试需要允许本机回环 socket。ROS 测试自行启动隔离 master、真实 EGO 和正式
入口，以受控 odometry/cloud 验证 cmd；不连接现场 ROS master、生产 router 或飞行器。
l4 消费者测试只读加载工作区的 l4-agent 并核验源文件摘要，不启动 l4 应用或修改其内容。

职责修正前的完整验收为 **115 passed**；另有 11 条 rospy 的 notifyAll 弃用警告。
当前已恢复两个保留字段，并把取消覆盖上行到 dispatcher；按用户要求未重跑验证，
不能将此前结果当作修正版的通过记录。
这证明本轮到 cmd 的边界，不代表 cmd 下游飞控、电机或实机已经验收。

## 控制职责边界

planner 仅同步去除来源任务编号；保留 yaw_low_speed、goal_to_follower 及原有行为。
普通取消由 dispatcher 以新批次发送当前位置/当前 yaw 的保持目标，不依赖新增的
planner/cancel 入口。显式急停保留既有全局信号，并由 dispatcher 编排保持目标。
位姿失效或发送失败时不假报停止、不放行新动作；本修正尚未做运行验证。
