/**
 * This file is part of SUPER
 *
 * Copyright 2025 Yunfan REN, MaRS Lab, University of Hong Kong, <mars.hku.hk>
 * Developed by Yunfan REN <renyf at connect dot hku dot hk>
 * for more information see <https://github.com/hku-mars/SUPER>.
 * If you use this code, please cite the respective publications as
 * listed on the above website.
 *
 * SUPER is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * SUPER is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with SUPER. If not, see <http://www.gnu.org/licenses/>.
 */

#ifndef SRC_FSM_ROS1_HPP
#define SRC_FSM_ROS1_HPP

#include "fsm/fsm.h"

#include <algorithm>

#include "ros/ros.h"
#include "std_srvs/Trigger.h"
#include "nav_msgs/Path.h"
#include "nav_msgs/Odometry.h"
#include "geometry_msgs/PoseStamped.h"
#include "std_msgs/Bool.h"
#include "visualization_msgs/Marker.h"
#include "quadrotor_msgs/PlannerResult.h"
#include "quadrotor_msgs/PositionCommand.h"
#include "quadrotor_msgs/LocalGoalSet.h"
#include "quadrotor_msgs/WaypointProgress.h"
#include "vis_utils/camera_fov.h"
namespace super_planner {
namespace fsm {
class FsmRos1 : public Fsm {
  ros::NodeHandle nh_;
  ros::Subscriber goal_sub_, traj_start_trigger_sub_;
  ros::ServiceServer reset_srv_;
  ros::Publisher cmd_pub, path_pub_, plan_result_pub_, exec_finish_pub_, wp_progress_pub_, fsm_state_pub_;
  ros::Timer execution_timer_, replan_timer_, cmd_timer_;
  quadrotor_msgs::PositionCommand pid_cmd_;
  quadrotor_msgs::LocalGoalSet latest_goal_;
  super_planner::rog_map::ROGMap::Ptr map_ptr_;
  vis_utils::PerceptionUtils::Ptr percep_utils_;
  quadrotor_msgs::PositionCommand latest_cmd;

  /* yaw-only turn: optimized yaw trajectory generated once per YAWING
   * session from the live odometry heading (shortest circle path, see
   * SuperPlanner::generateYawOnlyTraj). Re-generated when the goal
   * changes or the previous trajectory expired. */
  Trajectory yaw_only_traj_;
  bool yaw_only_traj_valid_{false};
  double yaw_only_goal_{0.0};
  double yaw_only_traj_gen_WT_{0.0};

  Vec3f latest_attitude_;
  nav_msgs::Path path;
  int16_t plan_count_{0};
  bool prev_on_backup_traj_{false};
  std::shared_ptr<super_planner::ros_interface::Ros1Interface> ros1_ptr_;

  void recordCommand(const quadrotor_msgs::PositionCommand& cmd) {
    if (ros1_ptr_) {
      ros1_ptr_->recordCommand(cmd);
    }
  }

  void publishMissionFeedback(bool plan_status, bool modify_status, bool exec_finished) {
    quadrotor_msgs::PlannerResult plan_msg;
    /* The batch goal is the final waypoint of the latest window. */
    const std::vector<float>& wps = latest_goal_.waypoints;
    if (wps.size() >= 3) {
      plan_msg.planner_goal.x = wps[wps.size() - 3];
      plan_msg.planner_goal.y = wps[wps.size() - 2];
      plan_msg.planner_goal.z = wps[wps.size() - 1];
    }
    plan_msg.plan_times = plan_count_;
    plan_msg.plan_status = plan_status;
    plan_msg.modify_status = modify_status;
    plan_result_pub_.publish(plan_msg);

    std_msgs::Bool finish_msg;
    finish_msg.data = exec_finished;
    exec_finish_pub_.publish(finish_msg);
    SLOG_EVENT(slog::Level::info, "super_feedback",
               {
                   slog::F("plan_status", plan_status),
                   slog::F("modify_status", modify_status),
                   slog::F("exec_finished", exec_finished),
                   slog::F("goal", fmt::format("[{:.3f} {:.3f} {:.3f}]", plan_msg.planner_goal.x,
                                               plan_msg.planner_goal.y, plan_msg.planner_goal.z)),
               });
  }

  /* Goal-unreachable escalation: tell the mission layer the goal failed.
   * exec_finished=true so the mission FSM can advance even without a
   * successful trajectory completion (it will re-plan or skip). */
  void publishMissionFailure() override { publishMissionFeedback(false, false, true); }

  /* Called when the drone is already at the goal during GENERATE_TRAJ:
   * publish exec_finished so the mission layer knows this goal was reached
   * and can advance to the next waypoint. */
  void onGoalConsumedAtRest() override { publishMissionFeedback(true, true, true); }

  void resetVisualizedPath() override { path.poses.clear(); }

  void publishWaypointProgress(bool all_consumed) override {
    quadrotor_msgs::WaypointProgress msg;
    msg.batch_id = gi_.batch_id;
    msg.skipped_mask = gi_.wp_skipped_mask;
    msg.all_consumed = all_consumed;
    if (all_consumed) {
      msg.consumed_count = static_cast<uint8_t>(gi_.wp_window_size);
      msg.active_idx = static_cast<uint8_t>(gi_.wp_window_size);
    } else {
      msg.consumed_count = gi_.wp_active_idx > 0 ? static_cast<uint8_t>(gi_.wp_orig_idx[gi_.wp_active_idx - 1] + 1) : 0;
      msg.active_idx = gi_.wp_active_idx < static_cast<int>(gi_.wp_list.size())
                           ? static_cast<uint8_t>(gi_.wp_orig_idx[gi_.wp_active_idx])
                           : static_cast<uint8_t>(gi_.wp_window_size);
    }
    wp_progress_pub_.publish(msg);
    SLOG_EVENT(slog::Level::info, "wp_progress_pub",
               {
                   slog::F("batch_id", msg.batch_id),
                   slog::F("consumed", msg.consumed_count),
                   slog::F("active", msg.active_idx),
                   slog::F("skipped_mask", static_cast<unsigned int>(msg.skipped_mask)),
                   slog::F("all_consumed", static_cast<bool>(msg.all_consumed)),
               });
  }

  void publishCurPoseToPath() override {
    path.header.frame_id = "world";
    path.header.stamp = ros::Time::now();
    geometry_msgs::PoseStamped pose;
    pose.header = path.header;
    pose.pose.position.x = robot_state_.p(0);
    pose.pose.position.y = robot_state_.p(1);
    pose.pose.position.z = robot_state_.p(2);
    pose.pose.orientation.x = robot_state_.q.x();
    pose.pose.orientation.y = robot_state_.q.y();
    pose.pose.orientation.z = robot_state_.q.z();
    pose.pose.orientation.w = robot_state_.q.w();
    path.poses.push_back(pose);
    path_pub_.publish(path);
  }

  void getOnePositionCommand(quadrotor_msgs::PositionCommand& pos_cmd, bool& traj_finish) {
    pos_cmd.trajectory_flag = 0;
    StatePVAJ pvaj;
    double yaw, yaw_dot;
    bool on_backup_traj;
    planner_ptr_->getOneCommandFromTraj(pvaj, yaw, yaw_dot, on_backup_traj, traj_finish);
    while (yaw > M_PI)
      yaw -= 2 * M_PI;
    while (yaw < -M_PI)
      yaw += 2 * M_PI;
    pos_cmd.header.stamp = ros::Time::now();
    pos_cmd.header.frame_id = "world";
    pos_cmd.position.x = pvaj(0, 0);
    pos_cmd.position.y = pvaj(1, 0);
    pos_cmd.position.z = pvaj(2, 0);
    pos_cmd.velocity.x = pvaj(0, 1);
    pos_cmd.velocity.y = pvaj(1, 1);
    pos_cmd.velocity.z = pvaj(2, 1);
    pos_cmd.acceleration.x = pvaj(0, 2);
    pos_cmd.acceleration.y = pvaj(1, 2);
    pos_cmd.acceleration.z = pvaj(2, 2);
    pos_cmd.jerk.x = pvaj(0, 3);
    pos_cmd.jerk.y = pvaj(1, 3);
    pos_cmd.jerk.z = pvaj(2, 3);
    pos_cmd.yaw = yaw;
    pos_cmd.yaw_dot = yaw_dot;
    pos_cmd.trajectory_flag = on_backup_traj ? 2 : 1;
    Vec3f rpy, omg;
    double aT;
    super_planner::geometry_utils::convertFlatOutputToAttAndOmg(pvaj.col(0), pvaj.col(1), pvaj.col(2), pvaj.col(3), yaw,
                                                                yaw_dot, rpy, omg, aT);
    latest_attitude_ = rpy;
    latest_cmd = pos_cmd;
    if (on_backup_traj && !prev_on_backup_traj_) {
      SLOG_EVENT(slog::Level::warn, "backup_traj_triggered", {});
      keyframe_pending_ = true;
    } else if (!on_backup_traj && prev_on_backup_traj_) {
      SLOG_EVENT(slog::Level::info, "backup_traj_exited", {});
      keyframe_pending_ = true;
    }
    prev_on_backup_traj_ = on_backup_traj;
  }

public:
  FsmRos1() = default;

  ~FsmRos1() {
    ros::shutdown();
    exit(0);
  };

  typedef std::shared_ptr<FsmRos1> Ptr;

  bool getPoseFromTraj(super_planner::super_utils::Pose& pose) {
    if (machine_state_ != FOLLOW_TRAJ) {
      SLOG_WARN("[Fsm] Not in FOLLOW_TRAJ state, can't get pose from traj.");
      return false;
    }
    getOnePositionCommand(pid_cmd_, traj_finish_);
    if (traj_finish_) {
      SLOG_INFO(" -- [Fsm] Traj finish.");
      if (closeToGoal(cfg_.goal_reach_radius)) {
        goal_unfinish_count_ = 0;
        if (consumeArrivedWaypoint()) {
          ChangeState("getPoseFromTraj", WAIT_TARGET);
        } else {
          ChangeState("getPoseFromTraj", GENERATE_TRAJ);
        }
      } else {
        goal_unfinish_count_++;
        if (goal_unfinish_count_ >= cfg_.goal_unreachable_max_unfinish) {
          declareGoalUnreachable("traj_finish_far");
        } else {
          ChangeState("getPoseFromTraj", GENERATE_TRAJ);
        }
      }
    }
    pose.first = Vec3f{pid_cmd_.position.x, pid_cmd_.position.y, pid_cmd_.position.z};
    pose.second = eulerToQuaternion(latest_attitude_(0), latest_attitude_(1), latest_attitude_(2));

    /// for checking the trajectory continuty
    static int call_cnt{0};
    call_cnt++;
    double cur_vel_norm =
        std::sqrt(pid_cmd_.velocity.x * pid_cmd_.velocity.x + pid_cmd_.velocity.y * pid_cmd_.velocity.y +
                  pid_cmd_.velocity.z * pid_cmd_.velocity.z);
    static double last_v = cur_vel_norm;
    double delta_v = std::abs(cur_vel_norm - last_v);
    last_v = cur_vel_norm;
    static double max_delta_v{0.0};
    if (delta_v > max_delta_v) {
      max_delta_v = delta_v;
    }
    SLOG_DEBUG(" -- [Fsm] Cur vel: {}, delta_v: {}, max_delta_v: {}", cur_vel_norm, delta_v, max_delta_v);
    return true;
  }

  void processGoal(const quadrotor_msgs::LocalGoalSet& msg) {
    latest_goal_ = msg;
    ++plan_count_;
    /* The batch goal is the final waypoint of the window (size 1 = single
     * goal); legacy single-goal fallback (no waypoints) degrades to zero. */
    super_planner::super_utils::Vec3f goal_p{0.0f, 0.0f, 0.0f};
    if (msg.waypoints.size() >= 3) {
      goal_p = Vec3f{msg.waypoints[msg.waypoints.size() - 3], msg.waypoints[msg.waypoints.size() - 2],
                     msg.waypoints[msg.waypoints.size() - 1]};
    }

    double yaw = msg.yaw;
    int yaw_mode = msg.yaw_mode;
    int yaw_path_mode = msg.yaw_path_mode;

    if (yaw_path_mode == quadrotor_msgs::LocalGoalSet::YAW_PATH_SHORTEST) {
      while (yaw > M_PI)
        yaw -= 2 * M_PI;
      while (yaw < -M_PI)
        yaw += 2 * M_PI;
    }

    if (yaw_mode == quadrotor_msgs::LocalGoalSet::YAW_MODE_NORMAL && msg.yaw_low_speed) {
      yaw_mode = quadrotor_msgs::LocalGoalSet::YAW_MODE_LOW_SPEED;
    }

    const bool panorama_source_allowed = msg.source_task_id == quadrotor_msgs::LocalGoalSet::SOURCE_TASK_EXPLORATION ||
                                         msg.source_task_id == quadrotor_msgs::LocalGoalSet::SOURCE_TASK_COUNTING;
    if (yaw_mode == quadrotor_msgs::LocalGoalSet::YAW_MODE_PANORAMA && !panorama_source_allowed) {
      SLOG_WARN("[SUPER] Reject panorama mode from source_task_id={}, fallback to NORMAL + SHORTEST.",
                static_cast<unsigned int>(msg.source_task_id));
      yaw_mode = quadrotor_msgs::LocalGoalSet::YAW_MODE_NORMAL;
      yaw_path_mode = quadrotor_msgs::LocalGoalSet::YAW_PATH_SHORTEST;
      while (yaw > M_PI)
        yaw -= 2 * M_PI;
      while (yaw < -M_PI)
        yaw += 2 * M_PI;
    }

    super_planner::super_utils::Quatf goal_q(Eigen::AngleAxisd(yaw, Eigen::Vector3d::UnitZ()));
    publishMissionFeedback(true, true, false);

    /* Waypoint window: waypoints is a flattened xyz array (at most 3 points in
     * travel order). Non-empty => multi-goal batch with SUPER-internal progress. */
    const size_t n_floats = msg.waypoints.size();
    if (n_floats >= 3 && n_floats % 3 == 0) {
      std::vector<Vec3f> raw_wps;
      const size_t n_wp = std::min<size_t>(n_floats / 3, 3);
      raw_wps.reserve(n_wp);
      for (size_t i = 0; i < n_wp; i++) {
        raw_wps.emplace_back(msg.waypoints[3 * i], msg.waypoints[3 * i + 1], msg.waypoints[3 * i + 2]);
      }
      if (setGoalWindow(msg.batch_id, raw_wps, goal_q, yaw_mode, yaw_path_mode, msg.look_forward)) {
        return;
      }
    }
    /* Legacy single-goal path: no active window. */
    gi_.wp_list.clear();
    gi_.wp_orig_idx.clear();
    planner_ptr_->setWaypointLookahead({});
    setGoalPosiAndYaw(goal_p, goal_q, yaw_mode, yaw_path_mode, msg.look_forward);
  }

  void goalCallback(const quadrotor_msgs::LocalGoalSetConstPtr& msg) {
    if (cfg_.traj_start_trigger_en && waiting_traj_start_trigger_) {
      /* Batch goal = final waypoint of the window. */
      std::string goal_str = "[0.000 0.000 0.000]";
      if (msg->waypoints.size() >= 3) {
        goal_str = fmt::format("[{:.3f} {:.3f} {:.3f}]", msg->waypoints[msg->waypoints.size() - 3],
                               msg->waypoints[msg->waypoints.size() - 2], msg->waypoints[msg->waypoints.size() - 1]);
      }
      SLOG_EVENT(slog::Level::warn, "local_goal_blocked",
                 {slog::F("reason", "wait_traj_start_trigger"), slog::F("topic", cfg_.traj_start_trigger_topic),
                  slog::F("goal", goal_str)});
      return;
    }
    processGoal(*msg);
  }

  /* Planner Reset Contract: only flag the request; the FSM main loop
   * consumes it (handleReset) on its own thread. */
  bool resetServiceCallback(std_srvs::Trigger::Request&, std_srvs::Trigger::Response& res) {
    yaw_only_traj_valid_ = false; /* FsmRos1-local; cleared on FSM thread too */
    requestReset();
    res.success = true;
    res.message = "reset requested (consumed by FSM loop)";
    return true;
  }

  void trajStartTriggerCallback(const geometry_msgs::PoseStampedConstPtr&) {
    waiting_traj_start_trigger_ = false;
    /* In-place /agent/stack_reset re-arms and re-publishes this one-shot
     * trigger; the odometry yaw has just snapped back to the launch
     * heading, so re-sync the online yaw integrator from odometry
     * (otherwise the yaw command keeps the pre-reset value, diverging
     * ~180 deg from the real heading and dragging the drone down). */
    planner_ptr_->resetOnlineYaw();
    SLOG_EVENT(slog::Level::warn, "traj_start_trigger", {});
  }

  void init(const ros::NodeHandle& nh, const std::string& cfg_path) {
    // 初始化参数读取
    nh_ = nh;
    cfg_ = Config(cfg_path);
    map_ptr_ = std::make_shared<super_planner::rog_map::ROGMapROS>(nh, cfg_path);
    // 初始化Planner
    ros1_ptr_ = std::make_shared<super_planner::ros_interface::Ros1Interface>(nh_);
    ros_ptr_ = ros1_ptr_;
    ros1_ptr_->initTelemetry(cfg_.telemetry_level, cfg_.telemetry_stdout_en, cfg_.telemetry_mcap_en,
                             cfg_.telemetry_mcap_dir);
    planner_ptr_ = std::make_shared<SuperPlanner>(cfg_path, ros_ptr_, map_ptr_);
    cmd_pub = nh_.advertise<quadrotor_msgs::PositionCommand>(cfg_.cmd_topic, 10);
    path_pub_ = nh_.advertise<nav_msgs::Path>("fsm/path", 100);
    fsm_state_pub_ = nh_.advertise<visualization_msgs::Marker>("visualization/fsm_state", 1);

    // camera_fov params for FOV visualization
    nh_.setParam("camera_fov/top_angle", 0.6);
    nh_.setParam("camera_fov/left_angle", 0.76);
    nh_.setParam("camera_fov/right_angle", 0.76);
    nh_.setParam("camera_fov/max_dist", 6.0);
    nh_.setParam("camera_fov/vis_dist", 1.0);
    percep_utils_ = std::make_shared<vis_utils::PerceptionUtils>(nh_);
    plan_result_pub_ = nh_.advertise<quadrotor_msgs::PlannerResult>("/planning/planner_result", 10);
    exec_finish_pub_ = nh_.advertise<std_msgs::Bool>("/drone_0_mission_executive/exec_finish_trigger", 10);
    wp_progress_pub_ =
        nh_.advertise<quadrotor_msgs::WaypointProgress>("/drone_0_ego_planner_node/waypoint_progress", 10);

    int cmd_cnt = 0;

    if (cfg_.click_goal_en) {
      goal_sub_ = nh_.subscribe(cfg_.click_goal_topic, 1, &FsmRos1::goalCallback, this);
      SLOG_WARN(" -- [Fsm] CLICKGOAL ENABLE.");
      cmd_cnt++;
    }

    if (cfg_.traj_start_trigger_en) {
      traj_start_trigger_sub_ =
          nh_.subscribe(cfg_.traj_start_trigger_topic, 1, &FsmRos1::trajStartTriggerCallback, this);
      SLOG_WARN(" -- [Fsm] TRAJ_START_TRIGGER ENABLE: {}", cfg_.traj_start_trigger_topic);
    }

    /* Planner Reset Contract (std_srvs/Trigger, fixed name shared by
     * every backend since they run mutually exclusively). */
    reset_srv_ = nh_.advertiseService("/planner/reset", &FsmRos1::resetServiceCallback, this);

    if (cmd_cnt != 1) {
      SLOG_ERROR(" -- [Fsm] CMD INPUT ERROR.");
      exit(0);
    }

    if (cfg_.timer_en) {
      execution_timer_ = nh_.createTimer(ros::Duration(0.01), &FsmRos1::mainFsmTimerCallback, this); // 100Hz
      cmd_timer_ = nh_.createTimer(ros::Duration(0.01), &FsmRos1::pubCmdTimerCallback, this);        // 100Hz
      replan_timer_ = nh_.createTimer(ros::Duration(1.0 / cfg_.replan_rate), &FsmRos1::replanTimerCallback,
                                      this); // 10Hz
    }

    machine_state_ = INIT;
    system_start_time_ = ros_ptr_->getSimTime();

    pid_cmd_.kx[0] = 5.7;
    pid_cmd_.kx[1] = 5.7;
    pid_cmd_.kx[2] = 4.2;

    pid_cmd_.kv[0] = 3.4;
    pid_cmd_.kv[1] = 3.4;
    pid_cmd_.kv[2] = 4.0;
  }

  void pubCmdTimerCallback(const ros::TimerEvent& event) {
    if (stop) {
      return;
    }
    if (machine_state_ != FOLLOW_TRAJ && machine_state_ != YAWING) {
      return;
    }

    /* YAWING: hover at the live odometry position (velocity-damped stop
     * for mid-flight entries), transition yaw via the online trapezoidal
     * limiter. Never publish yaw=0 before the target is computed. */
    if (machine_state_ == YAWING) {
      double yaw = robot_state_.yaw, yaw_dot = 0.0;
      if (yaw_only_task_) {
        /* yaw-only turn: execute the yaw trajectory optimized at
         * session start from the live odometry heading (shortest
         * circle path, allocated target). Re-generate when the goal
         * changed or the trajectory expired (new turn after a
         * previous one completed). */
        if (!isnan(pre_yaw_target_)) {
          const double dur = yaw_only_traj_valid_ ? yaw_only_traj_.getTotalDuration() : 0.0;
          const bool stale = !yaw_only_traj_valid_ || std::fabs(yaw_only_goal_ - pre_yaw_target_) > 1e-6 ||
                             (ros_ptr_->getSimTime() - yaw_only_traj_gen_WT_) > dur + 0.5;
          if (stale) {
            yaw_only_traj_valid_ = planner_ptr_->generateYawOnlyTraj(pre_yaw_target_, yaw_only_goal_, yaw_only_traj_);
            if (yaw_only_traj_valid_) {
              yaw_only_traj_.start_WT = ros_ptr_->getSimTime();
              yaw_only_traj_gen_WT_ = ros_ptr_->getSimTime();
              /* The fsm.cpp YAWING convergence check compares
               * against pre_yaw_target_: keep it in sync with
               * the allocated (continuous) goal. */
              pre_yaw_target_ = yaw_only_goal_;
            }
          }
          if (yaw_only_traj_valid_) {
            const double eval_t = ros_ptr_->getSimTime() - yaw_only_traj_.start_WT;
            yaw = yaw_only_traj_.getPos(eval_t)[0];
            yaw_dot = yaw_only_traj_.getVel(eval_t)[0];
          }
        }
      } else if (!isnan(pre_yaw_target_)) {
        planner_ptr_->stepOnlineYaw(ros_ptr_->getSimTime(), pre_yaw_target_, yaw, yaw_dot);
      }
      pid_cmd_.header.stamp = ros::Time::now();
      pid_cmd_.header.frame_id = "world";
      pid_cmd_.position.x = robot_state_.p.x();
      pid_cmd_.position.y = robot_state_.p.y();
      pid_cmd_.position.z = robot_state_.p.z();
      pid_cmd_.velocity.x = 0.0;
      pid_cmd_.velocity.y = 0.0;
      pid_cmd_.velocity.z = 0.0;
      pid_cmd_.acceleration.x = 0.0;
      pid_cmd_.acceleration.y = 0.0;
      pid_cmd_.acceleration.z = 0.0;
      pid_cmd_.jerk.x = 0.0;
      pid_cmd_.jerk.y = 0.0;
      pid_cmd_.jerk.z = 0.0;
      pid_cmd_.yaw = yaw;
      pid_cmd_.yaw_dot = yaw_dot;
      pid_cmd_.trajectory_flag = 1;
      cmd_pub.publish(pid_cmd_);
      recordCommand(pid_cmd_);
      return;
    }

    getOnePositionCommand(pid_cmd_, traj_finish_);
    cmd_pub.publish(pid_cmd_);
    recordCommand(pid_cmd_);

    // Draw FOV at current command pose (throttled ~20Hz)
    static int fov_cnt = 0;
    if (++fov_cnt % 5 == 0) {
      Vec3f pos(pid_cmd_.position.x, pid_cmd_.position.y, pid_cmd_.position.z);
      percep_utils_->setPose(Eigen::Vector3d(pos.x(), pos.y(), pos.z()), pid_cmd_.yaw);
      std::vector<Eigen::Vector3d> l1, l2;
      percep_utils_->getFOV(l1, l2);
      auto ros1_ptr = std::dynamic_pointer_cast<super_planner::ros_interface::Ros1Interface>(ros_ptr_);
      if (ros1_ptr)
        ros1_ptr->vizFov(l1, l2);
    }

    if (traj_finish_) {
      SLOG_INFO(" -- [Fsm] Traj finish.");
      if (closeToGoal(cfg_.goal_reach_radius)) {
        goal_unfinish_count_ = 0;
        /* Window-aware completion: mid-window arrival consumes the active
         * waypoint and replans for the next; only window exhaustion (or a
         * single goal) reports exec_finished to the mission. */
        if (consumeArrivedWaypoint()) {
          publishMissionFeedback(true, true, true);
          ChangeState("PubCmdCallback", WAIT_TARGET);
        } else {
          ChangeState("PubCmdCallback", GENERATE_TRAJ);
        }
      } else {
        goal_unfinish_count_++;
        if (goal_unfinish_count_ >= cfg_.goal_unreachable_max_unfinish) {
          declareGoalUnreachable("traj_finish_far");
        } else {
          ChangeState("PubCmdCallback", GENERATE_TRAJ);
        }
      }
    }
  }

  void replanTimerCallback(const ros::TimerEvent& event) { callReplanOnce(); }

  void mainFsmTimerCallback(const ros::TimerEvent& event) {
    callMainFsmOnce();
    publishFsmStateText();
  }

  void publishFsmStateText() {
    static int cnt = 0;
    if (++cnt % 5 != 0)
      return;
    if (!robot_state_.rcv)
      return;

    visualization_msgs::Marker m;
    m.header.frame_id = "world";
    m.header.stamp = ros::Time::now();
    m.ns = "fsm_state";
    m.id = 0;
    m.type = visualization_msgs::Marker::TEXT_VIEW_FACING;
    m.action = visualization_msgs::Marker::ADD;
    m.pose.position.x = robot_state_.p.x();
    m.pose.position.y = robot_state_.p.y();
    m.pose.position.z = robot_state_.p.z() + 0.6;
    m.pose.orientation.w = 1.0;
    m.scale.z = 0.35;
    m.color.r = 1.0;
    m.color.g = 1.0;
    m.color.b = 1.0;
    m.color.a = 1.0;
    m.lifetime = ros::Duration(0.2);
    m.text = MACHINE_STATE_STR[machine_state_];
    fsm_state_pub_.publish(m);
  }
};
} // namespace fsm
} // namespace super_planner

#endif // SRC_FSM_ROS1_HPP
