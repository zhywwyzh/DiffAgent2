#include <plan_manage/diff_replan_fsm.h>
namespace diff_planner {
void DiffReplanFSM::initExecution(ros::NodeHandle& nh) {
  planner_execution::Backend backend;
  backend.validate=[this](const planner_execution::Target& t) -> std::string {
    if (!have_odom_) return "odometry_unavailable";
    if (t.goal_to_follower) return "follower_unsupported";
    if (!t.look_forward || t.yaw_mode!=0 || t.yaw_path!=0) return "yaw_control_unsupported";
    return "";
  };
  backend.start=[this](const planner_execution::Target& t){return startExecution(t);};
  backend.stop=[this](){return stopExecution();};
  execution_action_=std::make_unique<planner_execution::WaypointActionServer>(nh,backend,execution_mutex_,true);
  execution_action_->start();
}
}
