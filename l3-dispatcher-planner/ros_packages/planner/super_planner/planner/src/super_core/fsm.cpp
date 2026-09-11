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

#include <fsm/fsm.h>
#include <memory>

using namespace super_planner::super_utils;
namespace super_planner {
namespace fsm {
    Fsm::~Fsm() = default;

    void Fsm::callReplanOnce() {
        if (stop) {
            return;
        }

        if (machine_state_ != FOLLOW_TRAJ) {
            return;
        }

        if (finish_plan) {
            return;
        }

        if (plan_from_rest_) {
            plan_from_rest_ = false;
            return;
        }

        /* Do NOT snap gi_.goal_p here: in-place mutation every replan cycle ratchets the
         * goal away (A* already repairs occupied/out-of-map goals into a local copy). */
        TimeConsuming replan_once_time("replan_once_time", false);

        RET_CODE ret_code = planner_ptr_->ReplanOnce(gi_.goal_p, gi_.goal_yaw, gi_.new_goal);
        bool keyframe = keyframe_pending_ || gi_.new_goal;
        keyframe_pending_ = false;
        if (ret_code == FAILED) {
            consecutive_replan_failures_++;
            planner_ptr_->notifyConsecutiveFailures(consecutive_replan_failures_);
            const double dist_to_goal = (robot_state_.p - gi_.goal_p).norm();
            keyframe = true;
            SLOG_EVENT(slog::Level::warn, "replan_failed", {
                    slog::F("state", MACHINE_STATE_STR[machine_state_]),
                    slog::F("consecutive_failures", consecutive_replan_failures_),
                    slog::F("dist_to_goal", dist_to_goal),
                    slog::F("pos", fmt::format("{}", robot_state_.p.transpose())),
                    slog::F("goal", fmt::format("{}", gi_.goal_p.transpose())),
                    slog::F("vel_norm", robot_state_.v.norm()),
            });
        } else {
            consecutive_replan_failures_ = 0;
            SLOG_DEBUG(" -- [Fsm] ReplanOnce succeed.");
        }
        if (ret_code == SUCCESS || ret_code == FINISH) {
            gi_.new_goal = false;

            if (cfg_.pre_yaw_replan_en) {
                /* Mid-flight stop-yaw trigger: compare the committed trajectory's
                 * tangent heading at the current time with the drone's yaw (x-axis
                 * horizontal projection). When the trajectory turns faster than the
                 * yaw can follow, brake to a hover and turn in place; a fresh
                 * trajectory is generated after convergence. */
                const double tgt = planner_ptr_->getTrajTangentYawNow();
                if (!isnan(tgt)) {
                    double e = tgt - robot_state_.yaw;
                    while (e > M_PI) e -= 2 * M_PI;
                    while (e < -M_PI) e += 2 * M_PI;
                    if (fabs(e) > cfg_.yaw_replan_threshold_deg * M_PI / 180.0) {
                        SLOG_EVENT(slog::Level::debug, "tangent_yaw_mismatch", {
                                slog::F("err_deg", fabs(e) * 57.3),
                        });
                        /* Mid-flight stop-yaw: the trajectory was hot-stitched
                         * from the previous one, not generated from rest — after
                         * yaw convergence re-plan from the actual hover state. */
                        yaw_from_rest_ = false;
                        pre_yaw_target_ = NAN;
                        pre_yaw_start_time_ = ros_ptr_->getSimTime();
                        ChangeState("ReplanTimerCallback:tangent_mismatch", YAWING);
                    }
                }
            }
        }

        const bool ambient = (++ambient_cnt_ % std::max(1, cfg_.telemetry_marker_decimation)) == 0;
        planner_ptr_->getLatestReplanLog().record(ros_ptr_, keyframe, ambient);
    }

    void Fsm::callMainFsmOnce() {
        if (stop) {
            return;
        }
        if (reset_requested_) {
            reset_requested_ = false;
            handleReset();
        }
        static double fsm_start_time = ros_ptr_->getSimTime();
        double cur_t = (ros_ptr_->getSimTime() - fsm_start_time);
        static double last_print_t = 0.0;
        planner_ptr_->getRobotState(robot_state_);


        if (cur_t - last_print_t > 1.0) {
            last_print_t = cur_t;
            if ((!robot_state_.rcv || (ros_ptr_->getSimTime() - robot_state_.rcv_time) > 0.1)) {
                SLOG_WARN(" -- [Fsm] No odom.");
                return;
            }
            if (waiting_traj_start_trigger_) {
                SLOG_WARN(" -- [Fsm][WARN] Wait for traj_start_trigger.");
            } else if (!started_) {
                SLOG_WARN(" -- [Fsm][WARN] Wait for goal.");
            }
            SLOG_INFO(" -- [Fsm {:.3f}] Current state: {}", cur_t, MACHINE_STATE_STR[machine_state_]);
        }

        switch (machine_state_) {
            case INIT: {
                if (!started_) {
                    return;
                }
                if ((!robot_state_.rcv || (ros_ptr_->getSimTime() - robot_state_.rcv_time) > 0.1)) {
                    SLOG_WARN(" -- [Fsm] No odom.");
                }
                ChangeState("MainFsmCallback", WAIT_TARGET);
                break;
            }
            case WAIT_TARGET: {
                if (!gi_.new_goal) {
                    return;
                } else {
                    ChangeState("MainFsmCallback", GENERATE_TRAJ);
                }
                resetVisualizedPath();
                break;
            }
            case GENERATE_TRAJ: {
                /* Already-arrived check at plan time: intermediate window waypoints
                 * use wp_reach_radius, the final waypoint (or a single goal) uses
                 * goal_reach_radius. */
                const bool final_wp = gi_.wp_list.empty() ||
                                      gi_.wp_active_idx >= static_cast<int>(gi_.wp_list.size()) - 1;
                const double reach_radius = final_wp ? cfg_.goal_reach_radius : cfg_.wp_reach_radius;
                if (closeToGoal(reach_radius)) {
                    /* Yaw-only turn: position already reached but the goal yaw
                     * differs. Turn in place via YAWING (pre_yaw_target_ =
                     * goal_yaw; pubCmdTimerCallback hovers + steps yaw), then
                     * consume the goal at rest once the yaw converges. */
                    const double yaw_tol = cfg_.yaw_pre_tolerance_deg * M_PI / 180.0;
                    auto wrap_pi = [](double a) {
                        while (a > M_PI) a -= 2.0 * M_PI;
                        while (a <= -M_PI) a += 2.0 * M_PI;
                        return a;
                    };
                    const bool yaw_required =
                        !isnan(gi_.goal_yaw) &&
                        fabs(wrap_pi(gi_.goal_yaw - robot_state_.yaw)) > yaw_tol;
                    if (yaw_required) {
                        yaw_only_task_ = true;
                        pre_yaw_target_ = gi_.goal_yaw;
                        pre_yaw_start_time_ = ros_ptr_->getSimTime();
                        yaw_from_rest_ = true;
                        ChangeState("MainFsmCallback:yaw-only", YAWING);
                        return;
                    }
                    if (consumeArrivedWaypoint()) {
                        onGoalConsumedAtRest();
                        ChangeState("MainFsmCallback", WAIT_TARGET);
                        gi_.new_goal = false;
                        finish_plan = true;
                    }
                    return;
                }
                int retcode = planner_ptr_->PlanFromRest(gi_.goal_p, gi_.goal_yaw, gi_.new_goal);
                if (!planner_ptr_->goalValid()) {
                    SLOG_WARN(" -- [Fsm] Goal is invalid, skip this goal.");
                    ChangeState("MainFsmCallback", WAIT_TARGET);
                    return;
                }
                if (retcode == SUCCESS || retcode == FINISH) {
                    gi_.new_goal = false;
                    plan_from_rest_ = true;
                    plan_from_rest_failures_ = 0;
                    finish_plan = false;
                    if (retcode == FINISH) {
                        finish_plan = true;
                    }

                    /* Enter pre-yaw from rest: trajectory is fresh, follow it
                     * directly once the yaw converges. */
                    yaw_from_rest_ = true;
                    pre_yaw_target_ = NAN;
                    pre_yaw_start_time_ = ros_ptr_->getSimTime();

                    ChangeState("MainFsmCallback", YAWING);
                } else {
                    SLOG_WARN(" -- [Fsm] PlanFromRest failed, try replan.");
                    if (++plan_from_rest_failures_ >= kPlanFromRestMaxFailures) {
                        declareGoalUnreachable("plan_from_rest_failed");
                    }
                }
                planner_ptr_->getLatestReplanLog().record(ros_ptr_, keyframe_pending_, true);
                keyframe_pending_ = false;
                break;
            }
            case YAWING: {
                /* Yaw plan + Yaw execute lifecycle.
                 * The trajectory is immutable during YAWING (replan disabled):
                 * freeze the clock so the resume point stays consistent with the
                 * frozen trajectory once yaw converges. */
                planner_ptr_->resetTrajStartWallTime(ros_ptr_->getSimTime());

                /* Yaw plan: compute the look-forward target once. */
                if (isnan(pre_yaw_target_)) {
                    pre_yaw_target_ = planner_ptr_->getPreYawTarget();
                    if (isnan(pre_yaw_target_)) {
                        /* Near-vertical segment: skip yaw. From rest the trajectory
                         * is still consistent and FOLLOW_TRAJ resumes it directly;
                         * mid-flight (hot-stitched) it must be re-planned. */
                        planner_ptr_->resetTrajStartWallTime(ros_ptr_->getSimTime());
                        pre_yaw_target_ = NAN;
                        ChangeState("MainFsmCallback:YAWING:vertical",
                                    yaw_from_rest_ ? FOLLOW_TRAJ : GENERATE_TRAJ);
                        break;
                    }
                    SLOG_INFO(" -- [SUPER][Yaw] pre_yaw_target={:.2f} deg cur_yaw={:.2f} deg",
                              pre_yaw_target_ * 57.3, robot_state_.yaw * 57.3);
                }
                /* Yaw execute: check in-place convergence via stepOnlineYaw. */
                planner_ptr_->getRobotState(robot_state_);
                double yaw_err = pre_yaw_target_ - robot_state_.yaw;
                while (yaw_err > M_PI) yaw_err -= 2 * M_PI;
                while (yaw_err < -M_PI) yaw_err += 2 * M_PI;

                if (fabs(yaw_err) < cfg_.yaw_pre_tolerance_deg * M_PI / 180.0) {
                    /* Yaw converged. From rest the frozen trajectory is
                     * consistent with the hover state: resume it directly.
                     * Mid-flight the committed trajectory is a hot-stitched
                     * continuation the drone is no longer on — re-generate from
                     * the actual hover state (GENERATE_TRAJ -> PlanFromRest ->
                     * pre-yaw of the fresh trajectory, near-zero since yaw
                     * already converged). */
                    pre_yaw_target_ = NAN;
                    if (yaw_only_task_) {
                        /* In-place turn done: consume the goal at rest. */
                        yaw_only_task_ = false;
                        onGoalConsumedAtRest();
                        ChangeState("MainFsmCallback:yaw-only:done", WAIT_TARGET);
                        gi_.new_goal = false;
                        finish_plan = true;
                        break;
                    }
                    planner_ptr_->resetTrajStartWallTime(ros_ptr_->getSimTime());
                    ChangeState("MainFsmCallback:YAWING:reached",
                                yaw_from_rest_ ? FOLLOW_TRAJ : GENERATE_TRAJ);
                }

                /* Timeout: force transition after 10 s. */
                if (ros_ptr_->getSimTime() - pre_yaw_start_time_ > 10.0) {
                    SLOG_WARN(" -- [SUPER] Pre-yaw timeout, force follow traj.");
                    if (yaw_only_task_) {
                        yaw_only_task_ = false;
                        declareGoalUnreachable("yaw_only_timeout");
                        break;
                    }
                    planner_ptr_->resetTrajStartWallTime(ros_ptr_->getSimTime());
                    pre_yaw_target_ = NAN;
                    ChangeState("MainFsmCallback:YAWING:timeout",
                                yaw_from_rest_ ? FOLLOW_TRAJ : GENERATE_TRAJ);
                }
                break;
            }
            case FOLLOW_TRAJ: {
                publishCurPoseToPath();
                updateWaypointProgress();
                logNavigationProgress();
                break;
            }
            default:
                break;
        }
    }

    void Fsm::handleReset() {
        /* Planner Reset Contract (specs/mission-planner-protocol): clear the
         * active goal / waypoint window, drop the committed trajectory so no
         * PositionCommand keeps flowing, re-sync the yaw integrator from
         * odometry, and return to the idle state. */
        gi_.new_goal = false;
        gi_.wp_list.clear();
        gi_.wp_orig_idx.clear();
        gi_.wp_skipped_mask = 0;
        gi_.wp_window_size = 0;
        gi_.wp_active_idx = 0;
        gi_.pending_goal_yaw = NAN;
        planner_ptr_->setWaypointLookahead({});
        planner_ptr_->clearCommittedTraj();
        yaw_only_task_ = false;
        pre_yaw_target_ = NAN;
        planner_ptr_->resetOnlineYaw();
        ChangeState("handleReset", WAIT_TARGET);
        SLOG_EVENT(slog::Level::warn, "planner_reset", {
                slog::F("state", MACHINE_STATE_STR[machine_state_]),
        });
    }

    void Fsm::declareGoalUnreachable(const std::string &reason) {
        const double dist_to_goal = (robot_state_.p - gi_.goal_p).norm();
        SLOG_EVENT(slog::Level::warn, "goal_unreachable", {
                slog::F("reason", reason),
                slog::F("dist_to_goal", dist_to_goal),
                slog::F("pos", fmt::format("{}", robot_state_.p.transpose())),
                slog::F("goal", fmt::format("{}", gi_.goal_p.transpose())),
                slog::F("goal_unfinish_count", goal_unfinish_count_),
                slog::F("consecutive_replan_failures", consecutive_replan_failures_),
        });
        publishMissionFailure();
        goal_unfinish_count_ = 0;
        consecutive_replan_failures_ = 0;
        plan_from_rest_failures_ = 0;
        /* Drop any active waypoint batch: the goal it belonged to is dead. */
        if (!gi_.wp_list.empty()) {
            gi_.wp_list.clear();
            gi_.wp_orig_idx.clear();
            planner_ptr_->setWaypointLookahead({});
        }
        gi_.new_goal = false;
        finish_plan = true;
        ChangeState("declareGoalUnreachable", WAIT_TARGET);
    }

    bool Fsm::closeToGoal(const double &thresh_dis) {
        /// The close to goal should consider the the local shift
        /// All goal should be in the known free on inf map.
        /// The intermedia points should be in free space.
        double dis = (robot_state_.p - gi_.goal_p).norm();
        return dis < thresh_dis;
    }

    void Fsm::logNavigationProgress() {
        const double now = ros_ptr_->getSimTime();
        if (last_progress_log_t_ > 0.0 && now - last_progress_log_t_ < 1.0) {
            return;
        }
        last_progress_log_t_ = now;

        const double dist_to_goal = (robot_state_.p - gi_.goal_p).norm();
        double progress = 0.0;
        if (last_progress_dist_ >= 0.0) {
            progress = last_progress_dist_ - dist_to_goal;
        }
        if (last_progress_dist_ < 0.0 || progress > 0.05) {
            last_progress_move_t_ = now;
        }
        last_progress_dist_ = dist_to_goal;

        const double no_progress_duration = last_progress_move_t_ > 0.0 ? now - last_progress_move_t_ : 0.0;
        const bool stuck_suspect = started_ && machine_state_ == FOLLOW_TRAJ &&
                                   dist_to_goal > 0.5 &&
                                   no_progress_duration > 3.0 &&
                                   robot_state_.v.norm() < 0.2;
        SLOG_EVENT(slog::Level::debug, "nav_tick", {
                slog::F("state", MACHINE_STATE_STR[machine_state_]),
                slog::F("dist_to_goal", dist_to_goal),
                slog::F("progress_1s", progress),
                slog::F("no_progress_duration", no_progress_duration),
                slog::F("stuck_suspect", stuck_suspect),
                slog::F("pos", fmt::format("{}", robot_state_.p.transpose())),
                slog::F("goal", fmt::format("{}", gi_.goal_p.transpose())),
                slog::F("vel_norm", robot_state_.v.norm()),
                slog::F("yaw_deg", robot_state_.yaw * 57.2957795),
                slog::F("consecutive_replan_failures", consecutive_replan_failures_),
                slog::F("traj_finish", traj_finish_),
                slog::F("on_backup", planner_ptr_->isOnBackupTraj()),
        });
        if (stuck_suspect) {
            SLOG_EVENT(slog::Level::warn, "stuck_suspect", {
                    slog::F("dist_to_goal", dist_to_goal),
                    slog::F("no_progress_duration", no_progress_duration),
                    slog::F("pos", fmt::format("{}", robot_state_.p.transpose())),
                    slog::F("goal", fmt::format("{}", gi_.goal_p.transpose())),
                    slog::F("vel_norm", robot_state_.v.norm()),
                    slog::F("consecutive_replan_failures", consecutive_replan_failures_),
            });
            if (no_progress_duration > cfg_.goal_unreachable_timeout_s) {
                declareGoalUnreachable("no_progress_timeout");
            }
        }
    }

    void Fsm::setGoalPosiAndYaw(const Vec3f &p, const Quatf &q, int yaw_mode, int yaw_path_mode, bool look_forward) {

        /* Every fresh goal re-syncs the online yaw integrator from the live
         * odometry heading: after a /agent/stack_reset the odom yaw jumps back to the
         * launch heading while the integrator retains the pre-reset value. */
        planner_ptr_->resetOnlineYaw();

        if (planner_ptr_->getMap()->getNearestInfCellNot(GridType::OCCUPIED, p, gi_.goal_p, 3.0)) {
            SLOG_DEBUG(" -- [Fsm] Get goal at {}", fmt::format("{}", gi_.goal_p.transpose()));
            SLOG_EVENT(slog::Level::info, "goal_set", {
                    slog::F("dist_to_goal", (robot_state_.p - gi_.goal_p).norm()),
            });
        } else {
            SLOG_WARN("Goal is deeply occupied, skip this goal.");
            return;
        }

        const bool too_close = (robot_state_.p - gi_.goal_p).norm() < 0.1;
        if (too_close) {
            SLOG_INFO(" -- [SUPER] Goal too close ({:.3f}m), consumed at rest.",
                      (robot_state_.p - gi_.goal_p).norm());
        }

        gi_.yaw_mode = yaw_mode;
        gi_.yaw_path_mode = yaw_path_mode;
        gi_.look_forward = look_forward;

        if (cfg_.yaw_mode == super_planner::fsm::Config::YAW_TO_VEL) {
            gi_.goal_yaw = NAN;
            SLOG_INFO(" -- [SUPER] [Fsm] yaw_mode=YAW_TO_VEL goal yaw free (velocity heading) goal=[{:.3f},{:.3f},{:.3f}]",
                      gi_.goal_p.x(), gi_.goal_p.y(), gi_.goal_p.z());
        } else if (cfg_.yaw_mode == super_planner::fsm::Config::YAW_TO_GOAL) {
            if (look_forward || !cfg_.click_yaw_en) {
                gi_.goal_yaw = NAN;
                SLOG_INFO(" -- [SUPER] [Fsm] yaw_mode=YAW_TO_GOAL look_forward={} goal yaw free goal=[{:.3f},{:.3f},{:.3f}]",
                          static_cast<int>(look_forward),
                          gi_.goal_p.x(), gi_.goal_p.y(), gi_.goal_p.z());
            } else {
                if (isnan(q.w()) || isnan(q.x()) || isnan(q.y()) || isnan(q.z())) {
                    gi_.goal_yaw = NAN;
                    SLOG_INFO(" -- [SUPER] [Fsm] goal yaw disabled (NaN quat) goal=[{:.3f},{:.3f},{:.3f}]",
                              gi_.goal_p.x(), gi_.goal_p.y(), gi_.goal_p.z());
                } else {
                    gi_.goal_yaw = super_planner::geometry_utils::get_yaw_from_quaternion(q);
                    SLOG_INFO(" -- [SUPER] [Fsm] goal yaw={:.2f} deg goal=[{:.3f},{:.3f},{:.3f}]",
                              gi_.goal_yaw * 57.3,
                              gi_.goal_p.x(), gi_.goal_p.y(), gi_.goal_p.z());
                }
            }
        }

        planner_ptr_->getRobotState(robot_state_);
        if (robot_state_.rcv) {
            planner_ptr_->getMap()->clearUnknownAroundOnFirstGoal(robot_state_.p);
        }

        started_ = true;
        gi_.new_goal = true;
        last_progress_dist_ = -1.0;
        last_progress_move_t_ = ros_ptr_->getSimTime();
        consecutive_replan_failures_ = 0;
        goal_unfinish_count_ = 0;
        plan_from_rest_failures_ = 0;
    }

    bool Fsm::setGoalWindow(const uint32_t batch_id, const std::vector<Vec3f> &raw_wps,
                            const Quatf &q, const int yaw_mode, const int yaw_path_mode,
                            const bool look_forward) {
        gi_.wp_list.clear();
        gi_.wp_orig_idx.clear();
        gi_.wp_skipped_mask = 0;
        gi_.wp_window_size = static_cast<int>(raw_wps.size());
        /* Reproject every waypoint onto the nearest non-occupied cell on the inflate map;
         * deeply occupied ones are skipped and reported through skipped_mask. */
        for (size_t i = 0; i < raw_wps.size(); i++) {
            Vec3f reproj;
            if (planner_ptr_->getMap()->getNearestInfCellNot(GridType::OCCUPIED, raw_wps[i], reproj, 3.0)) {
                gi_.wp_list.push_back(reproj);
                gi_.wp_orig_idx.push_back(static_cast<int>(i));
            } else {
                gi_.wp_skipped_mask |= static_cast<uint8_t>(1u << i);
                SLOG_EVENT(slog::Level::warn, "wp_reproject_fail", {
                        slog::F("batch_id", batch_id),
                        slog::F("wp_idx", i),
                        slog::F("wp", fmt::format("{}", raw_wps[i].transpose())),
                });
            }
        }
        if (gi_.wp_list.empty()) {
            SLOG_EVENT(slog::Level::warn, "wp_batch_rejected", {
                    slog::F("batch_id", batch_id),
                    slog::F("reason", "all_reproject_failed"),
            });
            return false;
        }
        gi_.batch_id = batch_id;
        gi_.wp_active_idx = 0;
        SLOG_EVENT(slog::Level::info, "wp_batch_recv", {
                slog::F("batch_id", batch_id),
                slog::F("size", raw_wps.size()),
                slog::F("valid", gi_.wp_list.size()),
                slog::F("skipped_mask", static_cast<unsigned int>(gi_.wp_skipped_mask)),
        });
        /* If the robot is already on top of the first waypoint, consume it immediately. */
        planner_ptr_->getRobotState(robot_state_);
        while (gi_.wp_list.size() > 1 &&
               (robot_state_.p - gi_.wp_list.front()).norm() < cfg_.wp_reach_radius) {
            gi_.wp_list.erase(gi_.wp_list.begin());
            gi_.wp_orig_idx.erase(gi_.wp_orig_idx.begin());
        }
        setGoalPosiAndYaw(gi_.wp_list.front(), q, yaw_mode, yaw_path_mode, look_forward);
        /* Yaw only applies when the batch-final waypoint becomes the active target. */
        gi_.pending_goal_yaw = gi_.goal_yaw;
        if (gi_.wp_list.size() > 1) {
            gi_.goal_yaw = NAN;
        }
        pushWaypointLookaheadToPlanner();
        return true;
    }

    bool Fsm::consumeArrivedWaypoint() {
        if (!gi_.wp_list.empty() && gi_.wp_active_idx < static_cast<int>(gi_.wp_list.size())) {
            gi_.wp_active_idx++;
            if (gi_.wp_active_idx < static_cast<int>(gi_.wp_list.size())) {
                gi_.goal_p = gi_.wp_list[gi_.wp_active_idx];
                if (gi_.wp_active_idx == static_cast<int>(gi_.wp_list.size()) - 1) {
                    gi_.goal_yaw = gi_.pending_goal_yaw;
                }
                gi_.new_goal = true;
                pushWaypointLookaheadToPlanner();
                publishWaypointProgress(false);
                return false;
            }
            /* Window exhausted: report batch completion; the caller reports
             * exec_finished with the final waypoint as the active goal. */
            publishWaypointProgress(true);
            SLOG_EVENT(slog::Level::info, "wp_batch_done", {
                    slog::F("batch_id", gi_.batch_id),
            });
            gi_.wp_list.clear();
            gi_.wp_orig_idx.clear();
            planner_ptr_->setWaypointLookahead({});
        }
        return true;
    }

    void Fsm::pushWaypointLookaheadToPlanner() {
        vec_E<Vec3f> la;
        for (size_t i = gi_.wp_active_idx + 1; i < gi_.wp_list.size(); i++) {
            la.push_back(gi_.wp_list[i]);
        }
        planner_ptr_->setWaypointLookahead(la);
    }

    void Fsm::updateWaypointProgress() {
        if (!started_ || gi_.wp_list.empty() ||
            gi_.wp_active_idx >= static_cast<int>(gi_.wp_list.size())) {
            return;
        }
        const Vec3f tgt = gi_.wp_list[gi_.wp_active_idx];
        const double dist = (robot_state_.p - tgt).norm();
        bool reached = dist < cfg_.wp_reach_radius;
        if (!reached && gi_.wp_active_idx + 1 < static_cast<int>(gi_.wp_list.size())) {
            /* Pass-by: the robot crossed the waypoint's plane along the travel direction
             * with bounded lateral error (the soft pass cost may legitimately deviate). */
            const Vec3f dir = (gi_.wp_list[gi_.wp_active_idx + 1] - tgt).normalized();
            const Vec3f rel = robot_state_.p - tgt;
            const double along = rel.dot(dir);
            const double lateral = (rel - along * dir).norm();
            reached = along > 0.0 && lateral < cfg_.wp_passby_lateral;
        }
        if (!reached) {
            return;
        }
        SLOG_EVENT(slog::Level::info, "wp_consumed", {
                slog::F("batch_id", gi_.batch_id),
                slog::F("wp_idx", gi_.wp_active_idx),
                slog::F("orig_idx", gi_.wp_orig_idx[gi_.wp_active_idx]),
                slog::F("dist", dist),
        });
        gi_.wp_active_idx++;
        if (gi_.wp_active_idx < static_cast<int>(gi_.wp_list.size())) {
            gi_.goal_p = gi_.wp_list[gi_.wp_active_idx];
            if (gi_.wp_active_idx == static_cast<int>(gi_.wp_list.size()) - 1) {
                gi_.goal_yaw = gi_.pending_goal_yaw;
            }
            gi_.new_goal = true;
            pushWaypointLookaheadToPlanner();
        } else {
            /* The batch-final arrival is still reported through the exec_finish path
             * (traj_finish + closeToGoal); only clear the lookahead here. */
            planner_ptr_->setWaypointLookahead({});
        }
        publishWaypointProgress(false);
    }

    void Fsm::ChangeState(const string &call_func, const MACHINE_STATE &new_state) {
        SLOG_EVENT(slog::Level::info, "state_change", {
                slog::F("from", MACHINE_STATE_STR[int(machine_state_)]),
                slog::F("to", MACHINE_STATE_STR[int(new_state)]),
                slog::F("caller", call_func),
        });
        machine_state_ = new_state;
        keyframe_pending_ = true;
    }
}
} // namespace super_planner
