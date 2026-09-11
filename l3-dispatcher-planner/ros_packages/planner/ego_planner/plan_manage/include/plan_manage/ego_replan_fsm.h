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
#include <std_msgs/Int8.h>
#include <std_msgs/Int32.h>
#include <std_msgs/Bool.h>
#include <vector>
#include <visualization_msgs/Marker.h>
#include <geometry_msgs/Twist.h>

#include <optimizer/poly_traj_optimizer.h>
#include <plan_env/grid_map.h>
#include <geometry_msgs/PoseStamped.h>
#include <quadrotor_msgs/LocalGoalSet.h>
#include <quadrotor_msgs/PlannerResult.h>
#include <quadrotor_msgs/EgoStateTrigger.h>
#include <quadrotor_msgs/WaypointProgress.h>
#include <std_srvs/Trigger.h>
#include <plan_manage/planner_manager.h>
#include <traj_utils/PolyTraj.h>
#include <traj_utils/MINCOTraj.h>
#include <plan_manage/traj_server.h>

using std::vector;
namespace ego_planner {
namespace plan_manage {
/**
 * 12-state finite state machine for receding-horizon trajectory planning.
 *
 * Manages the planning lifecycle: initialization, target acquisition,
 * trajectory generation/replanning/execution, emergency stop, crash
 * recovery, and yaw handling. Drives EGOPlannerManager through the
 * reboundReplan pipeline based on odometry and goal triggers.
 */
class EGOReplanFSM {
public:
  EGOReplanFSM() {}
  ~EGOReplanFSM();

  /**
   * Initialize the FSM: set up ROS topics, timers, and sub-modules.
   *
   * @param[inout] nh  ROS node handle
   */
  void init(ros::NodeHandle& nh);
  inline ego_planner::plan_env::MapManager::Ptr getMapPtr() { return planner_manager_->map_; };

  EIGEN_MAKE_ALIGNED_OPERATOR_NEW

private:
  /* ---------- flag ---------- */
  enum FSM_EXEC_STATE {
    INIT,
    WAIT_TARGET,
    HANDLE_YAW,
    GEN_NEW_TRAJ,
    REPLAN_TRAJ,
    EXEC_TRAJ,
    EMERGENCY_STOP,
    SEQUENTIAL_START,
    CRASH_RECOVER,
    WAIT_YAW
  };
  enum TARGET_TYPE { MANUAL_TARGET = 1, EXPLORE_TARGET = 2, PRESET_TARGET = 3, REFENCE_PATH = 4 };
  struct PlanRetStatistic {
    PLAN_RET ret{PLAN_RET::SUCCESS};
    int times{0};
    int keep_failure_times{0};
    ros::Time start_time{ros::Time(0.0)};
    std::queue<std::pair<ros::Time, PLAN_RET>> failure_histroy;
    double succ_calc_time{0.0};

    void setRet(const PLAN_RET r, const double time = -1.0);
    std::string show(bool print = true);
  } plan_ret_stat_;
  struct YAW_CMD {
    double des_yaw;
    bool yaw_reach;
    ros::Time cmd_time;
  } yaw_cmd_;

  /* planning utils */
  EGOPlannerManager::Ptr planner_manager_;
  ego_planner::plan_manage::TrajServer traj_server_;

  /* parameters */
  int target_type_;         // 1: manual select, 2: hard code, 3: preset, 4: reference path
  double no_replan_thresh_; // no-replan distance threshold [m]
  double waypoints_[50][3];
  int waypoint_num_, wpt_id_;
  double emergency_time_;                    // emergency stop duration [s]
  double ego_state_trigger_pos_thresh_;      // state trigger position threshold [m]
  double ego_state_trigger_vel_thresh_;      // state trigger velocity threshold [m/s]
  double ego_state_trigger_acc_thresh_;      // state trigger acceleration threshold [m/s^2]
  double ego_state_trigger_yaw_rate_thresh_; // state trigger yaw rate threshold [rad/s]
  double ego_state_trigger_hold_time_;       // state trigger hold duration [s]
  bool flag_realworld_experiment_;
  bool enable_fail_safe_;
  bool enable_ground_height_measurement_;
  bool flag_escape_emergency_;
  bool flag_wait_crash_rec_;
  ros::Time crash_rec_start_time_;
  ros::Time last_density_eval_time_{ros::Time(0)};

  bool have_trigger_, have_target_, have_odom_, cur_traj_to_cur_target_, have_recv_pre_agent_, touch_goal_,
      mandatory_stop_;
  bool if_handle_yaw_{false};
  bool has_been_modified_;
  bool pending_goal_finish_trigger_;
  ros::Time goal_finish_stable_start_time_;
  FSM_EXEC_STATE exec_state_;

  Eigen::Vector3d start_pt_, start_vel_, start_acc_, start_jerk_; // start state [m], [m/s], [m/s^2], [m/s^3]
  Eigen::Vector3d glb_start_pt_, final_goal_;                     // goal state [m]
  Eigen::Vector3d odom_pos_, odom_vel_, odom_acc_,
      odom_omega_; // odometry: pos [m], vel [m/s], acc [m/s^2], omega [rad/s]
  Eigen::Vector3d last_odom_vel_;
  bool odom_acc_ready_{false};
  bool traj_server_yaw_synced_{false};
  ros::Time last_odom_stamp_{ros::Time(0)};
  double odom_yaw_; // odometry yaw [rad]
  Eigen::Quaterniond odom_q_;
  Eigen::Vector3d odom_euler_;
  std::vector<Eigen::Vector3d> wps_;
  quadrotor_msgs::PlannerResult planner_result_;

  // waypoint window state
  std::vector<Eigen::Vector3d> wp_list_;
  std::vector<int> wp_orig_idx_;
  int wp_active_idx_{0};
  int wp_window_size_{0};
  uint32_t wp_batch_id_{0};
  uint8_t wp_skipped_mask_{0};
  bool wp_window_active_{false};
  bool wp_batch_terminal_pending_{false};
  double wp_reach_radius_{0.3};
  double wp_passby_lateral_{2.0};
  double goal_reach_radius_{0.3};
  /* Window-threaded planning: the window points the committed trajectory is
   * planned through (via points) in travel order; empty means the window is
   * being executed per-point (legacy fallback). */
  std::vector<Eigen::Vector3d> wp_chain_;

  // handle yaw
  Eigen::Vector3d target_pos_; // target position [m]
  double target_yaw_;          // target yaw [rad]
  bool target_look_forward_;
  uint8_t target_yaw_mode_;
  uint8_t target_yaw_path_mode_;
  void handleYaw();
  double aim_direction_; // yaw aim direction [rad]
  bool yaw_init_finished_{false};

  /* ROS utils */
  ros::NodeHandle node_;
  ros::Timer exec_timer_, safety_timer_;
  ros::Subscriber waypoint_sub_, waypoint_sub_yaw_preset_sub_, odom_sub_, if_handle_yaw_sub_, trigger_sub_,
      broadcast_ploytraj_sub_, mandatory_stop_sub_;
  ros::ServiceServer reset_srv_; /* Planner Reset Contract: /planner/reset */
  ros::Publisher broadcast_ploytraj_pub_, ground_height_pub_, state_pub_, exec_finish_trigger_pub_,
      ego_state_trigger_pub_;
  ros::Publisher planner_result_pub_;
  ros::Publisher wp_progress_pub_;
  /* Canonical trajectory topics (ground-station-channels.spec.md §2.5):
   * /drone_<id>/planner/search_path + /drone_<id>/planner/optimized_traj,
   * remapped to absolute names at launch. Published at every successful
   * replan together with the existing MINCOTraj broadcast. */
  ros::Publisher search_path_pub_, optimized_traj_pub_;
  /* Window debugging visualization (rviz): current window points +
   * threaded initial path. */
  ros::Publisher window_points_pub_, init_path_pub_;

  /* state machine functions */
  /**
   * Main FSM execution callback triggered by ROS timer at ~10-20 Hz.
   *
   * @param[in] e  Timer event
   */
  void execFSMCallback(const ros::TimerEvent& e);
  /**
   * Transition the FSM to a new execution state.
   *
   * @param[in] new_state  Target FSM state
   * @param[in] pos_call   Call site identifier for logging
   */
  void changeFSMExecState(FSM_EXEC_STATE new_state, std::string pos_call);
  void printFSMExecState() const;
  void planningReturnsChk();
  void evaluateEnvironmentDensity();

  /* safety */
  void checkCollision();
  /**
   * Execute emergency stop at a given position.
   *
   * @param[in] stop_pos  Braking position [m]
   * @return True if emergency stop trajectory generated
   */
  bool callEmergencyStop(Eigen::Vector3d stop_pos);
  bool callCrashRecovery();

  /* local planning */
  /**
   * Call the main rebound replanning pipeline.
   *
   * @param[in] flag_use_last_optimal  Use last optimal trajectory as init
   * @param[in] flag_random_init       Randomize initial control points
   * @param[out] pathes                Density evaluation ray data (optional)
   * @return Plan result (SUCCESS / LOCAL_TGT_FAIL / INIT_FAIL / DEFAULT_FAIL)
   */
  PLAN_RET callReboundReplan(bool flag_use_last_optimal, bool flag_random_init,
                             std::vector<DensityEvalRayData>* pathes);
  /**
   * Plan trajectory from the current global reference trajectory.
   *
   * @param[in] trial_times  Number of retry attempts [--]
   * @return True if planning succeeded
   */
  bool planFromGlobalTraj(const int trial_times = 1);
  /**
   * Plan trajectory from local start to local target.
   *
   * @param[in] trial_times  Number of retry attempts [--]
   * @return True if planning succeeded
   */
  bool planFromLocalTraj(const int trial_times = 1);
  bool getTrajPVAJ(const std::string data_source);
  void execTraj();

  /* global trajectory */
  void waypointCallback(const geometry_msgs::PoseStampedPtr& msg);
  void aimCallback(const quadrotor_msgs::LocalGoalSetPtr& msg);
  void aimCallbackYawPreset(const quadrotor_msgs::LocalGoalSetPtr& msg);
  void execAim();
  void readGivenWpsAndPlan();
  /**
   * Plan trajectory to the next waypoint.
   *
   * @param[in] next_wp       Next waypoint position [m]
   * @param[in] next_yaw      Next waypoint yaw [rad]
   * @param[in] look_forward  Enable look-forward yaw
   * @param[in] yaw_mode      Yaw control mode
   * @param[in] yaw_path_mode Yaw path mode
   * @return True if planning succeeded
   */
  bool planNextWaypoint(const Eigen::Vector3d next_wp, const double next_yaw = 0.0, const bool look_forward = true,
                        uint8_t yaw_mode = quadrotor_msgs::LocalGoalSet::YAW_MODE_NORMAL,
                        uint8_t yaw_path_mode = quadrotor_msgs::LocalGoalSet::YAW_PATH_SHORTEST,
                        bool enable_pre_yaw = true);
  bool mondifyInCollisionFinalGoal();
  /**
   * Set the waypoint window from a batch of raw waypoints.
   *
   * Preserves free seed waypoints, repairs occupied intermediate seeds onto a
   * safe execution point, and initiates planning to the first valid waypoint.
   *
   * @param[in] batch_id        Monotonic batch identifier
   * @param[in] raw_wps         Raw waypoint positions (up to 3) [m]
   * @param[in] yaw             Target yaw [rad]
   * @param[in] look_forward    Enable look-forward yaw
   * @param[in] yaw_mode        Yaw control mode
   * @param[in] yaw_path_mode   Yaw path mode
   * @return True if at least one valid waypoint was set
   */
  bool setGoalWindow(uint32_t batch_id, const std::vector<Eigen::Vector3d>& raw_wps, double yaw, bool look_forward,
                     uint8_t yaw_mode, uint8_t yaw_path_mode);
  /**
   * Seamlessly extend the active waypoint queue with a new window.
   *
   * When the mission slides the window just-in-time, the new window's first
   * waypoint is the planner's current active waypoint. Instead of replacing
   * the window (which replans the whole trajectory from scratch and yanks the
   * drone toward a fresh goal mid-flight), merge the new points into the
   * existing queue, rebase the batch identity, and keep the committed
   * trajectory untouched.
   *
   * @param[in] batch_id  New monotonic batch identifier
   * @param[in] raw_wps   New window waypoints (mission-side coordinates)
   * @return True if the window was merged; false means the new window is not
   *         geometrically continuous and the caller falls back to setGoalWindow
   */
  bool mergeGoalWindow(uint32_t batch_id, const std::vector<Eigen::Vector3d>& raw_wps);
  /**
   * Replan the window-threaded trajectory toward the current window end.
   *
   * Called after setGoalWindow / mergeGoalWindow when the committed
   * trajectory terminal lags the window end; the new trajectory threads the
   * whole window (via points) and only the window-final waypoint decelerates.
   *
   * @return True if a plan was issued
   */
  bool threadWindowTrajectory();
  /**
   * Publish the current window points + threaded initial path for RViz.
   */
  void publishWindowVisualization();
  /**
   * Consume the current active waypoint and advance or close the window.
   *
   * @param[in] all_consumed  True if the batch is fully consumed
   */
  void consumeWaypoint(bool all_consumed);
  /**
   * Publish WaypointProgress to the upper layer (MissionFSM).
   *
   * @param[in] all_consumed  True if the batch is complete
   */
  void publishWaypointProgress(bool all_consumed) const;
  /**
   * Check if the robot has passed through the current active waypoint
   * by crossing its perpendicular plane with lateral tolerance.
   *
   * @param[in] pos  Current robot position [m]
   * @return True if the waypoint was passed by
   */
  bool checkWaypointPassby(const Eigen::Vector3d& pos) const;

  /* input-output */
  void mandatoryStopCallback(const std_msgs::Empty& msg);
  void ifHandleYawCallback(const std_msgs::BoolConstPtr& msg);
  bool resetServiceCallback(std_srvs::Trigger::Request& req, std_srvs::Trigger::Response& res);
  void odometryCallback(const nav_msgs::OdometryConstPtr& msg);
  void triggerCallback(const geometry_msgs::PoseStampedPtr& msg);
  void RecvBroadcastMINCOTrajCallback(const traj_utils::MINCOTrajConstPtr& msg);
  void polyTraj2ROSMsg(traj_utils::PolyTraj* poly_msg, traj_utils::MINCOTraj* MINCO_msg);
  void PublishCanonicalTrajectory();

  /* utils */
  void initPlannerResult();
  void updatePlannerResult(const Eigen::Vector3d goal, PLAN_RET status);

  /* ground height measurement */
  bool measureGroundHeight() const;
  bool measureGroundHeight2();
};

} // namespace plan_manage
} // namespace ego_planner

#endif
