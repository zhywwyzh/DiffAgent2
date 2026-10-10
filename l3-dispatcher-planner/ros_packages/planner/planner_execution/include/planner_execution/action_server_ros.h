#pragma once
#include "planner_execution/execution.h"
#include "planner_execution/command_output_ros.h"
#include <atomic>
#include <actionlib/server/action_server.h>
#include <quadrotor_msgs/ExecuteWaypointsAction.h>
#include <quadrotor_msgs/ExecutionState.h>
#include <nav_msgs/Odometry.h>
#include <ros/ros.h>
#include <memory>
#include <mutex>

namespace planner_execution {
class WaypointActionServer {
 public:
  using Server = actionlib::ActionServer<quadrotor_msgs::ExecuteWaypointsAction>;
  using Handle = Server::GoalHandle;
  WaypointActionServer(ros::NodeHandle nh, Backend backend, std::recursive_mutex& mutex, bool external_output=false, const std::string& command_topic="/position_cmd");
  ~WaypointActionServer();
  void start();
  void progress(const Progress& value);
  void fail(const std::string& reason);
  void request_stop();
  std::shared_ptr<CommandOutput> output() const { return output_; }
  uint64_t boot_id() const { return boot_id_; }
  uint64_t generation() const { return output_->generation(); }
  bool motion_enabled() const { return output_->enabled(); }
  static double now();
 private:
  void goal(Handle handle);
  void cancel(Handle handle);
  void odometry(const nav_msgs::OdometryConstPtr& msg);
  void tick(const ros::WallTimerEvent&);
  void publish_state();
  bool apply_stop();
  ros::CallbackQueue queue_;
  ros::NodeHandle nh_;
  std::unique_ptr<ros::AsyncSpinner> spinner_;
  std::shared_ptr<CommandOutput> output_;
  std::recursive_mutex stop_mutex_;
  std::string active_id_;
  bool pending_stop_{false}, pending_cancel_{false};
  double stop_requested_at_{0};
  ros::Subscriber emergency_stop_;
  Config config_;
  std::recursive_mutex& mutex_;
  WaypointExecution execution_;
  std::unique_ptr<Server> server_;
  std::optional<Handle> active_;
  ros::Subscriber odometry_;
  ros::Publisher readiness_;
  ros::WallTimer timer_;
  uint64_t boot_id_;
};
}
