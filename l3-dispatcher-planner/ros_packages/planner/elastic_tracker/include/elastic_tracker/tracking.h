#pragma once
#include <elastic_tracker/algorithm_config.h>
#include <planner_execution/execution_ports.h>
#include <Eigen/Geometry>
#include <memory>
#include <functional>
#include <vector>
#include <optional>
namespace elastic_tracker {
/** EGO 原生占据查询；坐标单位为米，freeze 只冻结输出快照。 */
struct MapPort {
  double resolution;
  std::function<bool(const Eigen::Vector3d&)> occupied;
  std::function<bool()> ready;
  std::function<void(bool)> freeze;
};
/** world 位姿；stamp 为传感器时间（秒），position 单位为米。 */
struct Pose {
  double stamp;
  Eigen::Vector3d position;
  Eigen::Quaterniond orientation;
};
/** 对齐 RGB 的深度帧；16UC1 使用毫米，32FC1 使用米。 */
struct Depth {
  double stamp;
  unsigned width, height, step;
  bool is_bigendian;
  std::string encoding;
  std::vector<uint8_t> data;
};
/** world 指令：米、米/秒、米/秒平方、米/秒立方；偏航单位为弧度。 */
struct Command {
  planner_execution::Vec3 position, velocity, acceleration, jerk;
  double yaw, yaw_rate;
  uint64_t generation;
  bool valid{true};
};
/**
 * 连续目标估计与规划，不持有 ROS 资源。
 * start/commit/stop/observation/plan/feedback 由执行服务串行调用；
 * receivePose、receiveDepth 和 sampleCommand 可在独立传感器/采样线程调用。
 */
class Tracking {
 public:
  Tracking(MapPort map, AlgorithmConfig config, double min_height, double max_height);
  ~Tracking();
  /** 建立有界执行；now 为当前源时间（秒），返回空字符串表示可准入。 */
  std::string startTracking(const planner_execution::TrackRequest& request, double now);
  void commitExecution(uint64_t generation);
  void stopTracking();
  void receivePose(const Pose& pose);
  void receiveDepth(Depth depth);
  void receiveObservation(const planner_execution::TrackObservation& value);
  std::string planTracking(double source_now);
  planner_execution::TrackFeedback getFeedback() const;
  /** 独立采样；源时间或单调时间过期时返回 valid=false，撤销当前输出代次。 */
  std::optional<Command> sampleCommand(double source_now);
 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};
}
