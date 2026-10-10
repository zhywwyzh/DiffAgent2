#include <plan_manage/diff_replan_fsm.h>
namespace diff_planner {
bool DiffReplanFSM::startExecution(const planner_execution::Target& t) {
  execution_holding_=false; mandatory_stop_=false;
  wp_list_.clear(); wp_orig_idx_.clear();
  for (size_t i=0;i<t.waypoints.size();++i) {
    auto p=t.waypoints[i]; wp_list_.emplace_back(p[0],p[1],p[2]); wp_orig_idx_.push_back(i);
  }
  if (planner_manager_->grid_map_->getInflateOccupancy(wp_list_.back()) == -1) return false;
  ++wp_batch_id_; wp_window_size_=wp_list_.size(); wp_active_idx_=0;
  has_window_=true; wp_flow_active_=true; wp_plan_count_=0;
  if (!planNextWaypointWindow(wp_list_,false)) return false;
  last_target_change_time_=ros::Time::now().toSec(); have_trigger_=true;
  changeFSMExecState(GEN_NEW_TRAJ,"action_goal"); return true;
}
bool DiffReplanFSM::stopExecution() {
  if (execution_action_ && execution_action_->motion_enabled()) execution_action_->output()->request_stop();
  if (execution_holding_ && execution_action_) return execution_action_->output()->holding();
  execution_holding_=true; have_target_=false; have_trigger_=false; have_new_target_=false;
  catch_goal_=false; wp_flow_active_=false; has_window_=false;
  wp_list_.clear(); wp_orig_idx_.clear();
  if (!have_odom_) return false;
  const bool ok=callEmergencyStop(odom_pos_);
  changeFSMExecState(WAIT_TARGET,"action_stop"); return ok && (!execution_action_ || execution_action_->output()->holding());
}
}
