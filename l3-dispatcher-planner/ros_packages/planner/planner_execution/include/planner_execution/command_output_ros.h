#pragma once
#include <ros/ros.h>
#include <ros/callback_queue.h>
#include <nav_msgs/Odometry.h>
#include <quadrotor_msgs/PositionCommand.h>
#include <quadrotor_msgs/ExecutionState.h>
#include <quadrotor_msgs/CommandState.h>
#include <functional>
#include <array>
#include <std_msgs/Empty.h>
#include <mutex>
#include <memory>
#include <cstdint>

namespace planner_execution {
// 唯一 cmd 输出仲裁。停止/保持不使用 planner 的长规划锁，也不修改地图。
class CommandOutput {
 public:
  explicit CommandOutput(ros::NodeHandle nh, bool remote = false, bool publish = true, const std::string& command_topic="/position_cmd");
  ~CommandOutput();
  void request_stop();
  bool requestStopIfCurrent(uint64_t generation);
  void set_boot(uint64_t boot);
  void set_gains(const std::array<double,3>& kx,const std::array<double,3>& kv);
  bool obsolete(uint64_t boot,uint64_t generation) const;
  bool deliver(uint64_t generation, const std::function<void()>& send);
  bool resume(uint64_t expected_generation);
  uint64_t generation() const;
  bool enabled() const;
  bool holding() const;
  bool matches(uint64_t boot, uint64_t generation) const;
  bool publish(const quadrotor_msgs::PositionCommand& cmd, uint64_t generation, uint64_t boot = 0);
 private:
  void odometry(const nav_msgs::OdometryConstPtr& msg);
  void remote_state(const quadrotor_msgs::ExecutionStateConstPtr& msg);
  void tick(const ros::WallTimerEvent&);
  void hold_locked();
  mutable std::mutex mutex_;
  ros::CallbackQueue queue_;
  ros::NodeHandle nh_;
  ros::Publisher publisher_, confirmation_;
  ros::Subscriber odometry_, stop_, state_, confirmation_sub_;
  ros::WallTimer timer_;
  std::unique_ptr<ros::AsyncSpinner> spinner_;
  quadrotor_msgs::PositionCommand reference_, hold_;
  bool blocked_{true}, have_pose_{false}, hold_valid_{false}, hold_sent_{false};
  bool remote_, publish_;
  uint64_t generation_{1}, boot_{0}, remote_stop_generation_{0};
  ros::WallTime last_state_, pose_received_, confirmation_received_;
  uint64_t confirmed_generation_{0}, confirmed_boot_{0};
  bool confirmed_hold_{false};
  double state_timeout_{1};
  std::string world_frame_;
};
}
