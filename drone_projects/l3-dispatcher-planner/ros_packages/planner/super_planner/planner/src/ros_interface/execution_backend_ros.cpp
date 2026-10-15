#include "ros_interface/ros1/fsm_ros1.hpp"
namespace super_planner { namespace fsm {
void FsmRos1::initExecution() {
  planner_execution::Backend backend;
  backend.validate=[this](const planner_execution::Target& t)->std::string {
    if (cfg_.traj_start_trigger_en && waiting_traj_start_trigger_) return "wait_traj_start_trigger";
    if (!cfg_.timer_en) return "native_action_requires_timers";
    if (!t.look_forward && cfg_.yaw_mode == super_planner::fsm::Config::YAW_TO_VEL) return "explicit_yaw_unsupported_in_velocity_mode";
    if (t.yaw_mode!=0 || t.yaw_path!=0) return "yaw_policy_unsupported";
    return "";
  };
  backend.start=[this](const planner_execution::Target& t){ return startExecution(t); };
  backend.stop=[this](){ return stopExecution(); };
  execution_action_=std::make_unique<planner_execution::WaypointActionServer>(nh_,backend,execution_mutex_,false,cfg_.cmd_topic);

}
bool FsmRos1::startExecution(const planner_execution::Target& target) {
  latest_goal_=target; ++plan_count_;
  execution_holding_=false;
  std::vector<Vec3f> points;
  for (auto p:target.waypoints) points.emplace_back(p[0],p[1],p[2]);
  Quatf q(Eigen::AngleAxisd(target.yaw,Eigen::Vector3d::UnitZ()));
  return setGoalWindow(gi_.batch_id+1,points,q,target.yaw_mode,target.yaw_path,target.look_forward);
}
bool FsmRos1::stopExecution() {
  if (execution_action_ && execution_action_->motion_enabled()) execution_action_->output()->request_stop();
  if (!execution_holding_) {
    clear_navigation(); latest_goal_=planner_execution::Target{}; reset_requested_=false; yaw_only_traj_valid_=false;
    execution_holding_=true;
  }
  return execution_action_ && execution_action_->output()->holding();
}
}}
