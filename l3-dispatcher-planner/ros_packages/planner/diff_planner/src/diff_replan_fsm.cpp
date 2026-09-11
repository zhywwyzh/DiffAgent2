
#include <plan_manage/diff_replan_fsm.h>
#include <quadrotor_msgs/piecewise_from_poly.hpp>

namespace diff_planner {

void DiffReplanFSM::init(ros::NodeHandle& nh) {
  exec_state_ = FSM_EXEC_STATE::INIT;
  have_target_ = false;
  have_odom_ = false;
  have_recv_pre_agent_ = false;
  flag_escape_emergency_ = true;
  mandatory_stop_ = false;

  /*  fsm param  */
  nh.param("fsm/flight_type", target_type_, -1);
  nh.param("fsm/thresh_replan_time", replan_thresh_, -1.0);
  nh.param("fsm/planning_horizon", planning_horizon_, -1.0);
  nh.param("fsm/emergency_time", emergency_time_, 1.0);
  nh.param("fsm/realworld_experiment", flag_realworld_experiment_, false);
  nh.param("fsm/fail_safe", enable_fail_safe_, true);
  nh.param("fsm/ground_height_measurement", enable_ground_height_measurement_, false);
  nh.param("fsm/mondify_final_goal", mondify_final_goal_, true);
  nh.param("fsm/enable_stuck_detect", enable_stuck_detect_, true);
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
  visualization_.reset(new PlanningVisualization(nh));
  planner_manager_.reset(new DiffPlannerManager);
  planner_manager_->initPlanModules(nh, visualization_);

  have_trigger_ = !flag_realworld_experiment_;
  no_replan_thresh_ = 0.5 * emergency_time_ * planner_manager_->pp_.max_vel_;

  /* initialize  Anomaly Detection Parameters */
  last_local_target_pos_.setZero();
  last_target_change_time_ = ros::Time::now().toSec();
  last_near_unknown_box_update_time_ = 0.0;
  replan_fail_count_ = 0;
  TARGET_STUCK_TIME = 1.5 * planning_horizon_ / planner_manager_->pp_.max_vel_;
  need_hover_stop_ = false;

  /* callback */
  exec_timer_ = nh.createTimer(ros::Duration(0.01), &DiffReplanFSM::execFSMCallback, this);
  safety_timer_ = nh.createTimer(ros::Duration(0.05), &DiffReplanFSM::checkCollisionCallback, this);

  odom_sub_ = nh.subscribe("odom_world", 1, &DiffReplanFSM::odometryCallback, this);
  mandatory_stop_sub_ = nh.subscribe("mandatory_stop", 1, &DiffReplanFSM::mandatoryStopCallback, this);

  /* Planner Reset Contract (std_srvs/Trigger, fixed name shared by every
   * backend since they run mutually exclusively). */
  reset_srv_ = nh.advertiseService("/planner/reset", &DiffReplanFSM::resetServiceCallback, this);

  /* Use MINCO trajectory to minimize the message size in wireless communication */
  broadcast_ploytraj_pub_ = nh.advertise<traj_utils::MINCOTraj>("planning/broadcast_traj_send", 10);
  broadcast_ploytraj_sub_ = nh.subscribe<traj_utils::MINCOTraj>("planning/broadcast_traj_recv", 100,
                                                                &DiffReplanFSM::RecvBroadcastMINCOTrajCallback, this,
                                                                ros::TransportHints().tcpNoDelay());

  poly_traj_pub_ = nh.advertise<traj_utils::PolyTraj>("planning/trajectory", 10);
  search_path_pub_ = nh.advertise<nav_msgs::Path>("planner/search_path", 10);
  optimized_traj_pub_ = nh.advertise<quadrotor_msgs::PiecewisePolynomial>("planner/optimized_traj", 10);
  heartbeat_pub_ = nh.advertise<std_msgs::Empty>("planning/heartbeat", 10);
  fsm_state_pub_ = nh.advertise<std_msgs::UInt8>("planning/fsm_state", 10);
  wp_progress_pub_ = nh.advertise<quadrotor_msgs::WaypointProgress>("waypoint_progress", 10);
  plan_result_pub_ = nh.advertise<quadrotor_msgs::PlannerResult>("/planning/planner_result", 10);
  exec_finish_pub_ = nh.advertise<std_msgs::Bool>("exec_finish_trigger", 10);
  ground_height_pub_ = nh.advertise<std_msgs::Float64>("/ground_height_measurement", 10);

  if (target_type_ == TARGET_TYPE::MANUAL_TARGET) {
    waypoint_sub_ = nh.subscribe("/goal", 1, &DiffReplanFSM::waypointCallback, this);
  } else if (target_type_ == TARGET_TYPE::PRESET_TARGET) {
    trigger_sub_ = nh.subscribe("/traj_start_trigger", 1, &DiffReplanFSM::triggerCallback, this);

    ROS_INFO("Wait for 2 second.");
    int count = 0;
    while (ros::ok() && count++ < 2000) {
      ros::spinOnce();
      ros::Duration(0.001).sleep();
    }

    readGivenWpsAndPlan();
  } else
    cout << "Wrong target_type_ value! target_type_=" << target_type_ << endl;
}

void DiffReplanFSM::execFSMCallback(const ros::TimerEvent& e) {
  exec_timer_.stop(); // To avoid blockage
  std_msgs::Empty heartbeat_msg;
  heartbeat_pub_.publish(heartbeat_msg);

  static int fsm_num = 0;
  fsm_num++;
  if (fsm_num == 500) {
    fsm_num = 0;
    printFSMExecState();
  }
  // printFSMExecState();
  // ROS_WARN("flag_escape_emergency_1 = %d", (int)flag_escape_emergency_);

  switch (exec_state_) {
  case INIT: {
    if (!have_odom_) {
      goto force_return; // return;
    }
    changeFSMExecState(WAIT_TARGET, "FSM");
    break;
  }

  case WAIT_TARGET: {
    if (!have_target_ || !have_trigger_)
      goto force_return; // return;
    else {
      changeFSMExecState(SEQUENTIAL_START, "FSM");
    }
    break;
  }

  case SEQUENTIAL_START: // for swarm or single drone with drone_id = 0
  {
    if (planner_manager_->pp_.drone_id <= 0 || (planner_manager_->pp_.drone_id >= 1 && have_recv_pre_agent_)) {
      if (!mondify_final_goal_ && planner_manager_->grid_map_->getInflateOccupancy(final_goal_)) {
        ROS_WARN("Final goal in obstacle, unsafe. Emergency stop.");
        need_hover_stop_ = true;
        flag_escape_emergency_ = true;
        changeFSMExecState(EMERGENCY_STOP, "STUCK_DETECT");
      } else {
        bool success = planFromGlobalTraj(10); // zx-todo
        if (success) {
          replan_fail_count_ = 0;
          changeFSMExecState(EXEC_TRAJ, "FSM");
        } else {
          ROS_WARN("Failed to generate the first trajectory, keep trying");
          replan_fail_count_++;
          changeFSMExecState(SEQUENTIAL_START, "FSM"); // "changeFSMExecState" must be called each time planned
        }
      }
    }
    break;
  }

  case GEN_NEW_TRAJ: {
    if (!mondify_final_goal_ && planner_manager_->grid_map_->getInflateOccupancy(final_goal_)) {
      ROS_WARN("Final goal in obstacle, unsafe. Emergency stop.");
      need_hover_stop_ = true;
      flag_escape_emergency_ = true;
      changeFSMExecState(EMERGENCY_STOP, "STUCK_DETECT");
    } else {
      bool success = planFromGlobalTraj(10); // zx-todo
      if (success) {
        replan_fail_count_ = 0;
        changeFSMExecState(EXEC_TRAJ, "FSM");
        flag_escape_emergency_ = true;
        ROS_WARN("flag_escape_emergency_GEN_NEW_TRAJ = %d", (int)flag_escape_emergency_);
      } else {
        replan_fail_count_++;
        changeFSMExecState(GEN_NEW_TRAJ, "FSM"); // "changeFSMExecState" must be called each time planned
      }
    }
    break;
  }

  case REPLAN_TRAJ: {

    if (planFromLocalTraj(1)) {
      replan_fail_count_ = 0;
      changeFSMExecState(EXEC_TRAJ, "FSM");
    } else {
      replan_fail_count_++;
      changeFSMExecState(REPLAN_TRAJ, "FSM");
    }

    break;
  }

  case EXEC_TRAJ: {
    updateWaypointProgress();

    /* update near-unknown collision box at 10 Hz */
    {
      const double now = ros::Time::now().toSec();
      if (now - last_near_unknown_box_update_time_ >= replan_thresh_) {
        last_near_unknown_box_update_time_ = now;
        // planner_manager_->grid_map_->setNearUnknownCollisionBoxAtEnd(final_goal_);
      }
    }

    /* determine if need to replan */
    LocalTrajData* info = &planner_manager_->traj_.local_traj;
    double t_cur = ros::Time::now().toSec() - info->start_time;
    t_cur = min(info->duration, t_cur);
    Eigen::Vector3d pos = info->traj.getPos(t_cur);
    bool touch_the_goal = ((local_target_pt_ - final_goal_).norm() < 1e-2);

    const PtsChk_t* chk_ptr = &planner_manager_->traj_.local_traj.pts_chk;
    bool close_to_current_traj_end = (chk_ptr->size() >= 1 && chk_ptr->back().size() >= 1)
                                         ? chk_ptr->back().back().first - t_cur < emergency_time_
                                         : 0; // In case of empty vector

    if (planner_manager_->grid_map_->getInflateOccupancy(final_goal_)) {
      if (!mondify_final_goal_) {
        ROS_WARN("Final goal in obstacle, unsafe. Emergency stop.");
        need_hover_stop_ = true;
        flag_escape_emergency_ = true;
        changeFSMExecState(EMERGENCY_STOP, "STUCK_DETECT");
      } else if (mondifyInCollisionFinalGoal()) {
        ROS_WARN("Successfully modified final_goal in EXEC_TRAJ !!!");
        changeFSMExecState(REPLAN_TRAJ, "mondify_FSM");
      }
    } else if ((target_type_ == TARGET_TYPE::PRESET_TARGET) && (wpt_id_ < waypoint_num_ - 1) &&
               (final_goal_ - pos).norm() < no_replan_thresh_) // case 2: assign the next waypoint
    {
      wpt_id_++;
      planNextWaypoint(wps_[wpt_id_], true);
    } else if ((t_cur > info->duration - 1e-2) && touch_the_goal) // case 3: the final waypoint reached
    {
      have_target_ = false;
      have_trigger_ = false;
      // planner_manager_->grid_map_->resetNearUnknownCollisionBox();
      if (target_type_ == TARGET_TYPE::PRESET_TARGET) {
        // prepare for next round
        wpt_id_ = 0;
        planNextWaypoint(wps_[wpt_id_], true);
      }

      /* The navigation task completed */
      if (wp_flow_active_) {
        publishPlannerResult(final_goal_, true, false, true); // batch-final arrival
      }
      changeFSMExecState(WAIT_TARGET, "FSM");
    } else if (t_cur > replan_thresh_ ||
               (!touch_the_goal && close_to_current_traj_end)) // case 3: time to perform next replan
    {
      changeFSMExecState(REPLAN_TRAJ, "FSM");
    }
    // ROS_ERROR("AAAA");
    if (enable_stuck_detect_) {
      /* Avoid getting stuck wandering around large obstacles */
      static bool baseline_initialized = false;
      if (touch_the_goal) {
        static double last_proj_len = 0.0;
        static Eigen::Vector3d baseline_origin = odom_pos_;
        static Eigen::Vector3d last_goal_when_baseline = final_goal_;
        if (!baseline_initialized || (last_goal_when_baseline - final_goal_).norm() > 0.1) {
          baseline_origin = odom_pos_;
          last_goal_when_baseline = final_goal_;
          last_proj_len = 0.0;
          baseline_initialized = true;
        }
        Eigen::Vector3d cur_pos = odom_pos_;
        Eigen::Vector3d global2cur = cur_pos - baseline_origin;
        Eigen::Vector3d proj_pos = projectPointToLineSegment(baseline_origin, final_goal_, cur_pos);
        double proj_len = (proj_pos - baseline_origin).norm();
        if (proj_len - last_proj_len < TARGET_STUCK_THRESH) {
          if (ros::Time::now().toSec() - last_target_change_time_ > TARGET_STUCK_TIME) {
            ROS_WARN("Drone stuck! Obstacle too large and near final goal. Emergency stop.");
            need_hover_stop_ = true;
            flag_escape_emergency_ = true;
            changeFSMExecState(EMERGENCY_STOP, "STUCK_DETECT");
          }
        } else {
          last_proj_len = proj_len;
          last_target_change_time_ = ros::Time::now().toSec();
        }

        if (global2cur.norm() > planning_horizon_ * M_SQRT2) {
          ROS_WARN("Drone stuck! The drone flew too far out of its way . Emergency stop.");
          need_hover_stop_ = true;
          flag_escape_emergency_ = true;
          changeFSMExecState(EMERGENCY_STOP, "STUCK_DETECT");
        }
      } else {
        baseline_initialized = false;
        if ((local_target_pt_ - last_local_target_pos_).norm() < TARGET_STUCK_THRESH) {
          if (ros::Time::now().toSec() - last_target_change_time_ > TARGET_STUCK_TIME) {
            ROS_WARN("Drone stuck! Obstacle too large. Emergency stop.");
            need_hover_stop_ = true;
            flag_escape_emergency_ = true;
            changeFSMExecState(EMERGENCY_STOP, "STUCK_DETECT");
          }
        } else {
          last_local_target_pos_ = local_target_pt_;
          last_target_change_time_ = ros::Time::now().toSec();
        }
      }
    }
    break;
  }

  case EMERGENCY_STOP: {
    if (flag_escape_emergency_) // Avoiding repeated calls
    {
      // ROS_INFO("flag_escape_emergency_ odom_pos: (%.2f, %.2f, %.2f), odom_vel: (%.2f, %.2f, %.2f)", odom_pos_.x(),
      // odom_pos_.y(), odom_pos_.z(), odom_vel_.x(), odom_vel_.y(), odom_vel_.z());
      callEmergencyStop(odom_pos_);
    } else {
      // ROS_INFO("EMERGENCY_STOP odom_pos: (%.2f, %.2f, %.2f), odom_vel: (%.2f, %.2f, %.2f)", odom_pos_.x(),
      // odom_pos_.y(), odom_pos_.z(), odom_vel_.x(), odom_vel_.y(), odom_vel_.z());
      if (enable_fail_safe_ && !need_hover_stop_ && odom_vel_.norm() < 0.1) {
        last_target_change_time_ = ros::Time::now().toSec();
        changeFSMExecState(GEN_NEW_TRAJ, "FSM");
      } else if (enable_fail_safe_ && need_hover_stop_ && odom_vel_.norm() < 0.1) {
        ROS_INFO("Exiting EMERGENCY_STOP. Switching to WAIT_TARGET. Need a new target point !!!");
        need_hover_stop_ = false;
        have_target_ = false;
        have_trigger_ = false;
        // planner_manager_->grid_map_->resetNearUnknownCollisionBox();
        changeFSMExecState(WAIT_TARGET, "EMERGENCY_EXIT");
      }
    }

    flag_escape_emergency_ = false;
    break;
  }
  }
  // ROS_WARN("flag_escape_emergency_2 = %d", (int)flag_escape_emergency_);

force_return:;
  finishProcess();
  exec_timer_.start();
}
void DiffReplanFSM::finishProcess() {
  if (replan_fail_count_ > MAX_REPLAN_FAIL_COUNT) {
    ROS_WARN("replan fail too much. Emergency stop.");
    replan_fail_count_ = 0;
    // need_hover_stop_ = true;
    flag_escape_emergency_ = true;
    changeFSMExecState(EMERGENCY_STOP, "finishProcess");
  }

  std_msgs::UInt8 state_msg;
  state_msg.data = static_cast<uint8_t>(exec_state_);
  fsm_state_pub_.publish(state_msg);
}

void DiffReplanFSM::changeFSMExecState(FSM_EXEC_STATE new_state, string pos_call) {

  if (new_state == exec_state_)
    continously_called_times_++;
  else
    continously_called_times_ = 1;

  static string state_str[8] = {"INIT",      "WAIT_TARGET",    "GEN_NEW_TRAJ",    "REPLAN_TRAJ",
                                "EXEC_TRAJ", "EMERGENCY_STOP", "SEQUENTIAL_START"};
  int pre_s = int(exec_state_);
  exec_state_ = new_state;
  cout << "[" + pos_call + "]" << "Drone:" << planner_manager_->pp_.drone_id
       << ", from " + state_str[pre_s] + " to " + state_str[int(new_state)] << endl;
}

void DiffReplanFSM::printFSMExecState() {
  static string state_str[8] = {"INIT",      "WAIT_TARGET",    "GEN_NEW_TRAJ",    "REPLAN_TRAJ",
                                "EXEC_TRAJ", "EMERGENCY_STOP", "SEQUENTIAL_START"};

  cout << "\r[FSM]: state: " + state_str[int(exec_state_)] << ", Drone:" << planner_manager_->pp_.drone_id;

  // some warnings
  if (!have_odom_ || !have_target_ || !have_trigger_ ||
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

  cout << endl;
}

std::pair<int, DiffReplanFSM::FSM_EXEC_STATE> DiffReplanFSM::timesOfConsecutiveStateCalls() {
  return std::pair<int, FSM_EXEC_STATE>(continously_called_times_, exec_state_);
}

void DiffReplanFSM::checkCollisionCallback(const ros::TimerEvent& e) {
  // check ground height by the way
  if (enable_ground_height_measurement_) {
    double height;
    measureGroundHeight(height);
  }

  /* --------- collision check data ---------- */
  LocalTrajData* info = &planner_manager_->traj_.local_traj;
  auto map = planner_manager_->grid_map_;
  const double t_cur = ros::Time::now().toSec() - info->start_time;
  PtsChk_t pts_chk = info->pts_chk;

  if (exec_state_ == WAIT_TARGET || exec_state_ == EMERGENCY_STOP || info->traj_id <= 0)
    return;

  /* ---------- check lost of depth ---------- */
  if (map->getOdomDepthTimeout()) {
    ROS_ERROR("Depth Lost! EMERGENCY_STOP");
    enable_fail_safe_ = false;
    changeFSMExecState(EMERGENCY_STOP, "SAFETY");
  }

  /* ---------- check trajectory ---------- */
  double t_temp = t_cur; // t_temp will be changed in the next function!
  int i_start = info->traj.locatePieceIdx(t_temp);

  if (i_start >= (int)pts_chk.size()) {
    return;
  }
  size_t j_start = 0;
  for (; i_start < (int)pts_chk.size(); ++i_start) {
    for (j_start = 0; j_start < pts_chk[i_start].size(); ++j_start) {
      if (pts_chk[i_start][j_start].first > t_cur) {
        goto find_ij_start;
      }
    }
  }
find_ij_start:;

  const bool touch_the_end = ((local_target_pt_ - final_goal_).norm() < 1e-2);
  size_t i_end = touch_the_end ? pts_chk.size() : pts_chk.size() * 3 / 4;
  for (size_t i = i_start; i < i_end; ++i) {
    for (size_t j = j_start; j < pts_chk[i].size(); ++j) {

      double t = pts_chk[i][j].first;
      Eigen::Vector3d p = pts_chk[i][j].second;

      bool dangerous = false;
      dangerous |= map->getInflateOccupancy(p);

      for (size_t id = 0; id < planner_manager_->traj_.swarm_traj.size(); id++) {
        if ((planner_manager_->traj_.swarm_traj.at(id).drone_id != (int)id) ||
            (planner_manager_->traj_.swarm_traj.at(id).drone_id == planner_manager_->pp_.drone_id)) {
          continue;
        }

        double t_X = t + (info->start_time - planner_manager_->traj_.swarm_traj.at(id).start_time);
        if (t_X > 0 && t_X < planner_manager_->traj_.swarm_traj.at(id).duration) {
          Eigen::Vector3d swarm_pridicted = planner_manager_->traj_.swarm_traj.at(id).traj.getPos(t_X);
          double dist = (p - swarm_pridicted).norm();
          double allowed_dist =
              planner_manager_->getSwarmClearance() + planner_manager_->traj_.swarm_traj.at(id).des_clearance;
          if (dist < allowed_dist) {
            ROS_WARN("swarm distance between drone %d and drone %d is %f, too close!", planner_manager_->pp_.drone_id,
                     (int)id, dist);
            dangerous = true;
            break;
          }
        }
      }

      if (dangerous) {
        /* Handle the collided case immediately */
        if (planFromLocalTraj()) // Make a chance
        {
          ROS_INFO("Plan success when detect collision. %f", t / info->duration);
          changeFSMExecState(EXEC_TRAJ, "SAFETY");
          flag_escape_emergency_ = true;
          return;
        } else {
          if (t - t_cur < emergency_time_) // 0.8s of emergency time
          {
            ROS_WARN("Emergency stop! time=%f", t - t_cur);
            flag_escape_emergency_ = true;
            changeFSMExecState(EMERGENCY_STOP, "SAFETY");
          } else {
            ROS_WARN("current traj in collision, replan.");
            changeFSMExecState(REPLAN_TRAJ, "SAFETY");
          }
          return;
        }
        break;
      }
    }
    j_start = 0;
  }
}

bool DiffReplanFSM::callEmergencyStop(Eigen::Vector3d stop_pos) {

  planner_manager_->EmergencyStop(stop_pos);

  traj_utils::PolyTraj poly_msg;
  traj_utils::MINCOTraj MINCO_msg;
  polyTraj2ROSMsg(poly_msg, MINCO_msg);
  poly_traj_pub_.publish(poly_msg);
  broadcast_ploytraj_pub_.publish(MINCO_msg);
  return true;
}

bool DiffReplanFSM::callReboundReplan(bool flag_use_poly_init, bool flag_randomPolyTraj) {
  if (mondify_final_goal_ && mondifyInCollisionFinalGoal()) {
    ROS_WARN("Successfully modified final_goal in callReboundReplan !!!");
  }
  planner_manager_->getLocalTarget(planning_horizon_, start_pt_, final_goal_, local_target_pt_, local_target_vel_,
                                   catch_goal_);

  bool plan_success =
      planner_manager_->reboundReplan(start_pt_, start_vel_, start_acc_, local_target_pt_, local_target_vel_,
                                      (have_new_target_ || flag_use_poly_init), flag_randomPolyTraj, catch_goal_);

  have_new_target_ = false;

  if (plan_success) {
    traj_utils::PolyTraj poly_msg;
    traj_utils::MINCOTraj MINCO_msg;
    polyTraj2ROSMsg(poly_msg, MINCO_msg);
    poly_traj_pub_.publish(poly_msg);
    broadcast_ploytraj_pub_.publish(MINCO_msg);
    PublishCanonicalTrajectory();
  }

  return plan_success;
}

bool DiffReplanFSM::planFromGlobalTraj(const int trial_times /*=1*/) // zx-todo
{
  if (!first_plan_unknown_inf_cleared_) {
    first_plan_unknown_inf_cleared_ = true;
    planner_manager_->grid_map_->clearUnknownInflateInBox(odom_pos_);
  }

  /// Shift the start point to the nearest inflate-free cell (same as SUPER PlanFromRest).
  Eigen::Vector3d local_start_pt;
  const double start_shift_max_dist = 3.0;
  if (!planner_manager_->grid_map_->getNearestInflateFreePoint(odom_pos_, local_start_pt, start_shift_max_dist)) {
    ROS_ERROR("[DiffReplanFSM] Local start point is deeply occupied, cannot find free cell within %.1fm.",
              start_shift_max_dist);
    return false;
  }
  start_pt_ = local_start_pt;
  if ((start_pt_ - odom_pos_).norm() > 1e-2) {
    ROS_WARN("[DiffReplanFSM] Shift planning start from odom (%.2f, %.2f, %.2f) to (%.2f, %.2f, %.2f), dist=%.3f",
             odom_pos_.x(), odom_pos_.y(), odom_pos_.z(), start_pt_.x(), start_pt_.y(), start_pt_.z(),
             (start_pt_ - odom_pos_).norm());
  }
  start_vel_ = odom_vel_;
  start_acc_.setZero();

  bool flag_random_poly_init;
  if (timesOfConsecutiveStateCalls().first == 1)
    flag_random_poly_init = false;
  else
    flag_random_poly_init = true;

  for (int i = 0; i < trial_times; i++) {
    if (callReboundReplan(true, flag_random_poly_init)) {
      return true;
    }
  }
  return false;
}

bool DiffReplanFSM::planFromLocalTraj(const int trial_times /*=1*/) {
  planner_manager_->clearReplanStitch();

  LocalTrajData* info = &planner_manager_->traj_.local_traj;
  const double replan_start_WT = ros::Time::now().toSec();
  double t_cur = replan_start_WT - info->start_time;
  t_cur = std::max(0.0, std::min(info->duration, t_cur));

  const double forward_dt = planner_manager_->pp_.replan_forward_dt_;
  double t_replan_state = t_cur + forward_dt;
  bool use_stitch = (info->traj_id > 0 && info->duration > 1e-3 && t_replan_state < info->duration - 1e-3);
  if (!use_stitch) {
    t_replan_state = t_cur;
  } else {
    planner_manager_->beginReplanStitch(replan_start_WT, t_cur, t_replan_state);
  }

  start_pt_ = info->traj.getPos(t_replan_state);
  start_vel_ = info->traj.getVel(t_replan_state);
  start_acc_ = info->traj.getAcc(t_replan_state);

  bool success = callReboundReplan(false, false);

  if (!success) {
    success = callReboundReplan(true, false);
    if (!success) {
      for (int i = 0; i < trial_times; i++) {
        success = callReboundReplan(true, true);
        if (success)
          break;
      }
    }
  }

  if (!success)
    planner_manager_->clearReplanStitch();

  return success;
}

bool DiffReplanFSM::planNextWaypointWindow(const std::vector<Eigen::Vector3d>& window, bool flag_2replan) {
  if (window.empty())
    return false;
  wp_plan_count_++;
  bool success = false;
  success = planner_manager_->planGlobalTrajWaypoints(odom_pos_, odom_vel_, Eigen::Vector3d::Zero(), window,
                                                      Eigen::Vector3d::Zero(), Eigen::Vector3d::Zero());
  if (success) {
    final_goal_ = window.back();
    /*** display ***/
    constexpr double step_size_t = 0.1;
    int i_end = floor(planner_manager_->traj_.global_traj.duration / step_size_t);
    vector<Eigen::Vector3d> gloabl_traj(i_end);
    for (int i = 0; i < i_end; i++) {
      gloabl_traj[i] = planner_manager_->traj_.global_traj.traj.getPos(i * step_size_t);
    }
    have_target_ = true;
    have_new_target_ = true;
    /*** FSM ***/
    if (exec_state_ != WAIT_TARGET && flag_2replan && exec_state_ != EMERGENCY_STOP) {
      ros::Time start_time = ros::Time::now();
      ros::Duration timeout(0.5);
      while (exec_state_ != EXEC_TRAJ) {
        ros::spinOnce();
        ros::Duration(0.001).sleep();
        if (ros::Time::now() - start_time > timeout) {
          ROS_WARN("Timeout waiting for state to change to EXEC_TRAJ.");
          return false;
        }
      }
      changeFSMExecState(REPLAN_TRAJ, "TRIG");
    } else if (exec_state_ == EMERGENCY_STOP) {
      return true;
    }
    visualization_->displayGlobalPathList(gloabl_traj, 0.1, 0);
  } else {
    ROS_ERROR("Unable to generate global trajectory!");
  }
  return success;
}

bool DiffReplanFSM::planNextWaypoint(const Eigen::Vector3d next_wp, bool flag_2replan) {
  std::vector<Eigen::Vector3d> one_pt_wps{next_wp};
  return planNextWaypointWindow(one_pt_wps, flag_2replan);
}

void DiffReplanFSM::publishWaypointProgress(bool all_consumed) {
  quadrotor_msgs::WaypointProgress msg;
  msg.batch_id = wp_batch_id_;
  msg.skipped_mask = 0;
  msg.all_consumed = all_consumed;
  if (all_consumed) {
    msg.consumed_count = static_cast<uint8_t>(wp_window_size_);
    msg.active_idx = static_cast<uint8_t>(wp_window_size_);
  } else {
    msg.consumed_count = wp_active_idx_ > 0 ? static_cast<uint8_t>(wp_orig_idx_[wp_active_idx_ - 1] + 1) : 0;
    msg.active_idx = wp_active_idx_ < static_cast<int>(wp_list_.size())
                         ? static_cast<uint8_t>(wp_orig_idx_[wp_active_idx_])
                         : static_cast<uint8_t>(wp_window_size_);
  }
  wp_progress_pub_.publish(msg);
  ROS_INFO("[DiffReplanFSM] wp_progress batch_id=%u consumed=%d active=%d all=%d", wp_batch_id_, msg.consumed_count,
           msg.active_idx, (int)all_consumed);
}

void DiffReplanFSM::publishPlannerResult(const Eigen::Vector3d& goal, bool plan_status, bool modify_status,
                                         bool exec_finished) {
  quadrotor_msgs::PlannerResult msg;
  msg.planner_goal.x = goal.x();
  msg.planner_goal.y = goal.y();
  msg.planner_goal.z = goal.z();
  msg.plan_times = wp_plan_count_;
  msg.plan_status = plan_status;
  msg.modify_status = modify_status;
  plan_result_pub_.publish(msg);

  if (exec_finished) {
    std_msgs::Bool finish_msg;
    finish_msg.data = true;
    exec_finish_pub_.publish(finish_msg);
  }
  ROS_INFO("[DiffReplanFSM] planner_result status=%d exec_finished=%d goal=(%.3f %.3f %.3f)", (int)plan_status,
           (int)exec_finished, msg.planner_goal.x, msg.planner_goal.y, msg.planner_goal.z);
}

void DiffReplanFSM::updateWaypointProgress() {
  if (!has_window_ || wp_active_idx_ >= static_cast<int>(wp_list_.size()))
    return;
  const bool last = (wp_active_idx_ == static_cast<int>(wp_list_.size()) - 1);
  const Eigen::Vector3d& tgt = wp_list_[wp_active_idx_];
  const double dist = (odom_pos_ - tgt).norm();
  bool reached = dist < (last ? goal_reach_radius_ : wp_reach_radius_);
  if (!reached && !last) {
    /* Pass-by: crossed the waypoint's plane along the travel direction with
     * bounded lateral error (mirrors SUPER consumption rules). */
    const Eigen::Vector3d dir = (wp_list_[wp_active_idx_ + 1] - tgt).normalized();
    const Eigen::Vector3d rel = odom_pos_ - tgt;
    const double along = rel.dot(dir);
    const double lateral = (rel - along * dir).norm();
    reached = along > 0.0 && lateral < wp_passby_lateral_;
  }
  if (!reached)
    return;
  wp_active_idx_++;
  if (wp_active_idx_ < static_cast<int>(wp_list_.size())) {
    publishWaypointProgress(false);
  } else {
    publishWaypointProgress(true);
    has_window_ = false;
  }
}

void DiffReplanFSM::waypointCallback(const quadrotor_msgs::LocalGoalSetConstPtr& msg) {
  /* Waypoint window: flattened xyz (1 to 3 points, travel order); a window of
   * size 1 IS a single-goal message (the final waypoint is the batch goal).
   * Yaw fields are not used by this backend. */
  std::vector<Eigen::Vector3d> raw_wps;
  for (size_t i = 0; i + 2 < msg->waypoints.size(); i += 3)
    raw_wps.emplace_back(msg->waypoints[i], msg->waypoints[i + 1], msg->waypoints[i + 2]);
  if (raw_wps.empty()) {
    ROS_WARN("Received goal with empty waypoint window, ignore this goal!");
    return;
  }

  if (planner_manager_->grid_map_->getInflateOccupancy(raw_wps.back()) == -1) {
    ROS_WARN("The goal is outside the safe fence, ignore this goal!");
    return;
  }

  /* Drop leading waypoints the drone is already on top of (mirror SUPER), keeping
   * the original window indices for progress reporting. */
  wp_list_.clear();
  wp_orig_idx_.clear();
  for (size_t i = 0; i < raw_wps.size(); ++i) {
    wp_list_.push_back(raw_wps[i]);
    wp_orig_idx_.push_back(static_cast<int>(i));
  }
  while (wp_list_.size() > 1 && (odom_pos_ - wp_list_.front()).norm() < wp_reach_radius_) {
    wp_list_.erase(wp_list_.begin());
    wp_orig_idx_.erase(wp_orig_idx_.begin());
  }
  wp_batch_id_ = msg->batch_id;
  wp_window_size_ = static_cast<int>(raw_wps.size());
  wp_active_idx_ = 0;
  has_window_ = true;
  wp_flow_active_ = true;
  wp_plan_count_ = 0;

  for (const auto& wp : wp_list_)
    ROS_INFO("Received goal: %f, %f, %f", wp(0), wp(1), wp(2));

  if (planNextWaypointWindow(wp_list_, true)) {
    last_target_change_time_ = ros::Time::now().toSec();
    have_trigger_ = true;
    publishPlannerResult(raw_wps.back(), true, false, false); // ack: window accepted
  } else {
    has_window_ = false;
    publishPlannerResult(raw_wps.back(), false, false, true); // unreachable: batch dropped
  }
}

bool DiffReplanFSM::mondifyInCollisionFinalGoal() {
  if (planner_manager_->grid_map_->getBiggerInflateOccupancy(final_goal_)) {
    Eigen::Vector3d orig_goal = final_goal_;
    double t_step = planner_manager_->grid_map_->getResolution() / planner_manager_->pp_.max_vel_;
    for (double t = planner_manager_->traj_.global_traj.duration; t > 0; t -= t_step) {
      Eigen::Vector3d pt = planner_manager_->traj_.global_traj.traj.getPos(t);
      if (!planner_manager_->grid_map_->getBiggerInflateOccupancy(pt)) {
        for (int i = 6; i > 0; i--) {
          if (t - i * t_step > 0) {
            Eigen::Vector3d pt_tmp = planner_manager_->traj_.global_traj.traj.getPos(t - i * t_step);
            if (!planner_manager_->grid_map_->getBiggerInflateOccupancy(pt_tmp)) {
              pt = pt_tmp;
              break;
            }
          }
        }
        if (planNextWaypoint(pt, false)) // final_goal_=pt inside if success
        {
          ROS_INFO("Current in-collision waypoint (%.3f, %.3f %.3f) has been modified to (%.3f, %.3f %.3f)",
                   orig_goal(0), orig_goal(1), orig_goal(2), final_goal_(0), final_goal_(1), final_goal_(2));
          return true;
        }
      }

      if (t <= t_step) {
        ROS_ERROR("Can't find any collision-free point on global traj.");
      }
    }
  }

  return false;
}

void DiffReplanFSM::readGivenWpsAndPlan() {
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
    visualization_->displayGoalPoint(wps_[i], Eigen::Vector4d(0, 0.5, 0.5, 1), 0.3, i);
    ros::Duration(0.001).sleep();
  }

  // plan first global waypoint
  wpt_id_ = 0;
  wp_flow_active_ = false; // preset flow: no mission feedback reporting
  planNextWaypoint(wps_[wpt_id_], true);
}

void DiffReplanFSM::mandatoryStopCallback(const std_msgs::Empty& msg) {
  mandatory_stop_ = true;
  ROS_ERROR("Received a mandatory stop command!");
  changeFSMExecState(EMERGENCY_STOP, "Mandatory Stop");
  enable_fail_safe_ = false;
}

/* Planner Reset Contract: back to WAIT_TARGET, drop the pending target, and
 * brake on the spot (stop trajectory) until a new goal arrives. */
bool DiffReplanFSM::resetServiceCallback(std_srvs::Trigger::Request&, std_srvs::Trigger::Response& res) {
  have_target_ = false;
  have_trigger_ = false;
  have_new_target_ = false;
  catch_goal_ = false;
  wp_flow_active_ = false; // no stale batch-boundary reports after reset
  if (have_odom_)
    callEmergencyStop(odom_pos_);
  changeFSMExecState(WAIT_TARGET, "reset");
  res.success = true;
  res.message = "planner reset to WAIT_TARGET";
  return true;
}

void DiffReplanFSM::odometryCallback(const nav_msgs::OdometryConstPtr& msg) {
  odom_pos_(0) = msg->pose.pose.position.x;
  odom_pos_(1) = msg->pose.pose.position.y;
  odom_pos_(2) = msg->pose.pose.position.z;

  odom_vel_(0) = msg->twist.twist.linear.x;
  odom_vel_(1) = msg->twist.twist.linear.y;
  odom_vel_(2) = msg->twist.twist.linear.z;

  have_odom_ = true;
}

void DiffReplanFSM::triggerCallback(const geometry_msgs::PoseStampedPtr& msg) {
  have_trigger_ = true;
  cout << "Triggered!" << endl;
}

void DiffReplanFSM::RecvBroadcastMINCOTrajCallback(const traj_utils::MINCOTrajConstPtr& msg) {
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
      msg->start_time.toSec() - planner_manager_->traj_.swarm_traj[recv_id].start_time <= 0) {
    ROS_WARN("Received drone %d's trajectory out of order or duplicated, abandon it.", (int)recv_id);
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

  if (msg->start_time.toSec() <=
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
  poly_traj::MinJerkOpt MJO;
  MJO.reset(headState, tailState, piece_nums);
  MJO.generate(innerPts, durations);

  /* Ignore the trajectories that are far away */
  Eigen::MatrixXd cps_chk = MJO.getInitConstraintPoints(5); // K = 5, such accuracy is sufficient
  bool far_away = true;
  for (int i = 0; i < cps_chk.cols(); ++i) {
    if ((cps_chk.col(i) - odom_pos_).norm() <
        planner_manager_->pp_.planning_horizon_ * 4 / 3) // close to me that can not be ignored
    {
      far_away = false;
      break;
    }
  }
  if (!far_away || !have_recv_pre_agent_) // Accept a far traj if no previous agent received
  {
    poly_traj::Trajectory trajectory = MJO.getTraj();
    planner_manager_->traj_.swarm_traj[recv_id].traj = trajectory;
    planner_manager_->traj_.swarm_traj[recv_id].drone_id = recv_id;
    planner_manager_->traj_.swarm_traj[recv_id].traj_id = msg->traj_id;
    planner_manager_->traj_.swarm_traj[recv_id].start_time = msg->start_time.toSec();
    planner_manager_->traj_.swarm_traj[recv_id].duration = trajectory.getTotalDuration();
    planner_manager_->traj_.swarm_traj[recv_id].start_pos = trajectory.getPos(0.0);
    planner_manager_->traj_.swarm_traj[recv_id].des_clearance = msg->des_clearance;

    /* Check Collision */
    if (planner_manager_->checkCollision(recv_id)) {
      changeFSMExecState(REPLAN_TRAJ, "SWARM_CHECK");
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

void DiffReplanFSM::polyTraj2ROSMsg(traj_utils::PolyTraj& poly_msg, traj_utils::MINCOTraj& MINCO_msg) {

  auto data = &planner_manager_->traj_.local_traj;
  Eigen::VectorXd durs = data->traj.getDurations();
  int piece_num = data->traj.getPieceNum();

  poly_msg.drone_id = planner_manager_->pp_.drone_id;
  poly_msg.traj_id = data->traj_id;
  poly_msg.start_time = ros::Time(data->start_time);
  poly_msg.order = 5; // todo, only support order = 5 now.
  poly_msg.duration.resize(piece_num);
  poly_msg.coef_x.resize(6 * piece_num);
  poly_msg.coef_y.resize(6 * piece_num);
  poly_msg.coef_z.resize(6 * piece_num);
  for (int i = 0; i < piece_num; ++i) {
    poly_msg.duration[i] = durs(i);

    poly_traj::CoefficientMat cMat = data->traj.getPiece(i).getCoeffMat();
    int i6 = i * 6;
    for (int j = 0; j < 6; j++) {
      poly_msg.coef_x[i6 + j] = cMat(0, j);
      poly_msg.coef_y[i6 + j] = cMat(1, j);
      poly_msg.coef_z[i6 + j] = cMat(2, j);
    }
  }

  MINCO_msg.drone_id = planner_manager_->pp_.drone_id;
  MINCO_msg.traj_id = data->traj_id;
  MINCO_msg.start_time = ros::Time(data->start_time);
  MINCO_msg.order = 5; // todo, only support order = 5 now.
  MINCO_msg.duration.resize(piece_num);
  MINCO_msg.des_clearance = planner_manager_->getSwarmClearance();
  Eigen::Vector3d vec;
  vec = data->traj.getPos(0);
  MINCO_msg.start_p[0] = vec(0), MINCO_msg.start_p[1] = vec(1), MINCO_msg.start_p[2] = vec(2);
  vec = data->traj.getVel(0);
  MINCO_msg.start_v[0] = vec(0), MINCO_msg.start_v[1] = vec(1), MINCO_msg.start_v[2] = vec(2);
  vec = data->traj.getAcc(0);
  MINCO_msg.start_a[0] = vec(0), MINCO_msg.start_a[1] = vec(1), MINCO_msg.start_a[2] = vec(2);
  vec = data->traj.getPos(data->duration);
  MINCO_msg.end_p[0] = vec(0), MINCO_msg.end_p[1] = vec(1), MINCO_msg.end_p[2] = vec(2);
  vec = data->traj.getVel(data->duration);
  MINCO_msg.end_v[0] = vec(0), MINCO_msg.end_v[1] = vec(1), MINCO_msg.end_v[2] = vec(2);
  vec = data->traj.getAcc(data->duration);
  MINCO_msg.end_a[0] = vec(0), MINCO_msg.end_a[1] = vec(1), MINCO_msg.end_a[2] = vec(2);
  MINCO_msg.inner_x.resize(piece_num - 1);
  MINCO_msg.inner_y.resize(piece_num - 1);
  MINCO_msg.inner_z.resize(piece_num - 1);
  Eigen::MatrixXd pos = data->traj.getPositions();
  for (int i = 0; i < piece_num - 1; i++) {
    MINCO_msg.inner_x[i] = pos(0, i + 1);
    MINCO_msg.inner_y[i] = pos(1, i + 1);
    MINCO_msg.inner_z[i] = pos(2, i + 1);
  }
  for (int i = 0; i < piece_num; i++)
    MINCO_msg.duration[i] = durs[i];
}

/**
 * Publish the canonical trajectory topics (ground-station-channels.spec.md
 * §2.5): /planner/optimized_traj (piecewise polynomial, ascending power) and
 * /planner/search_path (raw A* search result), remapped to
 * /drone_<id>/planner/* at launch. Fed from the SAME objects as the
 * PolyTraj/MINCOTraj broadcast — no separate computation.
 */
void DiffReplanFSM::PublishCanonicalTrajectory() {
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
}

bool DiffReplanFSM::measureGroundHeight(double& height) {
  if (planner_manager_->traj_.local_traj.pts_chk.size() < 3) // means planning have not started
  {
    return false;
  }

  auto traj = &planner_manager_->traj_.local_traj;
  auto map = planner_manager_->grid_map_;
  ros::Time t_now = ros::Time::now();

  double forward_t = 2.0 / planner_manager_->pp_.max_vel_; // 2.0m
  double traj_t = (t_now.toSec() - traj->start_time) + forward_t;
  if (traj_t <= traj->duration) {
    Eigen::Vector3d forward_p = traj->traj.getPos(traj_t);

    double reso = map->getResolution();
    for (;; forward_p(2) -= reso) {
      int ret = map->getOccupancy(forward_p);
      if (ret == -1) // reach map bottom
      {
        return false;
      }
      if (ret == 1) // reach the ground
      {
        height = forward_p(2);

        std_msgs::Float64 height_msg;
        height_msg.data = height;
        ground_height_pub_.publish(height_msg);

        return true;
      }
    }
  }

  return false;
}
Eigen::Vector3d DiffReplanFSM::projectPointToLineSegment(const Eigen::Vector3d& a, const Eigen::Vector3d& b,
                                                         const Eigen::Vector3d& p) {
  double t = 0.0;
  Eigen::Vector3d ab = b - a;
  double ab2 = ab.squaredNorm();
  double ab_norm = ab.norm();
  if (ab2 < 1e-8) {
    t = 0.0;
    return a;
  }
  t = (p - a).dot(ab) / ab2;
  if (t < 0.0) {
    t = 0.0;
    return a;
  } else if (t > 1.0) {
    t = 1.0;
    return b;
  }
  return a + t * ab;
}
} // namespace diff_planner
