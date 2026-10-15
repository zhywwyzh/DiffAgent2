# l3 dispatcher 与 EGO 直连运行

dispatcher 持有六态任务 FSM，经 planner 原生 `/planner/execute_waypoints` Action
驱动 EGO，输出到 `/setpoint_cmd`。默认注册六个基础飞行工具和两个 VLA 工具；
tracking 由独立显式入口装配。当前代码未完成运行验收。

设备侧源码投放、ARM64 k3s 编译和新版 L3 启停入口见
[真机运行说明](../../deployment/k3s/real/README.md)。从编排仓库根执行 `make drone-prepare`、
`make drone-up`；更新用 `make drone-deploy`，关闭用 `make drone-down`。
须先配置独立端侧工作空间及现有底层服务，代码尚未编译和设备验收。

本仓库完整 Unity 仿真入口见[k3s Unity 启动说明](../../deployment/k3s/unity/README.md)。
从编排仓库根执行 `make sim-prepare` 编译，`make up` 启动仿真与当前 L4，
`make status` 查询，`make down` 关闭；首次 L4 依赖用 `make station-setup` 准备。

维护入口见[执行总纲](../../doc/l3-dispatcher-planner/iteration/20260915-20260917/design-dispatcher-migration-execution-order.md)。动作规则归[基础飞行动作契约](../../specs/implemented/inner/flight-actions.spec.md)，线上
信封归[RPC 契约](../../specs/implemented/inner/l3-l4-rpc.spec.md)。

## 环境与构建

需要 ROS Noetic、与实际源码及 ROS 模块兼容的 Python、catkin、Eigen/PCL/OpenCV 及
EGO 的标准 ROS 依赖。构建脚本使用系统 Python 生成 ROS 消息；运行解释器必须能
导入该环境生成的消息和 rospy。Python 依赖列在 ros_packages/dispatcher/requirements.txt。

从编排仓库根执行。先在被忽略的本地配置中设置 ROS_SETUP（ROS 环境脚本）、
L3_BUILD_DIR（源码树之外的构建目录）、L3_PYTHON_ENV（运行虚拟环境目录），以及
LX_STACK_ID、ZENOH_ROUTER；地面相关能力可额外设置 GROUND_Z。不要将机器路径、实际连接信息写入文档。

```bash
source "$ROS_SETUP"
drone_projects/l3-dispatcher-planner/tools/build_ego.sh "$L3_BUILD_DIR"
source "$L3_BUILD_DIR/devel/setup.bash"
python3 -m venv --system-site-packages "$L3_PYTHON_ENV"
source "$L3_PYTHON_ENV/bin/activate"
python3 -m pip install -r drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/requirements.txt
```

构建包含 dispatcher、EGO、planner_execution、Elastic、消息及可视化依赖。
遥测包由 k3s 编译入口显式纳入，默认 launch 不启动遥测，k3s 以独立 Pod 装配。
其他 planner 保持原归属，不承诺切换后能力等价。

## 启动

确认 LX_STACK_ID、ZENOH_ROUTER 已导出到进程环境。地面参数为可选项，普通启动不要求；
起飞会话及贴地能力需要时再通过 ground_z 指定输入 world 系中的已知地面高度。
默认 odometry/cloud 输入分别为
`/ekf_quat/ekf_odom` 和 `/cloud_registered`，可通过同名 launch 参数覆盖。

```bash
roslaunch drone_projects/l3-dispatcher-planner/bringup/launch/basic_flight.launch
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
python3 -m pip install -r drone_projects/l3-dispatcher-planner/tests/requirements.txt
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  drone_projects/l3-dispatcher-planner/tests/basic-flight \
  drone_projects/l3-dispatcher-planner/tests/core-boundary \
  drone_projects/l3-dispatcher-planner/tests/tool-registry \
  drone_projects/l3-dispatcher-planner/tests/ros
```

完整测试需要允许本机回环 socket。ROS 测试自行启动隔离 master、真实 EGO 和正式
入口，以受控 odometry/cloud 验证 cmd；不连接现场 ROS master、生产 router 或飞行器。
l4 消费者测试只读加载工作区的 l4-agent 并核验源文件摘要，不启动 l4 应用或修改其内容。

职责修正前的完整验收为 **115 passed**；另有 11 条 rospy 的 notifyAll 弃用警告。
当前已恢复两个保留字段，并把取消覆盖上行到 dispatcher；按用户要求未重跑验证，
不能将此前结果当作修正版的通过记录。
这证明本轮到 cmd 的边界，不代表 cmd 下游飞控、电机或实机已经验收。

## 控制职责边界

普通取消立即释放调用资源，独立发送原生 Action 取消与全局急停，由 planner
接管保持并判定动态停稳。停止未确认时不放行新运动，连接恢复不证明已停止。
当前以中央执行缝契约为准，历史测试数字不能替代现行实现的运行证据。
