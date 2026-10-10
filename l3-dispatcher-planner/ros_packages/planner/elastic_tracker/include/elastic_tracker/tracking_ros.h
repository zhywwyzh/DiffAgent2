#pragma once
#include <elastic_tracker/tracking.h>
#include <planner_execution/action_server_ros.h>
#include <sensor_msgs/Image.h>
#include <nav_msgs/Odometry.h>
#include <ros/ros.h>
#include <atomic>
namespace elastic_tracker {
class TrackingRos {
 public:
  TrackingRos(ros::NodeHandle nh, MapPort map, planner_execution::WaypointActionServer& execution);
  ~TrackingRos();
  void shutdown();
 private:
  void pose(const nav_msgs::OdometryConstPtr& msg);
  void depth(const sensor_msgs::ImageConstPtr& msg);
  void sample(const ros::WallTimerEvent&);
  ros::CallbackQueue queue_;
  ros::NodeHandle nh_;
  std::unique_ptr<ros::AsyncSpinner> spinner_;
  std::unique_ptr<Tracking> tracking_;
  planner_execution::WaypointActionServer& execution_;
  std::shared_ptr<planner_execution::CommandOutput> output_;
  ros::Subscriber pose_, depth_;
  ros::WallTimer timer_;
  std::atomic<bool> running_{false};
  std::string frame_;
};
}
