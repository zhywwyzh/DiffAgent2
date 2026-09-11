#ifndef _REBO_REPLAN_FSM_H_
#define _REBO_REPLAN_FSM_H_

#include <Eigen/Eigen>
#include <algorithm>
#include <iostream>
#include <nav_msgs/Path.h>
#include <sensor_msgs/Imu.h>
#include <ros/ros.h>
#include <quadrotor_msgs/PiecewisePolynomial.h>
#include <std_msgs/Empty.h>
#include <std_msgs/Float64.h>
#include <std_srvs/Trigger.h>
#include <std_msgs/UInt8.h>
#include <vector>
#include <visualization_msgs/Marker.h>

#include <optimizer/poly_traj_optimizer.h>
#include <plan_env/grid_map.h>
#include <geometry_msgs/PoseStamped.h>
#include <plan_manage/planner_manager.h>
#include <quadrotor_msgs/LocalGoalSet.h>
#include <quadrotor_msgs/PlannerResult.h>
#include <quadrotor_msgs/WaypointProgress.h>
#include <std_msgs/Bool.h>
#include <traj_utils/planning_visualization.h>
#include <traj_utils/PolyTraj.h>
#include <traj_utils/MINCOTraj.h>

using std::vector;

namespace diff_planner {

class DiffReplanFSM {
public:
  DiffReplanFSM() {}
  ~DiffReplanFSM() {}

  void init(ros::NodeHandle& nh);

  EIGEN_MAKE_ALIGNED_OPERATOR_NEW

private:
  /* ---------- flag ---------- */
  enum FSM_EXEC_STATE { INIT, WAIT_TARGET, GEN_NEW_TRAJ, REPLAN_TRAJ, EXEC_TRAJ, EMERGENCY_STOP, SEQUENTIAL_START };
  enum TARGET_TYPE { MANUAL_TARGET = 1, PRESET_TARGET = 2, REFENCE_PATH = 3 };
  /* Anomaly Detection Parameters */
  Eigen::Vector3d last_local_target_pos_;
  double last_target_change_time_;
  double last_near_unknown_box_update_time_;
  int replan_fail_count_;
  static constexpr double TARGET_STUCK_THRESH =
      0.3;                  // Threshold for target movement below which it's considered "stuck"
  double TARGET_STUCK_TIME; // Default time threshold (seconds) for being considered stuck before reinitialization
  static constexpr int MAX_REPLAN_FAIL_COUNT = 10; // Threshold for maximum optimization failure count
  /* planning utils */
  DiffPlannerManager::Ptr planner_manager_;
  PlanningVisualization::Ptr visualization_;

  /* parameters */
  int target_type_; // 1 mannual select, 2 hard code
  double no_replan_thresh_, replan_thresh_;
  double waypoints_[50][3];
  int waypoint_num_, wpt_id_;
  double planning_horizon_;
  double emergency_time_;
  bool flag_realworld_experiment_;
  bool enable_fail_safe_;
  bool enable_ground_height_measurement_;
  bool flag_escape_emergency_;
  bool need_hover_stop_;
  bool mondify_final_goal_;
  bool enable_stuck_detect_; // Whether to enable stuck detection

  bool have_trigger_, have_target_, have_odom_, have_new_target_, have_recv_pre_agent_, catch_goal_, mandatory_stop_;
  bool first_plan_unknown_inf_cleared_{false};
  FSM_EXEC_STATE exec_state_;
  int continously_called_times_{0};

  Eigen::Vector3d start_pt_, start_vel_, start_acc_;   // start state
  Eigen::Vector3d final_goal_;                         // goal state
  Eigen::Vector3d local_target_pt_, local_target_vel_; // local target state
  Eigen::Vector3d odom_pos_, odom_vel_, odom_acc_;     // odometry state
  std::vector<Eigen::Vector3d> wps_;

  /* Waypoint window (LocalGoalSet batch protocol, mirrors SUPER semantics).
   * The global traj is planned through every window waypoint, so intermediate
   * waypoints are flown through at the min-jerk speed profile and only the
   * window end is decelerated to rest. */
  std::vector<Eigen::Vector3d> wp_list_; // active window after front-erase
  std::vector<int> wp_orig_idx_;         // wp_list_ index -> original window index
  int wp_active_idx_{0};
  int wp_window_size_{0};
  uint32_t wp_batch_id_{0};
  bool has_window_{false};
  bool wp_flow_active_{false}; // current goal came from LocalGoalSet (mission batch flow)
  int16_t wp_plan_count_{0};   // plan attempts for the current batch
  double wp_reach_radius_, wp_passby_lateral_, goal_reach_radius_;

  /* ROS utils */
  ros::NodeHandle node_;
  ros::Timer exec_timer_, safety_timer_;
  ros::Subscriber waypoint_sub_, odom_sub_, trigger_sub_, broadcast_ploytraj_sub_, mandatory_stop_sub_;
  ros::ServiceServer reset_srv_; /* Planner Reset Contract: /planner/reset */
  ros::Publisher poly_traj_pub_, broadcast_ploytraj_pub_, heartbeat_pub_, ground_height_pub_, fsm_state_pub_,
      wp_progress_pub_;
  ros::Publisher plan_result_pub_, exec_finish_pub_;
  /* Canonical trajectory topics (ground-station-channels.spec.md §2.5):
   * /drone_<id>/planner/search_path + /drone_<id>/planner/optimized_traj,
   * remapped to absolute names at launch. Published at every successful
   * replan together with the existing PolyTraj/MINCOTraj broadcast. */
  ros::Publisher search_path_pub_, optimized_traj_pub_;

  /* state machine functions */
  void execFSMCallback(const ros::TimerEvent& e);
  void changeFSMExecState(FSM_EXEC_STATE new_state, string pos_call);
  void printFSMExecState();
  std::pair<int, DiffReplanFSM::FSM_EXEC_STATE> timesOfConsecutiveStateCalls();

  /* safety */
  void checkCollisionCallback(const ros::TimerEvent& e);
  bool callEmergencyStop(Eigen::Vector3d stop_pos);

  /* local planning */
  bool callReboundReplan(bool flag_use_poly_init, bool flag_randomPolyTraj);
  bool planFromGlobalTraj(const int trial_times = 1);
  bool planFromLocalTraj(const int trial_times = 1);

  /* global trajectory */
  void waypointCallback(const quadrotor_msgs::LocalGoalSetConstPtr& msg);
  void readGivenWpsAndPlan();
  bool planNextWaypoint(const Eigen::Vector3d next_wp, bool flag_2replan);
  bool planNextWaypointWindow(const std::vector<Eigen::Vector3d>& window, bool flag_2replan);
  bool mondifyInCollisionFinalGoal();
  void finishProcess();

  /* waypoint window progress (reach / pass-by consumption + WaypointProgress) */
  void updateWaypointProgress();
  void publishWaypointProgress(bool all_consumed);

  /* PlannerResult feedback (ack / unreachable / exec_finished at batch boundary) */
  void publishPlannerResult(const Eigen::Vector3d& goal, bool plan_status, bool modify_status, bool exec_finished);

  /* input-output */
  void mandatoryStopCallback(const std_msgs::Empty& msg);
  bool resetServiceCallback(std_srvs::Trigger::Request& req, std_srvs::Trigger::Response& res);
  void odometryCallback(const nav_msgs::OdometryConstPtr& msg);
  void triggerCallback(const geometry_msgs::PoseStampedPtr& msg);
  void RecvBroadcastMINCOTrajCallback(const traj_utils::MINCOTrajConstPtr& msg);
  void polyTraj2ROSMsg(traj_utils::PolyTraj& poly_msg, traj_utils::MINCOTraj& MINCO_msg);
  void PublishCanonicalTrajectory();

  /* ground height measurement */
  bool measureGroundHeight(double& height);
  Eigen::Vector3d projectPointToLineSegment(const Eigen::Vector3d& a, const Eigen::Vector3d& b,
                                            const Eigen::Vector3d& p);
};

} // namespace diff_planner

#endif