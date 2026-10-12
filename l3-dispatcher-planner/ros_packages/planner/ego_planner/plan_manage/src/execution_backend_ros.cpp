#include <plan_manage/ego_replan_fsm.h>
namespace ego_planner { namespace plan_manage {
void EGOReplanFSM::initExecution(ros::NodeHandle& nh) {
  planner_execution::Backend backend;
  backend.validate=[this](const planner_execution::Target& t) -> std::string {
    if (!have_odom_) return "odometry_unavailable";
    if (t.yaw_path != 0 || t.yaw_mode == 2) {
      const auto& p=t.waypoints.back();
      if (t.yaw_path!=1 || t.yaw_mode!=2 || t.look_forward || t.waypoints.size()!=1 ||
          (Eigen::Vector3d(p[0],p[1],p[2])-odom_pos_).norm()>wp_reach_radius_)
        return "panorama_requires_in_place_continuous_goal";
    }
    return "";
  };
  backend.start=[this](const planner_execution::Target& t){return startExecution(t);};
  backend.commit=[this](){ if (target_yaw_mode_!=2) PublishCanonicalTrajectory(); };
  backend.stop=[this](){return stopExecution();};
  execution_action_=std::make_unique<planner_execution::WaypointActionServer>(nh,backend,execution_mutex_);
  traj_server_.setCommandOutput(execution_action_->output());
  bool tracking_enabled=false;
  nh.param("tracking_enabled",tracking_enabled,false);
  if(tracking_enabled) {
    auto map=planner_manager_->map_->sml_;
    map->enableTrackingMap();
    elastic_tracker::MapReader reader=[map](){return map->readTrackingMap();};
    tracking_=std::make_unique<elastic_tracker::TrackingRos>(nh,std::move(reader),*execution_action_);
  }
  execution_action_->start();
}
}}
