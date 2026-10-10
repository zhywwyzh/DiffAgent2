#include <plan_manage/ego_replan_fsm.h>
namespace ego_planner { namespace plan_manage {
bool EGOReplanFSM::startExecution(const planner_execution::Target& t) {
  execution_holding_=false; mandatory_stop_=false;
  initPlannerResult();
  std::vector<Eigen::Vector3d> points;
  for (auto p:t.waypoints) points.emplace_back(p[0],p[1],p[2]);
  target_pos_=points.back(); target_yaw_=t.yaw; target_look_forward_=t.look_forward;
  target_yaw_mode_=t.yaw_mode; target_yaw_path_mode_=t.yaw_path;
  if (t.yaw_mode==2) {
    wp_window_size_=1; wp_active_idx_=0; wp_skipped_mask_=0;
    wp_window_active_=true; wp_batch_terminal_pending_=true;
    wp_list_=points; wp_orig_idx_={0}; wp_chain_.clear();
    final_goal_=points.back(); have_target_=true; have_trigger_=true;
    yaw_cmd_.yaw_reach=false; yaw_cmd_.des_yaw=t.yaw; yaw_cmd_.cmd_time=ros::Time::now();
    traj_server_.reset(); traj_server_.syncYawFromOdom(odom_yaw_,"action_panorama");
    traj_server_.setPanoramaYaw(t.yaw,odom_yaw_,points.back());
    changeFSMExecState(WAIT_YAW,"action_panorama"); return true;
  }
  const bool ok=setGoalWindow(++wp_batch_id_,points,t.yaw,t.look_forward,t.yaw_mode,t.yaw_path);
  if (ok && wp_window_active_) have_trigger_=true;
  return ok;
}
bool EGOReplanFSM::stopExecution() {
  if (execution_action_ && execution_action_->motion_enabled()) execution_action_->output()->request_stop();
  if (execution_holding_ && execution_action_) return execution_action_->output()->holding();
  execution_holding_=true; have_target_=false; have_trigger_=false;
  pending_goal_finish_trigger_=false; touch_goal_=false;
  wp_window_active_=false; wp_batch_terminal_pending_=false;
  wp_chain_.clear(); wp_list_.clear(); wp_orig_idx_.clear(); wp_skipped_mask_=0;
  traj_server_.reset(); traj_server_.syncYawFromOdom(odom_yaw_,"action_stop");
  if (!have_odom_) return false;
  const bool ok=callEmergencyStop(odom_pos_);
  changeFSMExecState(WAIT_TARGET,"action_stop"); return ok && (!execution_action_ || execution_action_->output()->holding());
}
}}
