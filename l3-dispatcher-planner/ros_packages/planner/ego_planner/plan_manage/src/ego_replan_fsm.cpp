
#include <plan_manage/ego_replan_fsm.h>
#include <quadrotor_msgs/piecewise_from_poly.hpp>
#include <std_msgs/Bool.h>
#include <tf/tf.h>
#include <visualization_msgs/Marker.h>
#include <visualization_msgs/MarkerArray.h>
#include <cmath>

using namespace std;
namespace ego_planner {
namespace plan_manage {
using namespace ego_planner::traj_opt;
using namespace ego_planner::plan_env;
namespace {
const char* planRetName(const PLAN_RET ret) {
  switch (ret) {
  case PLAN_RET::SUCCESS:
    return "SUCCESS";
  case PLAN_RET::LOCAL_TGT_FAIL:
    return "LOCAL_TGT_FAIL";
  case PLAN_RET::INIT_FAIL:
    return "INIT_FAIL";
  case PLAN_RET::DEFAULT_FAIL:
    return "DEFAULT_FAIL";
  default:
    return "UNKNOWN";
  }
}
} // namespace

void ego_planner::plan_manage::EGOReplanFSM::init(ros::NodeHandle& nh) {
  exec_state_ = FSM_EXEC_STATE::INIT;
  have_target_ = false;
  have_odom_ = false;
  have_recv_pre_agent_ = false;
  flag_escape_emergency_ = true;
  flag_wait_crash_rec_ = false;
  mandatory_stop_ = false;
  cur_traj_to_cur_target_ = false;
  has_been_modified_ = false;
  if_handle_yaw_ = true;

  pending_goal_finish_trigger_ = false;
  goal_finish_stable_start_time_ = ros::Time(0);
  /*  fsm param  */
  nh.param("fsm/flight_type", target_type_, -1); // target_type_==2
  nh.param("fsm/emergency_time", emergency_time_, 1.0);
  nh.param("fsm/realworld_experiment", flag_realworld_experiment_, false);
  nh.param("fsm/fail_safe", enable_fail_safe_, true);
  nh.param("fsm/ground_height_measurement", enable_ground_height_measurement_, false);
  nh.param("fsm/ego_state_trigger_pos_thresh", ego_state_trigger_pos_thresh_, 0.30);
  nh.param("fsm/ego_state_trigger_vel_thresh", ego_state_trigger_vel_thresh_, 0.15);
  nh.param("fsm/ego_state_trigger_acc_thresh", ego_state_trigger_acc_thresh_, 0.30);
  nh.param("fsm/ego_state_trigger_yaw_rate_thresh", ego_state_trigger_yaw_rate_thresh_, 0.20);
  nh.param("fsm/ego_state_trigger_hold_time", ego_state_trigger_hold_time_, 0.20);

  nh.param("fsm/wp_reach_radius", wp_reach_radius_, 0.3);
  nh.param("fsm/wp_passby_lateral", wp_passby_lateral_, 2.0);
  nh.param("fsm/goal_reach_radius", goal_reach_radius_, 0.3);

  nh.param("fsm/waypoint_num", waypoint_num_, -1);
  for (int i = 0; i < waypoint_num_; i++) {
    nh.param("fsm/waypoint" + to_string(i) + "_x", waypoints_[i][0], -1.0);
    nh.param("fsm/waypoint" + to_string(i) + "_y", waypoints_[i][1], -1.0);
    nh.param("fsm/waypoint" + to_string(i) + "_z", waypoints_[i][2], -1.0);
  }

  /* initialize main modules */
  planner_manager_.reset(new EGOPlannerManager);
  planner_manager_->initPlanModules(nh);
  traj_server_.initTrajServer(nh);

  have_trigger_ = !flag_realworld_experiment_;
  // no_replan_thresh_ = 0.5 * emergency_time_ * planner_manager_->pp_.max_vel_;
  no_replan_thresh_ = 0.5;
  odom_acc_.setZero();
  last_odom_vel_.setZero();
  odom_acc_ready_ = false;
  traj_server_yaw_synced_ = false;
  last_odom_stamp_ = ros::Time(0);

  initPlannerResult();

  /* callback */
  exec_timer_ = nh.createTimer(ros::Duration(0.01), &ego_planner::plan_manage::EGOReplanFSM::execFSMCallback, this);

  odom_sub_ = nh.subscribe("odom_world", 50, &ego_planner::plan_manage::EGOReplanFSM::odometryCallback, this);
  mandatory_stop_sub_ =
      nh.subscribe("mandatory_stop", 10, &ego_planner::plan_manage::EGOReplanFSM::mandatoryStopCallback, this);
  if_handle_yaw_sub_ =
      nh.subscribe("if_handle_yaw", 10, &ego_planner::plan_manage::EGOReplanFSM::ifHandleYawCallback, this);

  /* Planner Reset Contract (std_srvs/Trigger, fixed name shared by every
   * backend since they run mutually exclusively). */
  reset_srv_ =
      nh.advertiseService("/planner/reset", &ego_planner::plan_manage::EGOReplanFSM::resetServiceCallback, this);

  /* Use MINCO trajectory to minimize the message size in wireless communication */
  broadcast_ploytraj_pub_ = nh.advertise<traj_utils::MINCOTraj>("planning/broadcast_traj_send", 10);
  broadcast_ploytraj_sub_ = nh.subscribe<traj_utils::MINCOTraj>(
      "planning/broadcast_traj_recv", 100, &ego_planner::plan_manage::EGOReplanFSM::RecvBroadcastMINCOTrajCallback,
      this, ros::TransportHints().tcpNoDelay());
  search_path_pub_ = nh.advertise<nav_msgs::Path>("planner/search_path", 10);
  optimized_traj_pub_ = nh.advertise<quadrotor_msgs::PiecewisePolynomial>("planner/optimized_traj", 10);
  window_points_pub_ = nh.advertise<visualization_msgs::MarkerArray>("planner/window_points", 10);
  init_path_pub_ = nh.advertise<nav_msgs::Path>("planner/init_path", 10);

  ground_height_pub_ = nh.advertise<std_msgs::Float64>("/ground_height_measurement", 10);
  state_pub_ = nh.advertise<std_msgs::Int8>("state", 10);
  exec_finish_trigger_pub_ = nh.advertise<std_msgs::Bool>("exec_finish_trigger", 10);
  planner_result_pub_ = nh.advertise<quadrotor_msgs::PlannerResult>("/planning/planner_result", 10);
  ego_state_trigger_pub_ = nh.advertise<quadrotor_msgs::EgoStateTrigger>("/planning/ego_state_trigger", 10);
  wp_progress_pub_ = nh.advertise<quadrotor_msgs::WaypointProgress>("/drone_0_ego_planner_node/waypoint_progress", 10);

  // ROS_INFO("Wait for 3 seconds.");
  // ros::Time t0 = ros::Time::now();
  while (ros::ok()) {
    ros::spinOnce();
    ros::Duration(0.001).sleep();
    if (have_odom_) // following functions use odom_pos_
      break;
  }

  if (target_type_ == TARGET_TYPE::MANUAL_TARGET) {
    // waypoint_sub_ = nh.subscribe("/goal", 1, &ego_planner::plan_manage::EGOReplanFSM::waypointCallback, this);
  } else if (target_type_ == TARGET_TYPE::EXPLORE_TARGET) {
    waypoint_sub_ = nh.subscribe("local_goal", 10, &ego_planner::plan_manage::EGOReplanFSM::aimCallback, this);
    waypoint_sub_yaw_preset_sub_ =
        nh.subscribe("local_goal_yaw_preset", 10, &ego_planner::plan_manage::EGOReplanFSM::aimCallbackYawPreset, this);
  } else if (target_type_ == TARGET_TYPE::PRESET_TARGET) {
    trigger_sub_ =
        nh.subscribe("/traj_start_trigger", 1, &ego_planner::plan_manage::EGOReplanFSM::triggerCallback, this);
    readGivenWpsAndPlan();
  } else
    cout << "Wrong target_type_ value! target_type_=" << target_type_ << endl;

  ROS_INFO("Planner started.");
}

void ego_planner::plan_manage::EGOReplanFSM::execFSMCallback(const ros::TimerEvent& e) {
  exec_timer_.stop(); // To avoid blockage, because execFSMCallback will call ros::spinOnce() inside
  traj_server_.feedDog();
  // measureGroundHeight();
  // measureGroundHeight2();
  mondifyInCollisionFinalGoal();
  checkCollision();
  planningReturnsChk();
  evaluateEnvironmentDensity();

  static int fsm_num = 0;
  fsm_num++;
  if (fsm_num == 500) {
    fsm_num = 0;
    printFSMExecState();
  }

  switch (exec_state_) {
  case INIT: {
    if (!have_odom_) {
      goto force_return; // return;
    }
    changeFSMExecState(WAIT_TARGET, "EGOFSM");
    break;
  }

  case WAIT_TARGET: {
    if (pending_goal_finish_trigger_) {
      bool stable_now = false;
      if (have_odom_) {
        const double goal_dist = (final_goal_ - odom_pos_).norm();
        const double vel_norm = odom_vel_.norm();
        const double acc_norm = odom_acc_.norm();
        const double yaw_rate_abs = std::abs(odom_omega_(2));
        stable_now = goal_dist <= ego_state_trigger_pos_thresh_ && vel_norm <= ego_state_trigger_vel_thresh_ &&
                     acc_norm <= ego_state_trigger_acc_thresh_ && yaw_rate_abs <= ego_state_trigger_yaw_rate_thresh_;
      }

      if (stable_now) {
        if (goal_finish_stable_start_time_.isZero())
          goal_finish_stable_start_time_ = ros::Time::now();

        if ((ros::Time::now() - goal_finish_stable_start_time_).toSec() >= ego_state_trigger_hold_time_) {
          quadrotor_msgs::EgoStateTrigger trigger_msg;
          trigger_msg.header.stamp = ros::Time::now();
          trigger_msg.data = true;
          ego_state_trigger_pub_.publish(trigger_msg);
          pending_goal_finish_trigger_ = false;
          goal_finish_stable_start_time_ = ros::Time(0);
        }
      } else {
        goal_finish_stable_start_time_ = ros::Time(0);
      }
    }

    if (!have_target_ || !have_trigger_ || !yaw_cmd_.yaw_reach)
      goto force_return; // return;
    else {
      changeFSMExecState(SEQUENTIAL_START, "EGOFSM");
    }
    break;
  }

  case HANDLE_YAW: {
    execAim();
    break;
  }

  case SEQUENTIAL_START: // for swarm or single drone with drone_id = 0
  {
    if (planner_manager_->pp_.drone_id <= 0 || (planner_manager_->pp_.drone_id >= 1 && have_recv_pre_agent_)) {
      bool success = planFromGlobalTraj(10); // zx-todo
      if (success) {
        changeFSMExecState(EXEC_TRAJ, "EGOFSM");
      } else {
        ROS_WARN("Failed to generate the first trajectory, keep trying");
        changeFSMExecState(SEQUENTIAL_START, "EGOFSM"); // "changeFSMExecState" must be called each time planned
      }
    }

    break;
  }

  case GEN_NEW_TRAJ: {
    bool success = planFromGlobalTraj(10); // zx-todo
    ROS_WARN("GEN_NEW_TRAJ!: %d", success);

    if (success) {
      changeFSMExecState(EXEC_TRAJ, "EGOFSM");
      flag_escape_emergency_ = true;
    } else {
      changeFSMExecState(GEN_NEW_TRAJ, "EGOFSM"); // "changeFSMExecState" must be called each time planned
    }
    break;
  }

  case REPLAN_TRAJ: {

    if (planFromLocalTraj(1)) {
      changeFSMExecState(EXEC_TRAJ, "EGOFSM");
    } else {
      // changeFSMExecState(REPLAN_TRAJ, "FSM");
      changeFSMExecState(GEN_NEW_TRAJ, "EGOFSM");
    }

    break;
  }

  case EXEC_TRAJ: {
    if (traj_server_.preYawActive())
      break;

    /* determine if need to replan */
    LocalTrajData* info = &planner_manager_->traj_.local_traj;
    if (traj_server_.consumePreYawCompletedEvent())
      info->start_time = ros::Time::now().toSec();
    double t_cur = ros::Time::now().toSec() - info->start_time;
    t_cur = min(info->duration, t_cur);
    Eigen::Vector3d pos = info->traj.getPos(t_cur);
    // bool touch_the_goal = ((local_target_pt_ - final_goal_).norm() < 0.01);

    constexpr double EXEC_PROPORTION = 0.5;
    bool close_to_current_traj_end = t_cur > info->last_opt_cp_time * EXEC_PROPORTION;
    bool close_to_final_goal = (final_goal_ - pos).norm() < no_replan_thresh_;

    // cout << setprecision(3) << " EX" << t0_dbg.toc(false) << flush;

    // bool close_to_current_traj_end = (chk_ptr->size() >= 1 && chk_ptr->back().size() >= 1) ?
    // chk_ptr->back().back().first - t_cur < emergency_time_ : 0; // In case of empty vector

    // cout << "t_cur=" << t_cur << " info->duration=" << info->duration
    //      << " final_goal_=" << final_goal_.transpose() << " pos=" << pos.transpose()
    //      << " local_target_pt_=" << local_target_pt_.transpose() << endl;
    if (wp_window_active_ && wp_active_idx_ < static_cast<int>(wp_list_.size()) - 1) {
      // Intermediate waypoint consumption (reach or pass-by).
      const double dist_to_wp = (wp_list_[wp_active_idx_] - pos).norm();
      bool consumed = dist_to_wp < wp_reach_radius_ || checkWaypointPassby(pos);
      if (consumed) {
        ROS_INFO_STREAM("[EGOPlanner] ego_wp_consumed batch_id=" << wp_batch_id_ << " active_idx=" << wp_active_idx_
                                                                 << " wp=" << wp_list_[wp_active_idx_].transpose()
                                                                 << " dist=" << dist_to_wp
                                                                 << " total_wps=" << wp_list_.size());
        consumeWaypoint(false);
        /* Window-threaded mode: the committed trajectory already threads the
         * whole window, so advancing the active index needs no replan (no
         * stop-and-restart at intermediate waypoints). Fall back to per-point
         * replanning when the window was not threaded (wp_chain_ empty). */
        if (wp_chain_.empty()) {
          planNextWaypoint(wp_list_[wp_active_idx_], target_yaw_, target_look_forward_, target_yaw_mode_,
                           target_yaw_path_mode_, false);
        }
      }
    }

    const bool has_intermediate_waypoint = wp_window_active_ && wp_active_idx_ < static_cast<int>(wp_list_.size()) - 1;
    if ((target_type_ == TARGET_TYPE::PRESET_TARGET) && (wpt_id_ < waypoint_num_ - 1) &&
        close_to_final_goal) // case 2: assign the next waypoint
    {
      wpt_id_++;
      planNextWaypoint(wps_[wpt_id_]);
    } else if (!has_intermediate_waypoint && t_cur > info->duration - 1e-2) // case 3: the final waypoint reached
    {
      if (wp_batch_terminal_pending_) {
        // Waypoint window final waypoint reached.
        have_target_ = false;
        have_trigger_ = false;
        pending_goal_finish_trigger_ = true;
        goal_finish_stable_start_time_ = ros::Time(0);
        consumeWaypoint(true);
        changeFSMExecState(WAIT_TARGET, "EGOFSM");
      } else if (touch_goal_) {
        have_target_ = false;
        have_trigger_ = false;
        pending_goal_finish_trigger_ = true;
        goal_finish_stable_start_time_ = ros::Time(0);

        if (target_type_ == TARGET_TYPE::PRESET_TARGET) {
          // prepare for next round
          wpt_id_ = 0;
          planNextWaypoint(wps_[wpt_id_]);
        }

        /* The navigation task completed */
        changeFSMExecState(WAIT_TARGET, "EGOFSM");
      } else {
        ROS_ERROR("t_cur > info->duration but touch_goal_ is false! ERROR");
        pending_goal_finish_trigger_ = false;
        goal_finish_stable_start_time_ = ros::Time(0);
        changeFSMExecState(WAIT_TARGET, "EGOFSM"); // no better choises
      }
    } else if (!touch_goal_ && close_to_current_traj_end && !close_to_final_goal) // case 3: time to perform next replan
    {
      cout << "case2=" << (!touch_goal_ && close_to_current_traj_end) << " CASE3=" << (final_goal_ - pos).norm()
           << endl;
      changeFSMExecState(REPLAN_TRAJ, "EGOFSM");
    } else if (planner_manager_->pp_.desvel_changed_toomuch_ &&
               !close_to_final_goal) // case 4: desired velocity limits changes too much
    {
      cout << "desvel_changed_toomuch_=" << planner_manager_->pp_.desvel_changed_toomuch_ << endl;
      planner_manager_->pp_.desvel_changed_toomuch_ = false;
      changeFSMExecState(REPLAN_TRAJ, "EGOFSM");
    }

    break;
  }

  case WAIT_YAW: {
    if (!yaw_cmd_.yaw_reach)
      break;

    have_target_ = false;
    have_trigger_ = false;
    pending_goal_finish_trigger_ = true;
    goal_finish_stable_start_time_ = ros::Time(0);
    if (wp_batch_terminal_pending_)
      consumeWaypoint(true);
    changeFSMExecState(WAIT_TARGET, "yaw_only_complete");
    break;
  }

  case EMERGENCY_STOP: {
    cout << " SX" << flag_escape_emergency_ << "|" << enable_fail_safe_ << "|" << odom_vel_.norm() << flush;
    if (flag_escape_emergency_) // Avoiding repeated calls
    {
      callEmergencyStop(odom_pos_);
    } else {
      if (enable_fail_safe_ && odom_vel_.norm() < 0.1)
        changeFSMExecState(GEN_NEW_TRAJ, "EGOFSM");
    }

    flag_escape_emergency_ = false;
    break;
  }

  case CRASH_RECOVER: {
    if (flag_wait_crash_rec_) {
      if ((ros::Time::now() - crash_rec_start_time_).toSec() > 5.0) // 5.0s time out
      {
        flag_wait_crash_rec_ = false; // run callCrashRecovery() again
        changeFSMExecState(CRASH_RECOVER, "EGOFSM");
      }
      if (planner_manager_->map_->sml_->getInflateOccupancy(odom_pos_) <= 0) {
        flag_wait_crash_rec_ = false;
        changeFSMExecState(GEN_NEW_TRAJ, "EGOFSM");
      }
    } else {
      if (callCrashRecovery()) {
        flag_wait_crash_rec_ = true;
        crash_rec_start_time_ = ros::Time::now();
      } else {
        ROS_ERROR("Totally get stuck in obs! I can do nothing!");
        have_trigger_ = false;
        have_target_ = false;
        pending_goal_finish_trigger_ = false;
        goal_finish_stable_start_time_ = ros::Time(0);
        changeFSMExecState(WAIT_TARGET, "EGOFSM");
      }
    }

    break;
  }
  }

force_return:;
  exec_timer_.start();
}

void ego_planner::plan_manage::EGOReplanFSM::changeFSMExecState(FSM_EXEC_STATE new_state, string pos_call) {

  if (new_state == WAIT_TARGET && exec_state_ != INIT) {
    std_msgs::Bool exec_finish_trigger_msg;
    exec_finish_trigger_msg.data = true;
    exec_finish_trigger_pub_.publish(exec_finish_trigger_msg);
  }

  if (new_state != exec_state_) {
    std_msgs::Int8 s_m;
    s_m.data = new_state;
    state_pub_.publish(s_m);
  }

  static string state_str[10] = {"INIT",      "WAIT_TARGET",    "HANDLE_YAW",       "GEN_NEW_TRAJ",  "REPLAN_TRAJ",
                                 "EXEC_TRAJ", "EMERGENCY_STOP", "SEQUENTIAL_START", "CRASH_RECOVER", "WAIT_YAW"};
  int pre_s = int(exec_state_);
  exec_state_ = new_state;
  ROS_INFO_STREAM("[EGOPlanner] ego_fsm_state_transition drone_id="
                  << planner_manager_->pp_.drone_id << " from=" << state_str[pre_s]
                  << " to=" << state_str[int(new_state)] << " reason=" << pos_call << " have_target=" << have_target_
                  << " have_trigger=" << have_trigger_ << " have_odom=" << have_odom_
                  << " odom_pos=" << odom_pos_.transpose() << " final_goal=" << final_goal_.transpose());
  cout << "[" + pos_call + "]" << "Drone:" << planner_manager_->pp_.drone_id
       << ", from " + state_str[pre_s] + " to " + state_str[int(new_state)] << endl;
}

void ego_planner::plan_manage::EGOReplanFSM::printFSMExecState() const {
  static string state_str[10] = {"INIT",      "WAIT_TARGET",    "HANDLE_YAW",       "GEN_NEW_TRAJ",  "REPLAN_TRAJ",
                                 "EXEC_TRAJ", "EMERGENCY_STOP", "SEQUENTIAL_START", "CRASH_RECOVER", "WAIT_YAW"};

  cout << "\r[FSM]: state: " + state_str[int(exec_state_)] << ", Drone:" << planner_manager_->pp_.drone_id;

  // some warnings
  if (!have_odom_ || !have_target_ || !have_trigger_ || !yaw_cmd_.yaw_reach ||
      (planner_manager_->pp_.drone_id >= 1 && !have_recv_pre_agent_)) {
    cout << ". Waiting for ";
  }
  if (!have_odom_) {
    cout << "odom,";
  }
  if (!have_target_) {
    cout << "target,";
  }
  if (!have_trigger_) {
    cout << "trigger,";
  }
  if (planner_manager_->pp_.drone_id >= 1 && !have_recv_pre_agent_) {
    cout << "prev traj,";
  }
  if (!yaw_cmd_.yaw_reach) {
    cout << "yaw_reach,";
  }

  cout << endl;
}

void ego_planner::plan_manage::EGOReplanFSM::evaluateEnvironmentDensity() {
  if (wp_window_active_)
    return;

  LocalTrajData* traj = &planner_manager_->traj_.local_traj;
  const double DistForward = 1.5; // m, used in SLOW mode
  const double TimeForward = 1.0; // s, used in FAST mode
  const double HZ = 10.0;
  ros::Time now = ros::Time::now();
  if ((now - last_density_eval_time_).toSec() >= 1 / HZ) {
    last_density_eval_time_ = now;
    DensityEvalRayData best_ray;

    Eigen::Vector3d satrt_p;
    double t_lc = now.toSec() - traj->start_time;
    if (traj->start_time > 1.0 && t_lc < traj->duration) // valid traj
    {
      if (planner_manager_->pp_.speed_mode == PlanParameters::MODE::SLOW) {
        double vel_tmp = max(traj->traj.getVel(t_lc).norm(), 1e-1);

        double t_forward = DistForward / vel_tmp;
        t_forward *= 2;
        int trial_times = 10;
        do {
          t_forward /= 2;
          double t = min(t_lc + t_forward, traj->duration);
          satrt_p = traj->traj.getPos(t);
        } while ((satrt_p - odom_pos_).norm() > 1.3 * DistForward && trial_times-- > 0);
      } else {
        satrt_p = traj->traj.getPos(min(t_lc + TimeForward, traj->duration));
      }
    } else if (have_odom_)
      satrt_p = odom_pos_;
    else
      return;

    Eigen::Vector3d end_p;
    if (have_target_)
      end_p = final_goal_;
    else if (have_odom_) {
      const double GoalDist = 30.0; // m
      end_p = satrt_p + odom_q_.toRotationMatrix().col(0) * GoalDist;
    } else
      return;

    if (planner_manager_->densityEval(satrt_p, end_p, &best_ray, NULL)) {
      planner_manager_->DetVelByDensity(best_ray);
    }
  }
}

void ego_planner::plan_manage::EGOReplanFSM::planningReturnsChk() {
  if (plan_ret_stat_.ret != PLAN_RET::SUCCESS) {
    double dur = (ros::Time::now() - plan_ret_stat_.start_time).toSec();
    if (plan_ret_stat_.times > 100 && dur > 3.0) // 100 times and 3s of failure
    {
      ROS_ERROR("PlanRetChk: %d times and %fs duration of failure type %d. Unable to reach the given goal! Wait for "
                "the next target.",
                plan_ret_stat_.times, dur, plan_ret_stat_.ret);

      plan_ret_stat_.failure_histroy.push(std::make_pair(plan_ret_stat_.start_time, plan_ret_stat_.ret));
      while (plan_ret_stat_.failure_histroy.size() > 1000)
        plan_ret_stat_.failure_histroy.pop();
      plan_ret_stat_.setRet(PLAN_RET::SUCCESS);

      have_target_ = false;
      have_trigger_ = false;
      pending_goal_finish_trigger_ = false;
      goal_finish_stable_start_time_ = ros::Time(0);

      if (wp_window_active_) {
        // Planning exhausted mid-batch: drop the window so a new batch can be accepted.
        wp_window_active_ = false;
        wp_batch_terminal_pending_ = false;
        wp_list_.clear();
        wp_orig_idx_.clear();
      }

      if (target_type_ == TARGET_TYPE::PRESET_TARGET) {
        // prepare for next round
        wpt_id_ = 0;
        planNextWaypoint(wps_[wpt_id_]);
      }

      /* The navigation task terminated */
      callEmergencyStop(odom_pos_);
      changeFSMExecState(WAIT_TARGET, "RetChk");
    }
  }
}

void ego_planner::plan_manage::EGOReplanFSM::checkCollision() {
  static ros::Time last_chk_time(0);
  ros::Time this_time = ros::Time::now();
  if (last_chk_time.toSec() > 10 && (this_time - last_chk_time).toSec() > 0.3)
    ROS_ERROR("[Safety] Check intervel=%f is too big!", (this_time - last_chk_time).toSec());
  last_chk_time = this_time;

  /* --------- collision check data ---------- */
  LocalTrajData* traj = &planner_manager_->traj_.local_traj;
  auto map = planner_manager_->map_;
  const double t_cur = ros::Time::now().toSec() - traj->start_time;

  if (exec_state_ == WAIT_TARGET || traj->traj_id <= 0) {
    return;
  }

  /* ---------- check lost of depth ---------- */
  if (map->cur_->getOdomDepthTimeout()) {
    ROS_ERROR("Depth Lost! EMERGENCY_STOP");
    enable_fail_safe_ = false;
    changeFSMExecState(EMERGENCY_STOP, "SAFETY");
  } else
    enable_fail_safe_ = true;

  if (exec_state_ != EXEC_TRAJ && exec_state_ != CRASH_RECOVER && odom_vel_.norm() < 0.1 &&
      map->getOcc(odom_pos_) > 0) // get stuck in obstacles
  {
    auto grid = map->cur_;
    ROS_WARN("[EGO_CLOUD_OCC_AT_ODOM] state=%d odom=(%.3f,%.3f,%.3f) raw=%llu radius_kept=%llu self_removed=%llu "
             "raycast=%llu skew=%.3f",
             static_cast<int>(exec_state_), odom_pos_(0), odom_pos_(1), odom_pos_(2),
             static_cast<unsigned long long>(grid->getLastCloudRawCount()),
             static_cast<unsigned long long>(grid->getLastCloudRadiusCount()),
             static_cast<unsigned long long>(grid->getLastCloudSelfFilteredCount()),
             static_cast<unsigned long long>(grid->getLastCloudProjectedCount()), grid->getLastCloudOdomSkew());
    changeFSMExecState(CRASH_RECOVER, "SAFETY");
    return;
  }

  /* ---------- check trajectory ---------- */
  bool dangerous = false;
  const double should_be_safe_dura = traj->last_opt_cp_time;
  const double forward_look_time = t_cur + 2.0; // 2.0 seconds
  const double end_chk_time = planner_manager_->pp_.speed_mode == PlanParameters::MODE::SLOW
                                  ? min(max(should_be_safe_dura, forward_look_time), traj->duration)
                                  : traj->duration;
  const double t_step =
      map->cur_->getResolution() /
      ((traj->traj.getJuncPos(0) - traj->traj.getJuncPos(traj->traj.getPieceNum())).norm() / should_be_safe_dura) / 2;
  int occ = 0;
  for (double t = t_cur; t <= end_chk_time && !dangerous && occ != GRID_MAP_OUTOFREGION_FLAG; t += t_step) {
    auto p = traj->traj.getPos(t);

    // 1. occupancy check
    occ = map->getOcc(p);
    dangerous |= (occ > 0 && occ < GRID_MAP_OUTOFREGION_FLAG);
    if (dangerous)
      cout << "[SAFETY] detect collision at " << p.transpose() << " t=" << t << endl;

    // 2. swarm clearance check
    for (size_t id = 0; id < planner_manager_->traj_.swarm_traj.size(); id++) {
      if ((planner_manager_->traj_.swarm_traj.at(id).drone_id != (int)id) ||
          (planner_manager_->traj_.swarm_traj.at(id).drone_id == planner_manager_->pp_.drone_id)) {
        continue;
      }

      double t_X = t + (traj->start_time - planner_manager_->traj_.swarm_traj.at(id).start_time);
      if (t_X > 0 && t_X < planner_manager_->traj_.swarm_traj.at(id).duration) {
        Eigen::Vector3d swarm_pridicted = planner_manager_->traj_.swarm_traj.at(id).traj.getPos(t_X);
        double dist = (p - swarm_pridicted).norm();
        double allowed_dist =
            planner_manager_->getSwarmClearance() + planner_manager_->traj_.swarm_traj.at(id).des_clearance;
        if (dist < allowed_dist * 0.9) // allow some small error
        {
          ROS_WARN(
              "swarm distance between drone %d (traj_id:%d, t:%f) and drone %d (traj_id:%d, t:%f) is %f, too close!",
              planner_manager_->pp_.drone_id, traj->traj_id, t, (int)id,
              planner_manager_->traj_.swarm_traj.at(id).traj_id, t_X, dist);
          dangerous = true;
        }
      }
    }

    if (dangerous) {
      if (t_cur < 0.01)
        ROS_WARN("Find collision immediately after planning a safe traj?");

      /* Handle the collided case immediately */
      cout << "plan_ret_stat_.ret=" << plan_ret_stat_.ret << endl;
      bool ret = plan_ret_stat_.ret == PLAN_RET::SUCCESS ? planFromLocalTraj() : planFromGlobalTraj(3);
      if (ret) // Make a chance
      {
        ROS_INFO("Plan success when detect collision. %f", t / traj->duration);
        changeFSMExecState(EXEC_TRAJ, "SAFETY");
        return;
      } else {
        if (t - t_cur < emergency_time_ ||
            (p - odom_pos_).norm() < 0.5) // 0.8s of emergency time and 0.5m emergency distance
        {
          if (map->getOcc(odom_pos_) > 0) {
            ROS_ERROR("The drone is in obs, I have no way but only ignore it.");
          } else {
            // make the final chance
            planner_manager_->pp_.emergency_ = true; // toggle on emergency mode
            bool ret = plan_ret_stat_.ret == PLAN_RET::SUCCESS ? planFromLocalTraj() : planFromGlobalTraj(3);
            planner_manager_->pp_.emergency_ = false; // toggle off emergency mode
            if (ret) {
              ROS_INFO("Emergency plan success when detect collision. %f", t / traj->duration);
              changeFSMExecState(EXEC_TRAJ, "SAFETY");
              return;
            } else {
              if (!flag_wait_crash_rec_) {
                ROS_WARN("Emergency stop! time=%f, occ=[%f %f %f]", t - t_cur, p(0), p(1), p(2));
                changeFSMExecState(EMERGENCY_STOP, "SAFETY");
              }
            }
          }
        } else if (!flag_wait_crash_rec_) {
          ROS_WARN("current traj in collision, replan.");
          changeFSMExecState(REPLAN_TRAJ, "SAFETY");
        } else {
          // pass
        }
        return;
      }
    }
  }
}

bool ego_planner::plan_manage::EGOReplanFSM::callEmergencyStop(Eigen::Vector3d stop_pos) {

  planner_manager_->EmergencyStop(stop_pos);

  auto lc_traj = planner_manager_->traj_.local_traj;
  traj_server_.setTrajectory(lc_traj.traj, lc_traj.start_time);
  traj_utils::MINCOTraj MINCO_msg;
  polyTraj2ROSMsg(NULL, &MINCO_msg);
  broadcast_ploytraj_pub_.publish(MINCO_msg);
  PublishCanonicalTrajectory();

  return true;
}

bool ego_planner::plan_manage::EGOReplanFSM::callCrashRecovery() {
  const double RECOVER_REGION = 0.4;
  auto map = planner_manager_->map_;
  const double reso = map->cur_->getResolution();
  const int max_steps = std::ceil(RECOVER_REGION / reso);
  for (int step = 1; step <= max_steps; ++step)
    for (int dx = -step; dx <= step; ++dx)
      for (int dy = -step; dy <= step; ++dy)
        for (int dz = -step; dz <= step; ++dz)
          if (!(map->getOcc(odom_pos_ + Eigen::Vector3d(reso * dx, reso * dy, reso * dz)) > 0)) {
            Eigen::Vector3d escape_to =
                map->cur_->getGridCenter(odom_pos_ + Eigen::Vector3d(reso * dx, reso * dy, reso * dz));
            if (planner_manager_->OnePieceTrajGen(odom_pos_, escape_to)) {
              ROS_WARN("CrashRecovery: from (%f, %f, %f) to (%f, %f, %f)", odom_pos_(0), odom_pos_(1), odom_pos_(2),
                       escape_to(0), escape_to(1), escape_to(2));
              auto lc_traj = planner_manager_->traj_.local_traj;
              traj_server_.setTrajectory(lc_traj.traj, lc_traj.start_time);
              traj_utils::MINCOTraj MINCO_msg;
              polyTraj2ROSMsg(NULL, &MINCO_msg);
              broadcast_ploytraj_pub_.publish(MINCO_msg);
              PublishCanonicalTrajectory();
              return true;
            }
          }

  return false;
}

PLAN_RET ego_planner::plan_manage::EGOReplanFSM::callReboundReplan(bool flag_use_last_optimal, bool flag_random_init,
                                                                   vector<DensityEvalRayData>* pathes) {
  ros::Time t_s = ros::Time::now();

  planner_manager_->computePlanningParams(planner_manager_->pp_.max_vel_);
  ROS_INFO_STREAM("[EGOPlanner] ego_replan_start drone_id="
                  << planner_manager_->pp_.drone_id << " state=callReboundReplan"
                  << " start_pt=" << start_pt_.transpose() << " start_vel=" << start_vel_.transpose()
                  << " final_goal=" << final_goal_.transpose() << " use_last_optimal=" << flag_use_last_optimal
                  << " random_init=" << flag_random_init << " pathes_size="
                  << (pathes ? static_cast<int>(pathes->size()) : -1) << " touch_goal=" << touch_goal_);
  // ROS_WARN("Map Lock try");
  planner_manager_->map_->cur_->LockCopyToOutputAllMap(true); // to avoid map change during planning
  // ROS_WARN("Map Lock done");
  /* Window-threaded planning: pass the window points (except the terminal)
   * as via points so the committed trajectory threads the whole window and
   * only the window-final waypoint decelerates. */
  std::vector<Eigen::Vector3d> via_points;
  if (wp_chain_.size() > 1)
    via_points.assign(wp_chain_.begin(), wp_chain_.end() - 1);
  PLAN_RET plan_success =
      planner_manager_->reboundReplan(start_pt_, start_vel_, start_acc_, start_jerk_, glb_start_pt_, final_goal_,
                                      flag_use_last_optimal, flag_random_init, pathes, touch_goal_, via_points);
  planner_manager_->map_->cur_->LockCopyToOutputAllMap(false); // allow map change

  ROS_WARN("Map Use=%d", planner_manager_->map_->getMapUse());
  ROS_INFO_STREAM("[EGOPlanner] ego_replan_result drone_id="
                  << planner_manager_->pp_.drone_id << " ret=" << planRetName(plan_success) << " ret_code="
                  << static_cast<int>(plan_success) << " elapsed_sec=" << (ros::Time::now() - t_s).toSec()
                  << " map_use=" << planner_manager_->map_->getMapUse() << " start_pt=" << start_pt_.transpose()
                  << " final_goal=" << final_goal_.transpose() << " use_last_optimal=" << flag_use_last_optimal
                  << " random_init=" << flag_random_init << " touch_goal=" << touch_goal_);

  if (plan_success == PLAN_RET::SUCCESS) {
    cur_traj_to_cur_target_ = true;
    auto lc_traj = planner_manager_->traj_.local_traj;
    traj_server_.setTrajectory(lc_traj.traj, lc_traj.start_time);
    traj_utils::MINCOTraj MINCO_msg;
    polyTraj2ROSMsg(NULL, &MINCO_msg);
    broadcast_ploytraj_pub_.publish(MINCO_msg);
    PublishCanonicalTrajectory();
  }
  plan_ret_stat_.setRet(plan_success, (ros::Time::now() - t_s).toSec());

  updatePlannerResult(final_goal_, plan_success);
  // ros::spinOnce();
  return plan_success;
}

bool ego_planner::plan_manage::EGOReplanFSM::planFromGlobalTraj(const int trial_times /*=1*/) {

  vector<DensityEvalRayData>* all_rays = new vector<DensityEvalRayData>;
  if (getTrajPVAJ("odom")) {
    if (!planner_manager_->densityEval(start_pt_, final_goal_, NULL, all_rays))
      all_rays = NULL;
  } else
    return false;

  for (int i = 0; i < trial_times; i++) {
    ROS_INFO("Tried for %d time.", i);
    if (getTrajPVAJ("odom"))
      if (callReboundReplan(false, !all_rays || plan_ret_stat_.keep_failure_times >= trial_times, all_rays) ==
          PLAN_RET::SUCCESS) {
        if (i > 0)
          ROS_INFO("Tried for %d times when success.", i);
        return true;
      }
  }
  return false;
}

bool ego_planner::plan_manage::EGOReplanFSM::planFromLocalTraj(const int trial_times /*=1*/) {
  PLAN_RET ret = PLAN_RET::DEFAULT_FAIL;

  // first trial
  if (cur_traj_to_cur_target_ && getTrajPVAJ("traj")) // zx-todo this logic will make REPLAN_TRAJ state plan trajs again
                                                      // and again even it keeps fail. I modified REPLAN_TRAJ logic
    ret = callReboundReplan(true, false, NULL);

  if (ret != PLAN_RET::SUCCESS) {
    vector<DensityEvalRayData>* all_rays = new vector<DensityEvalRayData>;

    // second trial
    if (planner_manager_->densityEval(start_pt_, final_goal_, NULL, all_rays)) {
      if (getTrajPVAJ("traj"))
        ret = callReboundReplan(false, false, all_rays);
    } else
      all_rays = NULL;

    // final trials
    if (ret != PLAN_RET::SUCCESS) {
      for (int i = 0; i < trial_times; i++) {
        if (getTrajPVAJ("traj"))
          ret = callReboundReplan(false, true, all_rays);
        if (ret)
          break;
      }
      if (ret != PLAN_RET::SUCCESS) {
        return false;
      }
    }
  }

  return true;
}

bool ego_planner::plan_manage::EGOReplanFSM::getTrajPVAJ(const string data_source) {
  if (data_source == string("odom")) // from odom
  {
    start_pt_ = odom_pos_;
    // start_pt_ = odom_pos_ + odom_vel_ * plan_ret_stat_.succ_calc_time; // do not use this because the modified
    // start_pt_ can be in-collision
    start_vel_ = odom_vel_;
    start_acc_.setZero();
    start_jerk_.setZero();
  } else if (data_source == string("traj")) // from trajectory
  {
    LocalTrajData* info = &planner_manager_->traj_.local_traj;
    double t_cur = ros::Time::now().toSec() - info->start_time;
    if (t_cur > info->duration) {
      ROS_ERROR("planFromLocalTraj: Traj Exec Time : t_cur=%f > duration=%f", t_cur, info->duration);
      return false;
    }
    double t_use = t_cur + plan_ret_stat_.succ_calc_time;
    t_use = min(t_use, info->duration);

    start_pt_ = info->traj.getPos(t_use);
    start_vel_ = info->traj.getVel(t_use);
    start_acc_ = info->traj.getAcc(t_use);
    start_jerk_ = info->traj.getJer(t_use);
  } else {
    ROS_ERROR("[getTrajPVAJ]invalid source input: %s", data_source.c_str());
    return false;
  }
  return true;
}

bool ego_planner::plan_manage::EGOReplanFSM::planNextWaypoint(const Eigen::Vector3d next_wp, const double next_yaw,
                                                              const bool look_forward, const uint8_t yaw_mode,
                                                              const uint8_t yaw_path_mode, const bool enable_pre_yaw) {
  ROS_INFO_STREAM("[EGOPlanner] ego_plan_next_waypoint drone_id="
                  << planner_manager_->pp_.drone_id << " odom_pos=" << odom_pos_.transpose()
                  << " next_wp=" << next_wp.transpose() << " next_yaw=" << next_yaw << " look_forward=" << look_forward
                  << " yaw_mode=" << static_cast<unsigned int>(yaw_mode)
                  << " yaw_path_mode=" << static_cast<unsigned int>(yaw_path_mode));
  final_goal_ = next_wp;
  glb_start_pt_ = odom_pos_;
  have_target_ = true;
  pending_goal_finish_trigger_ = false;
  goal_finish_stable_start_time_ = ros::Time(0);
  cur_traj_to_cur_target_ = false;
  // 最短路径命令在目标边界同步真实yaw；保持方向命令保留TrajServer内部连续角。
  if (yaw_path_mode == quadrotor_msgs::LocalGoalSet::YAW_PATH_SHORTEST)
    traj_server_.syncYawFromOdom(odom_yaw_, "planNextWaypoint");

  if (exec_state_ == WAIT_TARGET) {
    /*** turn the yaw ***/
    Eigen::Vector2d dxy = final_goal_.block<2, 1>(0, 0) - odom_pos_.block<2, 1>(0, 0);
    if (dxy.norm() > 0.1 && look_forward) // 0.1m
    {
      double des_yaw = atan2(dxy(1), dxy(0));
      yaw_cmd_.yaw_reach = false; // this will work only if the drone state is WAIT_TARGET
      yaw_cmd_.cmd_time = ros::Time::now();
      yaw_cmd_.des_yaw = des_yaw;
      traj_server_.setYaw(des_yaw, odom_yaw_, odom_pos_, true, yaw_mode,
                          quadrotor_msgs::LocalGoalSet::YAW_PATH_SHORTEST);
    }

    if (!look_forward) {
      yaw_cmd_.yaw_reach = false; // this will work only if the drone state is WAIT_TARGET
      yaw_cmd_.cmd_time = ros::Time::now();
      yaw_cmd_.des_yaw = next_yaw;
      traj_server_.setYaw(next_yaw, odom_yaw_, odom_pos_, false, yaw_mode, yaw_path_mode);
    }
  }

  if (!look_forward) {
    yaw_cmd_.yaw_reach = false; // this will work only if the drone state is WAIT_TARGET
    yaw_cmd_.cmd_time = ros::Time::now();
    yaw_cmd_.des_yaw = next_yaw;
    traj_server_.setYaw(next_yaw, odom_yaw_, odom_pos_, false, yaw_mode, yaw_path_mode);
  } else {
    const Eigen::Vector2d dxy = final_goal_.head<2>() - odom_pos_.head<2>();
    traj_server_.resetYawLookforward(odom_pos_, enable_pre_yaw && dxy.norm() > 0.1);
  }

  /*** FSM ***/
  // [gym] 所有状态都直接GEN_NEW_TRAJ,否则规划延迟
  //    if (exec_state_ != WAIT_TARGET)
  changeFSMExecState(GEN_NEW_TRAJ, "TRIG");

  /*** display ***/
  vector<Eigen::Vector3d> gloabl_traj(2);
  gloabl_traj[0] = odom_pos_;
  gloabl_traj[1] = final_goal_;

  return true;
}

bool ego_planner::plan_manage::EGOReplanFSM::mondifyInCollisionFinalGoal() {
  if (!have_target_)
    return false;

  /* This part will cause unnecessary goal modification */
  // if (touch_goal_ && plan_ret_stat_.ret != PLAN_RET::SUCCESS && plan_ret_stat_.times > 10) // sometimes the goal
  // stays inside a big obstacle
  // {
  //   double d_step = planner_manager_->grid_map_->getResolution() / 2;
  //   double d_end = (final_goal_ - glb_start_pt_).norm();
  //   Eigen::Vector3d dir = (glb_start_pt_ - final_goal_).normalized();
  //   for (double d = d_step; d < d_end; d += d_step)
  //   {
  //     Eigen::Vector3d pt = final_goal_ + d * dir;
  //     // bool new_goal_clear = true;
  //     if (planner_manager_->grid_map_->getInflateOccupancy(pt) > 0) // make final_goal_ collided deliberately so that
  //     following codes will handle it.
  //     {
  //       ROS_WARN("Move final_goal_ from [%f %f %f] to [%f %f %f].", final_goal_(0), final_goal_(1), final_goal_(2),
  //       pt(0), pt(1), pt(2)); final_goal_ = pt; break;
  //     }
  //   }
  // }

  bool flag_goal_modified = false;

  auto map = planner_manager_->map_;
  bool in_obs_goal_clear = true;
  const double res = planner_manager_->map_->cur_->getResolution();
  for (double x = -res; x < res + 1e-5; x += res)
    for (double y = -res; y < res + 1e-5; y += res)
      for (double z = -res; z < res + 1e-5; z += res) {
        if (map->getOcc(final_goal_ + Eigen::Vector3d(x, y, z)) > 0) {
          in_obs_goal_clear = false;
          goto out_loop1;
        }
      }
out_loop1:;
  if (!in_obs_goal_clear) // Reason: in obstacles
  {
    Eigen::Vector3d orig_goal = final_goal_;
    double d_step = map->cur_->getResolution();
    double d_end = (final_goal_ - glb_start_pt_).norm();
    Eigen::Vector3d dir = (glb_start_pt_ - final_goal_).normalized();
    double d = d_step;
    for (; d < d_end && !in_obs_goal_clear; d += d_step) {
      Eigen::Vector3d pt = final_goal_ + d * dir;
      bool new_goal_clear = true;
      const double res = map->cur_->getResolution();
      for (double x = -res; x < res + 1e-5; x += res)
        for (double y = -res; y < res + 1e-5; y += res)
          for (double z = -res; z < res + 1e-5; z += res) {
            if (map->getOcc(pt + Eigen::Vector3d(x, y, z)) > 0) {
              new_goal_clear = false;
              goto out_loop2;
            }
          }
    out_loop2:;
      if (new_goal_clear) {
        final_goal_ = pt;
        ROS_WARN("Current in-collision waypoint (%.3f, %.3f %.3f) has been modified to (%.3f, %.3f %.3f)", orig_goal(0),
                 orig_goal(1), orig_goal(2), final_goal_(0), final_goal_(1), final_goal_(2));
        ROS_WARN_STREAM("[EGOPlanner] ego_goal_modified_for_collision mode=full_clearance original_goal="
                        << orig_goal.transpose() << " modified_goal=" << final_goal_.transpose() << " global_start="
                        << glb_start_pt_.transpose() << " shift_distance=" << (final_goal_ - orig_goal).norm()
                        << " resolution=" << map->cur_->getResolution());
        in_obs_goal_clear = true;
        flag_goal_modified = true;
        break;
      }
    }

    if (!in_obs_goal_clear) {
      d_step = map->cur_->getResolution() / 2;
      for (d = d_step; d < d_end && !in_obs_goal_clear; d += d_step) {
        Eigen::Vector3d pt = final_goal_ + d * dir;
        cout << "pt=" << pt.transpose() << endl;
        if (map->getOcc(pt) <= 0) {
          final_goal_ = pt;
          ROS_WARN("[Weak check]Current in-collision waypoint (%.3f, %.3f %.3f) has been modified to (%.3f, %.3f %.3f)",
                   orig_goal(0), orig_goal(1), orig_goal(2), final_goal_(0), final_goal_(1), final_goal_(2));
          ROS_WARN_STREAM("[EGOPlanner] ego_goal_modified_for_collision mode=weak_check original_goal="
                          << orig_goal.transpose() << " modified_goal=" << final_goal_.transpose() << " global_start="
                          << glb_start_pt_.transpose() << " shift_distance=" << (final_goal_ - orig_goal).norm()
                          << " resolution=" << map->cur_->getResolution());
          in_obs_goal_clear = true;
          flag_goal_modified = true;
          break;
        }
      }

      // can't find any valid collision-free point
      if (map->getOcc(final_goal_) <= 0) {
        // can't find any goal with enough clearance, just ignore
      } else {
        ROS_ERROR_STREAM("[EGOPlanner] ego_goal_collision_repair_failed goal="
                         << final_goal_.transpose() << " global_start=" << glb_start_pt_.transpose());
        ROS_ERROR_THROTTLE(1.0, "Can't find any collision-free point on global path.");
      }
    }
  }

  bool swarm_collide_goal_clear = true;
  if (touch_goal_) {
    for (size_t id = 0; id < planner_manager_->traj_.swarm_traj.size(); id++) {
      if ((planner_manager_->traj_.swarm_traj.at(id).drone_id != (int)id) ||
          (planner_manager_->traj_.swarm_traj.at(id).drone_id == planner_manager_->pp_.drone_id)) {
        continue;
      }

      Eigen::Vector3d others_lc_goal =
          planner_manager_->traj_.swarm_traj.at(id).traj.getPos(planner_manager_->traj_.swarm_traj.at(id).duration);
      double allowed_dist =
          planner_manager_->getSwarmClearance() + planner_manager_->traj_.swarm_traj.at(id).des_clearance;
      if ((others_lc_goal - final_goal_).norm() < allowed_dist) {
        bool new_goal_clear = false;
        Eigen::Vector3d orig_goal = final_goal_;
        double d_step = map->cur_->getResolution();
        double d_end = (final_goal_ - glb_start_pt_).norm();
        Eigen::Vector3d dir = (glb_start_pt_ - final_goal_).normalized();
        for (double d = d_step; d < d_end; d += d_step) {
          Eigen::Vector3d pt = final_goal_ + d * dir;
          if ((others_lc_goal - pt).norm() >= allowed_dist * 1.5) {
            final_goal_ = pt;
            ROS_WARN("Current swarm-collision waypoint (%.3f, %.3f %.3f) has been modified to (%.3f, %.3f %.3f)",
                     orig_goal(0), orig_goal(1), orig_goal(2), final_goal_(0), final_goal_(1), final_goal_(2));
            new_goal_clear = true;
            flag_goal_modified = true;
            break;
          }
        }

        if (!new_goal_clear) {
          swarm_collide_goal_clear = false;
          ROS_ERROR_THROTTLE(1.0, "Can't find any swarm-collision-free point on global path.");
        }
      }
    }
  }

  has_been_modified_ = flag_goal_modified;
  if (flag_goal_modified && in_obs_goal_clear && swarm_collide_goal_clear)
    return planNextWaypoint(final_goal_); // final_goal_=pt inside if success
  else
    return false;
}

void ego_planner::plan_manage::EGOReplanFSM::waypointCallback(const geometry_msgs::PoseStampedPtr& msg) {
  // if (msg->goal[2] < -0.1)
  //   return;

  Eigen::Vector3d end_wp;
  end_wp << msg->pose.position.x, msg->pose.position.y, 1.0;

  std::cout << "========================================================<<<<<<<<<<<<<<<<<<<<" << std::endl;
  ROS_INFO("Received goal: %f, %f, %f", end_wp.x(), end_wp.y(), end_wp.z());

  if (planNextWaypoint(end_wp)) {
    have_trigger_ = true;
  }
}

void ego_planner::plan_manage::EGOReplanFSM::aimCallbackYawPreset(const quadrotor_msgs::LocalGoalSetPtr& msg) {
  // Dead topic in this stack (no publisher); final waypoint of the window.
  const Eigen::Vector3d end_wp = msg->waypoints.size() >= 3 ? Eigen::Vector3d(msg->waypoints[msg->waypoints.size() - 3],
                                                                              msg->waypoints[msg->waypoints.size() - 2],
                                                                              msg->waypoints[msg->waypoints.size() - 1])
                                                            : Eigen::Vector3d::Zero();
  ROS_INFO("[Ego]: Received goalID: %d, pos: %.1f, %.1f, %.1f, lookforward: %d, yaw: %.2f", msg->drone_id, end_wp.x(),
           end_wp.y(), end_wp.z(), (int)msg->look_forward, msg->yaw);
  if (msg->drone_id != planner_manager_->pp_.drone_id)
    return;
  std::cout << "[Ego]: <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<" << std::endl;

  initPlannerResult();

  uint8_t yaw_mode = msg->yaw_mode;
  if (yaw_mode == quadrotor_msgs::LocalGoalSet::YAW_MODE_NORMAL && msg->yaw_low_speed)
    yaw_mode = quadrotor_msgs::LocalGoalSet::YAW_MODE_LOW_SPEED;
  uint8_t yaw_path_mode = msg->yaw_path_mode;
  if (yaw_mode == quadrotor_msgs::LocalGoalSet::YAW_MODE_PANORAMA &&
      yaw_path_mode == quadrotor_msgs::LocalGoalSet::YAW_PATH_KEEP_DIRECTION) {
    traj_server_.setPanoramaYaw(msg->yaw, odom_yaw_, end_wp);
    changeFSMExecState(WAIT_YAW, "Panorama Yaw Preset");
    return;
  }
  if (yaw_mode == quadrotor_msgs::LocalGoalSet::YAW_MODE_PANORAMA) {
    yaw_mode = quadrotor_msgs::LocalGoalSet::YAW_MODE_NORMAL;
    yaw_path_mode = quadrotor_msgs::LocalGoalSet::YAW_PATH_SHORTEST;
  }
  if (planNextWaypoint(end_wp, msg->yaw, msg->look_forward, yaw_mode, yaw_path_mode))
  // if (planNextWaypoint(end_wp))
  {
    have_trigger_ = true;
  }
}

void ego_planner::plan_manage::EGOReplanFSM::execAim() {
  if (abs(odom_yaw_ - aim_direction_) / M_PI * 180 > 10.0 && (target_pos_ - odom_pos_).norm() > 0.05 &&
      target_look_forward_) {

    ROS_WARN_THROTTLE(0.5, "[Ego-FSM] | Turning Yaw ... (cur yaw : %.2f deg, des_yaw : %.2f deg, err : %.2f deg)",
                      odom_yaw_ / M_PI * 180.0, aim_direction_ / M_PI * 180.0,
                      abs(odom_yaw_ - aim_direction_) / M_PI * 180.0);
    traj_server_.setYaw(aim_direction_, odom_yaw_, odom_pos_, false, target_yaw_mode_,
                        quadrotor_msgs::LocalGoalSet::YAW_PATH_SHORTEST);

  } else {
    ROS_INFO("[Ego-FSM] | Yaw Turned, Executing Plan ... ");
    if (planNextWaypoint(target_pos_, target_yaw_, target_look_forward_, target_yaw_mode_, target_yaw_path_mode_)) {
      have_trigger_ = true;
    }
  }
}

void ego_planner::plan_manage::EGOReplanFSM::aimCallback(const quadrotor_msgs::LocalGoalSetPtr& msg) {
  /* Waypoint window: flattened xyz (1 to 3 points, travel order); a window of
   * size 1 IS a single-goal message (the final waypoint is the batch goal). */
  const size_t n_floats = msg->waypoints.size();
  std::vector<Eigen::Vector3d> raw_wps;
  if (n_floats >= 3 && n_floats % 3 == 0) {
    raw_wps.reserve(n_floats / 3);
    for (size_t i = 0; i < n_floats; i += 3) {
      raw_wps.emplace_back(msg->waypoints[i], msg->waypoints[i + 1], msg->waypoints[i + 2]);
    }
  }
  const Eigen::Vector3d goal = raw_wps.empty() ? Eigen::Vector3d::Zero() : raw_wps.back();

  ROS_INFO(
      "[Ego]: Received goalID: %d, pos: %.1f, %.1f, %.1f, lookforward: %d, yaw: %.2f, yaw_mode: %u, yaw_path_mode: %u",
      msg->drone_id, goal.x(), goal.y(), goal.z(), (int)msg->look_forward, msg->yaw,
      static_cast<unsigned int>(msg->yaw_mode), static_cast<unsigned int>(msg->yaw_path_mode));
  if (msg->drone_id != planner_manager_->pp_.drone_id)
    return;

  std::cout << "[Ego]: <<<<<<<<<<<<<<<<<< New Goal <<<<<<<<<<<<<<<<<< " << std::endl;
  ROS_INFO("[EGOPlanner] ego_goal_received drone_id=%d goal=%.3f %.3f %.3f yaw=%.3f look_forward=%d "
           "yaw_mode=%u yaw_path_mode=%u state=aimCallback",
           msg->drone_id, goal.x(), goal.y(), goal.z(), msg->yaw,
           static_cast<int>(msg->look_forward), static_cast<unsigned int>(msg->yaw_mode),
           static_cast<unsigned int>(msg->yaw_path_mode));
  initPlannerResult();
  target_pos_ = goal;
  double yaw = msg->yaw;
  if (msg->yaw_path_mode == quadrotor_msgs::LocalGoalSet::YAW_PATH_SHORTEST) {
    while (yaw > M_PI)
      yaw -= 2 * M_PI;
    while (yaw < -M_PI)
      yaw += 2 * M_PI;
  }
  target_yaw_ = yaw;
  target_yaw_mode_ = msg->yaw_mode;
  if (target_yaw_mode_ == quadrotor_msgs::LocalGoalSet::YAW_MODE_NORMAL && msg->yaw_low_speed)
    target_yaw_mode_ = quadrotor_msgs::LocalGoalSet::YAW_MODE_LOW_SPEED;
  target_yaw_path_mode_ = msg->yaw_path_mode;
  target_look_forward_ = msg->look_forward;

  if (target_yaw_mode_ == quadrotor_msgs::LocalGoalSet::YAW_MODE_PANORAMA &&
      target_yaw_path_mode_ == quadrotor_msgs::LocalGoalSet::YAW_PATH_KEEP_DIRECTION) {
    // 全景旋转是纯yaw会话，不生成近零位移轨迹，也不进入GEN_NEW_TRAJ。
    traj_server_.setPanoramaYaw(target_yaw_, odom_yaw_, target_pos_);
    changeFSMExecState(WAIT_YAW, "Panorama Yaw");
    return;
  }

  // Waypoint window: a new batch always replaces the active one (mission owns
  // batch sequencing). A window of size 1 is a single-goal message.
  if (!raw_wps.empty()) {
    const int n_wp = std::min<size_t>(raw_wps.size(), 3);
    raw_wps.resize(n_wp);
    /* Seamless continuation (C): when the JIT-slid window starts at the
     * currently active waypoint, extend the queue and keep the committed
     * trajectory instead of replacing the window (which replans from scratch
     * and yanks the drone toward a fresh goal mid-flight). Only valid while a
     * trajectory is actually executing (have_target_); otherwise the window
     * must start planning normally. */
    if (target_look_forward_ && wp_window_active_ && have_target_ && mergeGoalWindow(msg->batch_id, raw_wps)) {
      /* Extend the threaded trajectory toward the new window end when the
       * committed one lags it (window-threaded mode keeps flying without a
       * per-point replan). */
      if (wp_chain_.empty() || (wp_chain_.back() - wp_list_.back()).norm() > 0.1)
        threadWindowTrajectory();
      else
        publishWindowVisualization();
      return;
    }
    if (setGoalWindow(msg->batch_id, raw_wps, target_yaw_, target_look_forward_, target_yaw_mode_,
                      target_yaw_path_mode_)) {
      // An already-satisfied batch emits all_consumed immediately and leaves
      // no active window; do not start a legacy single-goal trajectory.
      if (wp_window_active_)
        have_trigger_ = true;
      return;
    }
    // Fall through to single-goal path if setGoalWindow failed.
  }

  // Legacy single-goal message: close any active window so stale wp_list_
  // state cannot interfere with the new goal (e.g. stopMotion re-issue).
  wp_window_active_ = false;
  wp_batch_terminal_pending_ = false;
  wp_list_.clear();
  wp_orig_idx_.clear();

  // 计算当前点到目标点的方向的yaw
  Eigen::Vector3d dxy = target_pos_ - odom_pos_;
  aim_direction_ = atan2(dxy(1), dxy(0));
  if (aim_direction_ > M_PI)
    aim_direction_ -= 2 * M_PI;
  if (aim_direction_ < -M_PI)
    aim_direction_ += 2 * M_PI;

  if (if_handle_yaw_) {
    changeFSMExecState(HANDLE_YAW, "Recv Aim Callback");
  } else if (planNextWaypoint(target_pos_, target_yaw_, target_look_forward_, target_yaw_mode_,
                              target_yaw_path_mode_)) {
    have_trigger_ = true;
  }
}

void ego_planner::plan_manage::EGOReplanFSM::readGivenWpsAndPlan() {
  if (waypoint_num_ <= 0) {
    ROS_ERROR("Wrong waypoint_num_ = %d", waypoint_num_);
    return;
  }

  wps_.resize(waypoint_num_);
  for (int i = 0; i < waypoint_num_; i++) {
    wps_[i](0) = waypoints_[i][0];
    wps_[i](1) = waypoints_[i][1];
    wps_[i](2) = waypoints_[i][2];
  }

  for (size_t i = 0; i < (size_t)waypoint_num_; i++) {
    ros::Duration(0.001).sleep();
  }

  // plan first global waypoint
  wpt_id_ = 0;
  planNextWaypoint(wps_[wpt_id_]);
}

void ego_planner::plan_manage::EGOReplanFSM::mandatoryStopCallback(const std_msgs::Empty& msg) {
  mandatory_stop_ = true;
  ROS_ERROR("Received a mandatory stop command!");
  changeFSMExecState(EMERGENCY_STOP, "Mandatory Stop");
  enable_fail_safe_ = false;
}

/* Planner Reset Contract: back to WAIT_TARGET, drop the pending target, and
 * brake on the spot (stop trajectory) until a new goal arrives. */
bool ego_planner::plan_manage::EGOReplanFSM::resetServiceCallback(std_srvs::Trigger::Request&,
                                                                  std_srvs::Trigger::Response& res) {
  have_target_ = false;
  have_trigger_ = false;
  pending_goal_finish_trigger_ = false;
  touch_goal_ = false;
  /* Planner Reset Contract (PlannerIdleState): the waypoint window is part of
   * the active goal and MUST be cleared, otherwise a stale window merges the
   * first post-reset window and the drone never starts. */
  wp_window_active_ = false;
  wp_batch_terminal_pending_ = false;
  wp_chain_.clear();
  wp_list_.clear();
  wp_orig_idx_.clear();
  wp_skipped_mask_ = 0;
  traj_server_.reset();
  if (have_odom_)
    planner_manager_->EmergencyStop(odom_pos_);
  changeFSMExecState(WAIT_TARGET, "reset");
  res.success = true;
  res.message = "planner reset to WAIT_TARGET";
  return true;
}

void ego_planner::plan_manage::EGOReplanFSM::ifHandleYawCallback(const std_msgs::BoolConstPtr& msg) {
  if_handle_yaw_ = msg->data;
  ROS_INFO("[Ego-FSM] if_handle_yaw_ updated to %s", if_handle_yaw_ ? "true" : "false");
}

void ego_planner::plan_manage::EGOReplanFSM::odometryCallback(const nav_msgs::OdometryConstPtr& msg) {
  odom_pos_(0) = msg->pose.pose.position.x;
  odom_pos_(1) = msg->pose.pose.position.y;
  odom_pos_(2) = msg->pose.pose.position.z;

  odom_vel_(0) = msg->twist.twist.linear.x;
  odom_vel_(1) = msg->twist.twist.linear.y;
  odom_vel_(2) = msg->twist.twist.linear.z;

  ros::Time cur_stamp = msg->header.stamp;
  if (cur_stamp.isZero())
    cur_stamp = ros::Time::now();

  if (odom_acc_ready_) {
    const double dt = (cur_stamp - last_odom_stamp_).toSec();
    if (dt > 1e-3 && dt < 1.0) {
      // Suppress differentiation noise with a lightweight low-pass filter.
      const Eigen::Vector3d raw_acc = (odom_vel_ - last_odom_vel_) / dt;
      constexpr double ACC_LP_ALPHA = 0.2;
      odom_acc_ = ACC_LP_ALPHA * raw_acc + (1.0 - ACC_LP_ALPHA) * odom_acc_;
    } else {
      odom_acc_.setZero();
    }
  } else {
    odom_acc_.setZero();
    odom_acc_ready_ = true;
  }
  last_odom_vel_ = odom_vel_;
  last_odom_stamp_ = cur_stamp;

  odom_omega_(0) = msg->twist.twist.angular.x;
  odom_omega_(1) = msg->twist.twist.angular.y;
  odom_omega_(2) = msg->twist.twist.angular.z;

  odom_q_ = Eigen::Quaterniond(msg->pose.pose.orientation.w, msg->pose.pose.orientation.x, msg->pose.pose.orientation.y,
                               msg->pose.pose.orientation.z);

  odom_euler_ = odom_q_.toRotationMatrix().eulerAngles(0, 1, 2);

  Eigen::Matrix3d M = odom_q_.matrix();
  double yaw = atan2(M(1, 0), M(0, 0));
  double yaw_err = yaw - yaw_cmd_.des_yaw;
  while (yaw_err > M_PI)
    yaw_err -= 2 * M_PI;
  while (yaw_err < -M_PI)
    yaw_err += 2 * M_PI;

  odom_yaw_ = yaw;
  traj_server_.updateYawFromOdom(odom_yaw_);
  if (!traj_server_yaw_synced_) {
    traj_server_.syncYawFromOdom(odom_yaw_, "first_odom");
    traj_server_yaw_synced_ = true;
  }

  if (!yaw_cmd_.yaw_reach) {
    if (abs(yaw_err) < 10.0 / 57.3) // 10 degree
      yaw_cmd_.yaw_reach = true;
  }

  if (planner_manager_->map_->sml_->getInflateOccupancy(odom_pos_) > 0) {
    static Eigen::Vector3d last_occ_pt = Eigen::Vector3d::Zero();
    last_occ_pt = odom_pos_;
  }

  have_odom_ = true;
}

void ego_planner::plan_manage::EGOReplanFSM::triggerCallback(const geometry_msgs::PoseStampedPtr& msg) {
  have_trigger_ = true;
  cout << "Triggered!" << endl;
}

void ego_planner::plan_manage::EGOReplanFSM::RecvBroadcastMINCOTrajCallback(const traj_utils::MINCOTrajConstPtr& msg) {
  const size_t recv_id = (size_t)msg->drone_id;
  if ((int)recv_id == planner_manager_->pp_.drone_id) // myself
    return;

  if (msg->drone_id < 0) {
    ROS_ERROR("drone_id < 0 is not allowed in a swarm system!");
    return;
  }
  if (msg->order != 5) {
    ROS_ERROR("Only support trajectory order equals 5 now!");
    return;
  }
  if (msg->duration.size() != (msg->inner_x.size() + 1)) {
    ROS_ERROR("WRONG trajectory parameters.");
    return;
  }
  if (planner_manager_->traj_.swarm_traj.size() > recv_id &&
      planner_manager_->traj_.swarm_traj[recv_id].drone_id == (int)recv_id &&
      msg->start_time.toSec() - planner_manager_->traj_.swarm_traj[recv_id].start_time < 0) {
    ROS_WARN("[egofsm] Received drone %d's trajectory out of order or duplicated, abandon it.", (int)recv_id);
    ROS_WARN("Received time: %f, start_time %f, diff: %f", msg->start_time.toSec(),
             planner_manager_->traj_.swarm_traj[recv_id].start_time,
             msg->start_time.toSec() - planner_manager_->traj_.swarm_traj[recv_id].start_time);
    return;
  }

  ros::Time t_now = ros::Time::now();
  if (abs((t_now - msg->start_time).toSec()) > 0.25) {

    if (abs((t_now - msg->start_time).toSec()) <
        10.0) // 10 seconds offset, more likely to be caused by unsynced system time.
    {
      ROS_WARN("Time stamp diff: Local - Remote Agent %d = %fs", msg->drone_id, (t_now - msg->start_time).toSec());
    } else {
      ROS_ERROR("Time stamp diff: Local - Remote Agent %d = %fs, swarm time seems not synchronized, abandon!",
                msg->drone_id, (t_now - msg->start_time).toSec());
      return;
    }
  }

  /* Fill up the buffer */
  if (planner_manager_->traj_.swarm_traj.size() <= recv_id) {
    for (size_t i = planner_manager_->traj_.swarm_traj.size(); i <= recv_id; i++) {
      LocalTrajData blank;
      blank.drone_id = -1;
      blank.start_time = 0.0;
      planner_manager_->traj_.swarm_traj.push_back(blank);
    }
  }

  if (msg->start_time.toSec() <
      planner_manager_->traj_.swarm_traj[recv_id].start_time) // This must be called after buffer fill-up
  {
    ROS_WARN("Old traj received, ignored.");
    return;
  }

  /* Parse and store data */

  int piece_nums = msg->duration.size();
  Eigen::Matrix<double, 3, 3> headState, tailState;
  headState << msg->start_p[0], msg->start_v[0], msg->start_a[0], msg->start_p[1], msg->start_v[1], msg->start_a[1],
      msg->start_p[2], msg->start_v[2], msg->start_a[2];
  tailState << msg->end_p[0], msg->end_v[0], msg->end_a[0], msg->end_p[1], msg->end_v[1], msg->end_a[1], msg->end_p[2],
      msg->end_v[2], msg->end_a[2];
  Eigen::MatrixXd innerPts(3, piece_nums - 1);
  Eigen::VectorXd durations(piece_nums);
  for (int i = 0; i < piece_nums - 1; i++)
    innerPts.col(i) << msg->inner_x[i], msg->inner_y[i], msg->inner_z[i];
  for (int i = 0; i < piece_nums; i++)
    durations(i) = msg->duration[i];
  ego_planner::traj_opt::poly_traj::MinJerkOpt MJO;
  MJO.reset(headState, tailState, piece_nums);
  MJO.generate(innerPts, durations);

  /* Ignore the trajectories that are far away */
  Eigen::MatrixXd cps_chk = MJO.getInitConstraintPoints(5); // K = 5, such accuracy is sufficient
  bool far_away = true;
  for (int i = 0; i < cps_chk.cols(); ++i) {
    ROS_WARN_THROTTLE(2.0, "Todo: planning_horizen_ will change since 20230526. This is not exeamed here.");
    if ((cps_chk.col(i) - odom_pos_).norm() <
        planner_manager_->pp_.planning_horizen_ * 4 / 3) // close to me that can not be ignored
    {
      far_away = false;
      break;
    }
  }
  if (!far_away || !have_recv_pre_agent_) // Accept a far traj if no previous agent received
  {
    ego_planner::traj_opt::poly_traj::Trajectory trajectory = MJO.getTraj();
    planner_manager_->traj_.swarm_traj[recv_id].traj = trajectory;
    planner_manager_->traj_.swarm_traj[recv_id].drone_id = recv_id;
    planner_manager_->traj_.swarm_traj[recv_id].traj_id = msg->traj_id;
    planner_manager_->traj_.swarm_traj[recv_id].start_time = msg->start_time.toSec();
    planner_manager_->traj_.swarm_traj[recv_id].duration = trajectory.getTotalDuration();
    planner_manager_->traj_.swarm_traj[recv_id].start_pos = trajectory.getPos(0.0);
    planner_manager_->traj_.swarm_traj[recv_id].des_clearance = msg->des_clearance;

    /* Check Collision */
    if (planner_manager_->checkCollision(recv_id)) {
      if (!mandatory_stop_) {
        changeFSMExecState(REPLAN_TRAJ, "SWARM_CHECK");
      }
    }

    /* Check if receive agents have lower drone id */
    if (!have_recv_pre_agent_) {
      if ((int)planner_manager_->traj_.swarm_traj.size() >= planner_manager_->pp_.drone_id) {
        for (int i = 0; i < planner_manager_->pp_.drone_id; ++i) {
          if (planner_manager_->traj_.swarm_traj[i].drone_id != i) {
            break;
          }

          have_recv_pre_agent_ = true;
        }
      }
    }
  } else {
    planner_manager_->traj_.swarm_traj[recv_id].drone_id = -1; // Means this trajectory is invalid
  }
}

void ego_planner::plan_manage::EGOReplanFSM::polyTraj2ROSMsg(traj_utils::PolyTraj* poly_msg,
                                                             traj_utils::MINCOTraj* MINCO_msg) {

  auto data = &planner_manager_->traj_.local_traj;
  Eigen::VectorXd durs = data->traj.getDurations();
  // cout << "traj.duration=" << data->duration << " durs=" << durs.sum() << endl;
  int piece_num = data->traj.getPieceNum();

  if (poly_msg) {
    poly_msg->drone_id = planner_manager_->pp_.drone_id;
    poly_msg->traj_id = data->traj_id;
    poly_msg->start_time = ros::Time(data->start_time);
    poly_msg->order = 5; // todo, only support order = 5 now.
    poly_msg->duration.resize(piece_num);
    poly_msg->coef_x.resize(6 * piece_num);
    poly_msg->coef_y.resize(6 * piece_num);
    poly_msg->coef_z.resize(6 * piece_num);
    for (int i = 0; i < piece_num; ++i) {
      poly_msg->duration[i] = durs(i);

      ego_planner::traj_opt::poly_traj::CoefficientMat cMat = data->traj.getPiece(i).getCoeffMat();
      int i6 = i * 6;
      for (int j = 0; j < 6; j++) {
        poly_msg->coef_x[i6 + j] = cMat(0, j);
        poly_msg->coef_y[i6 + j] = cMat(1, j);
        poly_msg->coef_z[i6 + j] = cMat(2, j);
      }
    }
  }

  if (MINCO_msg) {
    MINCO_msg->drone_id = planner_manager_->pp_.drone_id;
    MINCO_msg->traj_id = data->traj_id;
    MINCO_msg->start_time = ros::Time(data->start_time);
    MINCO_msg->order = 5; // todo, only support order = 5 now.
    MINCO_msg->duration.resize(piece_num);
    MINCO_msg->des_clearance = planner_manager_->getSwarmClearance();
    Eigen::Vector3d vec;
    vec = data->traj.getPos(0);
    MINCO_msg->start_p[0] = vec(0), MINCO_msg->start_p[1] = vec(1), MINCO_msg->start_p[2] = vec(2);
    vec = data->traj.getVel(0);
    MINCO_msg->start_v[0] = vec(0), MINCO_msg->start_v[1] = vec(1), MINCO_msg->start_v[2] = vec(2);
    vec = data->traj.getAcc(0);
    MINCO_msg->start_a[0] = vec(0), MINCO_msg->start_a[1] = vec(1), MINCO_msg->start_a[2] = vec(2);
    vec = data->traj.getPos(data->duration);
    MINCO_msg->end_p[0] = vec(0), MINCO_msg->end_p[1] = vec(1), MINCO_msg->end_p[2] = vec(2);
    vec = data->traj.getVel(data->duration);
    MINCO_msg->end_v[0] = vec(0), MINCO_msg->end_v[1] = vec(1), MINCO_msg->end_v[2] = vec(2);
    vec = data->traj.getAcc(data->duration);
    MINCO_msg->end_a[0] = vec(0), MINCO_msg->end_a[1] = vec(1), MINCO_msg->end_a[2] = vec(2);
    MINCO_msg->inner_x.resize(piece_num - 1);
    MINCO_msg->inner_y.resize(piece_num - 1);
    MINCO_msg->inner_z.resize(piece_num - 1);
    Eigen::MatrixXd pos = data->traj.getPositions();
    for (int i = 0; i < piece_num - 1; i++) {
      MINCO_msg->inner_x[i] = pos(0, i + 1);
      MINCO_msg->inner_y[i] = pos(1, i + 1);
      MINCO_msg->inner_z[i] = pos(2, i + 1);
    }
    for (int i = 0; i < piece_num; i++)
      MINCO_msg->duration[i] = durs[i];
  }
}

/**
 * Publish the canonical trajectory topics (ground-station-channels.spec.md
 * §2.5): /planner/optimized_traj (piecewise polynomial, ascending power) and
 * /planner/search_path (raw A-star / kinodynamic search result), remapped to
 * /drone_<id>/planner/* at launch. Fed from the SAME objects as the
 * MINCOTraj broadcast — no separate computation.
 */
void ego_planner::plan_manage::EGOReplanFSM::PublishCanonicalTrajectory() {
  auto data = &planner_manager_->traj_.local_traj;
  if (data->traj.getPieceNum() <= 0) {
    return;
  }
  quadrotor_msgs::PiecewisePolynomial msg;
  msg.header.stamp = ros::Time::now();
  msg.header.frame_id = "world";
  const int order = 5; // 6th-order MINCO segment representation.
  quadrotor_msgs::FillPiecewisePolynomial(
      data->traj, order, [](const auto& traj_obj, int i) { return traj_obj.getPiece(i); },
      [](const auto& piece, int axis, int power) { return piece.getCoeffMat()(axis, power); }, msg);
  optimized_traj_pub_.publish(msg);

  const auto& sp = planner_manager_->getSearchPath();
  if (sp.empty()) {
    return;
  }
  nav_msgs::Path path;
  path.header = msg.header;
  path.poses.reserve(sp.size());
  for (const auto& p : sp) {
    geometry_msgs::PoseStamped ps;
    ps.header = msg.header;
    ps.pose.position.x = p.x();
    ps.pose.position.y = p.y();
    ps.pose.position.z = p.z();
    ps.pose.orientation.w = 1.0;
    path.poses.push_back(ps);
  }
  search_path_pub_.publish(path);

  /* Window-threaded initial path (trajPtVec before A* repair): the sampled
   * polyline that threads the window via points; visualize against the
   * optimized trajectory to audit the threading. */
  const auto& init = planner_manager_->getInitPath();
  if (!init.empty() && init_path_pub_.getNumSubscribers() > 0) {
    nav_msgs::Path init_path;
    init_path.header = msg.header;
    init_path.poses.reserve(init.size());
    for (const auto& p : init) {
      geometry_msgs::PoseStamped ps;
      ps.header = msg.header;
      ps.pose.position.x = p.x();
      ps.pose.position.y = p.y();
      ps.pose.position.z = p.z();
      ps.pose.orientation.w = 1.0;
      init_path.poses.push_back(ps);
    }
    init_path_pub_.publish(init_path);
  }
}

bool ego_planner::plan_manage::EGOReplanFSM::measureGroundHeight() const {
  if (ground_height_pub_.getNumSubscribers() <= 0)
    return false;

  const double RATE = 10.0;
  static ros::Time last_mea_time(0);
  ros::Time now = ros::Time::now();
  if (!enable_ground_height_measurement_ || (now - last_mea_time).toSec() < 1 / RATE)
    return false;
  last_mea_time = now;

  auto traj = &planner_manager_->traj_.local_traj;
  auto map = planner_manager_->map_->sml_;
  ros::Time t_now = ros::Time::now();

  double forward_t = 2.0 / planner_manager_->pp_.max_vel_; // 2.0m
  double traj_t = (t_now.toSec() - traj->start_time) + forward_t;
  if (traj->traj_id > 0 && traj_t <= traj->duration) {
    Eigen::Vector3d forward_p = traj->traj.getPos(traj_t);

    double reso = map->getResolution();
    for (; forward_p(2) > -5.0; forward_p(2) -= reso) // 5 meter of trusted height
    {
      int ret = map->getOccupancy(forward_p, true);
      if (ret == -1) // reach the virtual ground (no use)
      {
        return false;
      }
      if (ret == 1) // reach the ground
      {
        std_msgs::Float64 height_msg;
        height_msg.data = forward_p(2);
        ground_height_pub_.publish(height_msg);

        return true;
      }
    }
  }

  return false;
}

bool ego_planner::plan_manage::EGOReplanFSM::measureGroundHeight2() {
  if (!enable_ground_height_measurement_)
    return false;

  auto map = planner_manager_->map_->sml_;
  ;
  if (have_odom_) {
    // odom_pos_(3) += 2;
    Eigen::Vector3d forward_p = odom_pos_;
    // std::cout << "forward_p: " << forward_p << std::endl;

    double reso = map->getResolution();
    for (;; forward_p(2) -= reso) {
      int ret = map->getOccupancy(forward_p);
      if (ret == -1) // reach map bottom
      {
        // std::cout << "no publish height" << std::endl;
        return false;
      }
      if (ret == 1) // reach the ground
      {
        double height = forward_p(2);

        std_msgs::Float64 height_msg;
        height_msg.data = height;
        ground_height_pub_.publish(height_msg);
        // std::cout << "publish height" << std::endl;

        return true;
      }
    }
  }

  return false;
}

void ego_planner::plan_manage::EGOReplanFSM::PlanRetStatistic::setRet(const PLAN_RET r, const double time /*= -1.0*/) {
  if (ret == r) {
    times++;
  } else {
    times = 1;
    ret = r;
    start_time = ros::Time::now();
  }

  if (ret != PLAN_RET::SUCCESS) {
    keep_failure_times++;
  } else {
    keep_failure_times = 0;
  }

  if (r == PLAN_RET::SUCCESS && time > 0) {
    succ_calc_time = time;
  }
}

std::string ego_planner::plan_manage::EGOReplanFSM::PlanRetStatistic::show(bool print /*= true*/) {
  switch (ret) {
  case PLAN_RET::SUCCESS:
    if (print)
      cout << "SUCCESS" << endl;
    return std::string("SUCCESS");

  case PLAN_RET::INIT_FAIL:
    if (print)
      cout << "INIT_FAIL" << endl;
    return std::string("INIT_FAIL");

  case PLAN_RET::LOCAL_TGT_FAIL:
    if (print)
      cout << "LOCAL_TGT_FAIL" << endl;
    return std::string("LOCAL_TGT_FAIL");

  case PLAN_RET::DEFAULT_FAIL:
    if (print)
      cout << "DEFAULT_FAIL" << endl;
    return std::string("DEFAULT_FAIL");

  default:
    ROS_ERROR("Unknwon PLAN_RET ???");
    break;
  }

  return std::string("Unknwon PLAN_RET ???");
}

ego_planner::plan_manage::EGOReplanFSM::~EGOReplanFSM() {
  if (plan_ret_stat_.failure_histroy.size() > 0) {
    printf("====== failure statistics ======\n");
    while (plan_ret_stat_.failure_histroy.size()) {
      auto s = plan_ret_stat_.failure_histroy.front();
      plan_ret_stat_.failure_histroy.pop();
      printf("Failure type %d at time %f\n", s.second, s.first.toSec());
    }
  }
}

void ego_planner::plan_manage::EGOReplanFSM::initPlannerResult() {
  planner_result_.planner_goal.x = 0.0;
  planner_result_.planner_goal.y = 0.0;
  planner_result_.planner_goal.z = 0.0;
  planner_result_.plan_status = false;
  planner_result_.plan_times = 0;
  planner_result_.modify_status = false;
}

void ego_planner::plan_manage::EGOReplanFSM::updatePlannerResult(const Eigen::Vector3d goal, PLAN_RET status) {
  planner_result_.plan_status = status == PLAN_RET::SUCCESS;
  planner_result_.modify_status = has_been_modified_;
  if ((planner_result_.planner_goal.x == goal.x() && planner_result_.planner_goal.y == goal.y() &&
       planner_result_.planner_goal.z == goal.z())) {
    planner_result_.plan_times++;
  } else {
    planner_result_.plan_times = 1;
    planner_result_.planner_goal.x = goal.x();
    planner_result_.planner_goal.y = goal.y();
    planner_result_.planner_goal.z = goal.z();
  }
  planner_result_pub_.publish(planner_result_);
}

bool ego_planner::plan_manage::EGOReplanFSM::mergeGoalWindow(uint32_t batch_id,
                                                             const std::vector<Eigen::Vector3d>& raw_wps) {
  if (raw_wps.empty() || wp_list_.empty() || wp_active_idx_ >= static_cast<int>(wp_list_.size()))
    return false;
  /* Geometry continuity gate: the new window must start at the currently
   * active waypoint (mission slides overlapping windows), otherwise the batch
   * is a real replacement and the normal setGoalWindow path owns it. */
  if ((wp_list_[wp_active_idx_] - raw_wps.front()).norm() > 0.5)
    return false;

  /* Drop already-consumed points; the queue now starts at the active point,
   * which equals the new window's first point by the gate above. */
  if (wp_active_idx_ > 0) {
    wp_list_.erase(wp_list_.begin(), wp_list_.begin() + wp_active_idx_);
    wp_orig_idx_.erase(wp_orig_idx_.begin(), wp_orig_idx_.begin() + wp_active_idx_);
  }

  /* Walk the new window against the queue: matching points rebase their
   * batch-local index (progress is now reported under the new batch), new
   * points are appended in travel order. */
  size_t qi = 0;
  for (size_t i = 0; i < raw_wps.size(); ++i) {
    if (qi < wp_list_.size() && (wp_list_[qi] - raw_wps[i]).norm() < 0.5) {
      wp_orig_idx_[qi] = static_cast<int>(i);
      ++qi;
    } else {
      wp_list_.push_back(raw_wps[i]);
      wp_orig_idx_.push_back(static_cast<int>(i));
    }
  }
  wp_active_idx_ = 0;
  wp_batch_id_ = batch_id;
  wp_window_size_ = static_cast<int>(raw_wps.size());
  wp_skipped_mask_ = 0;
  ROS_INFO_STREAM("[EGOPlanner] ego_wp_window_merged batch_id=" << batch_id << " queue_size=" << wp_list_.size()
                                                                << " window_size=" << wp_window_size_
                                                                << " active=" << wp_list_.front().transpose());
  return true;
}

bool ego_planner::plan_manage::EGOReplanFSM::setGoalWindow(uint32_t batch_id,
                                                           const std::vector<Eigen::Vector3d>& raw_wps, double yaw,
                                                           bool look_forward, uint8_t yaw_mode, uint8_t yaw_path_mode) {
  wp_window_active_ = false;
  wp_batch_terminal_pending_ = false;
  wp_list_.clear();
  wp_orig_idx_.clear();
  wp_skipped_mask_ = 0;

  for (size_t i = 0; i < raw_wps.size(); ++i) {
    if (i == raw_wps.size() - 1) {
      /* Batch-final waypoint stays raw: when it is unreachable the native
       * mondifyInCollisionFinalGoal shifts it and sets has_been_modified_,
       * which the mission consumes as the unreachable-goal signal. Silently
       * reprojecting the final here would break that contract (drone stops
       * off-aim with modify_status=false and the mission never completes). */
      wp_list_.push_back(raw_wps[i]);
      wp_orig_idx_.push_back(static_cast<int>(i));
      continue;
    }
    if (planner_manager_->map_->getOcc(raw_wps[i]) <= 0) {
      wp_list_.push_back(raw_wps[i]);
      wp_orig_idx_.push_back(static_cast<int>(i));
      continue;
    }
    /* EGO-style seed rebound: an occupied intermediate waypoint is pushed
     * back along the travel direction (previous seed -> raw point) to the
     * first collision-free position, so the repaired point stays on the path
     * and the trajectory A* naturally bypasses the obstacle block instead of
     * hopping to an arbitrary nearest free cell. */
    const Eigen::Vector3d prev = wp_list_.empty() ? odom_pos_ : wp_list_.back();
    Eigen::Vector3d safe_pt;
    bool repaired = false;
    const Eigen::Vector3d backoff_dir = prev - raw_wps[i];
    const double backoff_len = backoff_dir.norm();
    if (backoff_len > 1e-6) {
      const Eigen::Vector3d dir = backoff_dir / backoff_len;
      const double reso = planner_manager_->map_->getReso();
      const double max_backoff = 2.0;
      const double step_max = std::min(max_backoff, backoff_len);
      auto isClearNeighborhood = [&](const Eigen::Vector3d& pt) {
        for (double x = -reso; x <= reso + 1e-6; x += reso)
          for (double y = -reso; y <= reso + 1e-6; y += reso)
            for (double z = -reso; z <= reso + 1e-6; z += reso)
              if (planner_manager_->map_->getOcc(pt + Eigen::Vector3d(x, y, z)) > 0)
                return false;
        return true;
      };
      for (double d = reso; d <= step_max + 1e-6 && !repaired; d += reso) {
        const Eigen::Vector3d cand = raw_wps[i] + dir * d;
        if (isClearNeighborhood(cand)) {
          safe_pt = cand;
          repaired = true;
        }
      }
    }
    if (!repaired)
      repaired = planner_manager_->getNearbySafePt(raw_wps[i], 30, safe_pt);
    if (repaired) {
      wp_list_.push_back(safe_pt);
      wp_orig_idx_.push_back(static_cast<int>(i));
      ROS_WARN_STREAM("[EGOPlanner] ego_wp_seed_rebound batch_id="
                      << batch_id << " orig_idx=" << i << " raw=" << raw_wps[i].transpose()
                      << " repaired=" << safe_pt.transpose() << " displacement=" << (safe_pt - raw_wps[i]).norm());
    } else {
      wp_skipped_mask_ |= (1 << i);
      ROS_WARN_STREAM("[EGOPlanner] ego_wp_seed_rebound_failed batch_id=" << batch_id << " orig_idx=" << i
                                                                          << " raw=" << raw_wps[i].transpose());
    }
  }

  if (wp_list_.empty()) {
    ROS_WARN("[EGOPlanner] ego_set_goal_window_failed batch_id=%u reason=all_wps_occupied", batch_id);
    return false;
  }

  wp_batch_id_ = batch_id;
  wp_window_size_ = static_cast<int>(raw_wps.size());
  wp_active_idx_ = 0;
  wp_batch_terminal_pending_ = true;

  // Pop already-satisfied waypoints at the front. A terminal yaw command is
  // satisfied only when both position and yaw have arrived; otherwise keep
  // the last waypoint so EGO executes the in-place turn and emits its result.
  constexpr double kImmediateYawTolerance = 5.0 / 180.0 * M_PI;
  auto frontSatisfied = [&]() {
    if ((odom_pos_ - wp_list_.front()).norm() >= wp_reach_radius_)
      return false;
    if (look_forward || wp_list_.size() > 1)
      return true;
    const double yaw_error = std::atan2(std::sin(yaw - odom_yaw_), std::cos(yaw - odom_yaw_));
    return std::fabs(yaw_error) < kImmediateYawTolerance;
  };
  while (!wp_list_.empty() && frontSatisfied()) {
    wp_list_.erase(wp_list_.begin());
    wp_orig_idx_.erase(wp_orig_idx_.begin());
  }

  if (wp_list_.empty()) {
    ROS_INFO("[EGOPlanner] ego_set_goal_window_reached batch_id=%u reason=all_wps_reached", batch_id);
    wp_window_active_ = true;
    consumeWaypoint(true);
    return true;
  }

  wp_window_active_ = true;
  const bool yaw_only =
      !look_forward && wp_list_.size() == 1 && (wp_list_.front() - odom_pos_).norm() < wp_reach_radius_;
  if (yaw_only) {
    final_goal_ = wp_list_.front();
    have_target_ = true;
    have_trigger_ = true;
    pending_goal_finish_trigger_ = false;
    goal_finish_stable_start_time_ = ros::Time(0);
    yaw_cmd_.yaw_reach = false;
    yaw_cmd_.cmd_time = ros::Time::now();
    yaw_cmd_.des_yaw = yaw;
    traj_server_.reset();
    if (yaw_path_mode == quadrotor_msgs::LocalGoalSet::YAW_PATH_SHORTEST)
      traj_server_.syncYawFromOdom(odom_yaw_, "yaw_only");
    traj_server_.setYaw(yaw, odom_yaw_, odom_pos_, false, yaw_mode, yaw_path_mode);
    wp_chain_.clear();
    publishWindowVisualization();
    ROS_INFO_STREAM("[EGOPlanner] ego_yaw_only_start batch_id=" << batch_id << " yaw=" << yaw << " odom_yaw="
                                                                << odom_yaw_ << " hold_pos=" << odom_pos_.transpose());
    changeFSMExecState(WAIT_YAW, "yaw_only");
    return true;
  }

  /* Window-threaded planning: plan one trajectory through ALL window points
   * (via points), terminal = window end. Intermediate waypoints are passed
   * through at speed; only the window end decelerates. */
  wp_chain_ = wp_list_;
  planNextWaypoint(wp_list_.back(), yaw, look_forward, yaw_mode, yaw_path_mode);
  publishWindowVisualization();
  ROS_INFO_STREAM("[EGOPlanner] ego_set_goal_window batch_id="
                  << batch_id << " window_size=" << wp_window_size_ << " valid_wps=" << wp_list_.size()
                  << " first_wp=" << wp_list_.front().transpose() << " threaded=" << wp_chain_.size());
  return true;
}

bool ego_planner::plan_manage::EGOReplanFSM::threadWindowTrajectory() {
  if (!wp_window_active_ || wp_list_.empty())
    return false;
  /* The committed trajectory already covers the window end: nothing to do. */
  if (!wp_chain_.empty() && !wp_list_.empty() && (wp_chain_.back() - wp_list_.back()).norm() < 0.1)
    return false;
  /* Extend: plan from the current state through the whole window to its end.
   * planNextWaypoint() keeps the existing trajectory until the new one is
   * ready (GEN_NEW_TRAJ swaps on success), so this is a seamless extension. */
  wp_chain_ = wp_list_;
  const bool ok = planNextWaypoint(wp_list_.back(), target_yaw_, target_look_forward_, target_yaw_mode_,
                                   target_yaw_path_mode_, false);
  if (ok)
    publishWindowVisualization();
  return ok;
}

void ego_planner::plan_manage::EGOReplanFSM::publishWindowVisualization() {
  if (window_points_pub_.getNumSubscribers() <= 0 || wp_list_.empty())
    return;
  visualization_msgs::MarkerArray markers;
  visualization_msgs::Marker pts;
  pts.header.frame_id = "world";
  pts.header.stamp = ros::Time::now();
  pts.ns = "window_points";
  pts.id = 0;
  pts.type = visualization_msgs::Marker::SPHERE_LIST;
  pts.action = visualization_msgs::Marker::ADD;
  pts.scale.x = pts.scale.y = pts.scale.z = 0.12;
  pts.color.r = 0.1f;
  pts.color.g = 0.6f;
  pts.color.b = 1.0f;
  pts.color.a = 1.0f;
  for (const auto& wp : wp_list_) {
    geometry_msgs::Point p;
    p.x = wp.x();
    p.y = wp.y();
    p.z = wp.z();
    pts.points.push_back(p);
  }
  markers.markers.push_back(pts);
  if (wp_list_.size() >= 2) {
    visualization_msgs::Marker line;
    line.header = pts.header;
    line.ns = "window_chain";
    line.id = 1;
    line.type = visualization_msgs::Marker::LINE_STRIP;
    line.action = visualization_msgs::Marker::ADD;
    line.scale.x = 0.05;
    line.color.r = 1.0f;
    line.color.g = 0.55f;
    line.color.b = 0.1f;
    line.color.a = 1.0f;
    line.points = pts.points;
    markers.markers.push_back(line);
  }
  window_points_pub_.publish(markers);
}

void ego_planner::plan_manage::EGOReplanFSM::consumeWaypoint(bool all_consumed) {
  if (all_consumed) {
    publishWaypointProgress(true);
    wp_batch_terminal_pending_ = false;
    wp_window_active_ = false;
    wp_chain_.clear();
    wp_list_.clear();
    wp_orig_idx_.clear();
  } else {
    wp_active_idx_++;
    publishWaypointProgress(false);
  }
}

void ego_planner::plan_manage::EGOReplanFSM::publishWaypointProgress(bool all_consumed) const {
  quadrotor_msgs::WaypointProgress msg;
  msg.batch_id = wp_batch_id_;
  msg.skipped_mask = wp_skipped_mask_;
  msg.all_consumed = all_consumed;

  if (all_consumed) {
    msg.consumed_count = wp_window_size_;
    msg.active_idx = wp_window_size_;
  } else if (!wp_orig_idx_.empty()) {
    msg.consumed_count = wp_orig_idx_[wp_active_idx_ - 1] + 1;
    msg.active_idx =
        (wp_active_idx_ < static_cast<int>(wp_orig_idx_.size())) ? wp_orig_idx_[wp_active_idx_] : wp_window_size_;
  } else {
    msg.consumed_count = wp_active_idx_;
    msg.active_idx = wp_active_idx_;
  }

  wp_progress_pub_.publish(msg);
}

bool ego_planner::plan_manage::EGOReplanFSM::checkWaypointPassby(const Eigen::Vector3d& pos) const {
  if (!wp_window_active_ || wp_active_idx_ + 1 >= wp_list_.size())
    return false;

  const Eigen::Vector3d dir = wp_list_[wp_active_idx_ + 1] - wp_list_[wp_active_idx_];
  const double dir_len = dir.norm();
  if (dir_len < 1e-6)
    return false;
  const Eigen::Vector3d dir_n = dir / dir_len;
  const Eigen::Vector3d rel = pos - wp_list_[wp_active_idx_];
  const double along = rel.dot(dir_n);
  const double lateral = (rel - along * dir_n).norm();
  return along > 0.0 && lateral < wp_passby_lateral_;
}
} // namespace plan_manage
} // namespace ego_planner
