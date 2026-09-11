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

#pragma once

#include <iostream>
#include <fstream>
#include "Eigen/Eigen"


#include <super_core/config.hpp>
#include <ros_interface/ros1/ros1_interface.hpp>
#include <data_structure/base/trajectory.h>

#include <data_structure/base/polytope.h>


#include "traj_opt/exp_traj_optimizer_s4.h"
#include "traj_opt/backup_traj_optimizer_s4.h"
#include "path_search/astar.h"
#include "rog_map/rog_map.h"
#include "super_core/corridor_generator.h"
#include "super_core/fov_checker.h"

#include "traj_opt/yaw_traj_opt.h"
#include "super_core/super_ret_code.hpp"
#include "super_utils/fmt_eigen.hpp"

#include <super_core/log_utils.hpp>
#include <super_core/case_dump.hpp>
#include <data_structure/exp_traj.h>
#include <data_structure/cmd_traj.h>
#include <data_structure/backup_traj.h>


namespace super_planner {
    using namespace super_planner::geometry_utils;

    class SuperPlanner {
        LogOneReplan latest_replan;
        super_planner::Config cfg_;
        std::string cfg_path_;
        /* One-shot reason set by notifyConsecutiveFailures(); consumed (cleared)
         * by the next generateExpTraj case dump. */
        std::string forced_dump_reason_;
        /* Flood-protection state for case dumps. */
        double last_dump_WT_{-1e9};
        int dump_count_{0};
        /* Per-replan wall time of the two SFC constructions [s]; the generic
         * frontend buckets in time_consuming_ include other work. */
        double last_exp_sfc_t_{0.0};
        double last_back_sfc_t_{0.0};
        /* Wall time of the PlanFromRest start-point nearest-free-cell search [s]. */
        double last_goal_shift_t_{0.0};
        /* Pending corner case: queued inside generateExpTraj/generateBackupTrajectory,
         * flushed once at ReplanOnce/PlanFromRest exit so the backup section and
         * the full timing breakdown are included. */
        bool pending_case_{false};
        ExpOptCaseData pending_case_data_;

        friend struct ReplanExitGuard;
        super_planner::rog_map::ROGMap::Ptr map_ptr_;
        CorridorGenerator::Ptr cg_ptr_;
        super_planner::path_search::Astar::Ptr astar_ptr_;
        super_planner::ros_interface::RosInterface::Ptr ros_ptr_;
        Vec3f shifted_sfc_start_pt_;

        super_planner::traj_opt::ExpTrajOpt::Ptr exp_traj_opt_;
        super_planner::traj_opt::BackupTrajOpt::Ptr back_traj_opt_;
        super_planner::traj_opt::YawTrajOpt::Ptr yaw_traj_opt_;

        CIRI::Ptr ciri_;

        super_planner::super_utils::RobotState robot_state_;

        std::mutex drone_state_mutex_;
        std::mutex replan_lock_;

        Vec3f local_start_p_;

        bool robot_on_backup_traj_{false};
        // use negative value to indicate the traj is not available
        double on_backup_start_WT{-1}, on_backup_end_WT{-1};

        double planner_process_start_WT_;

        struct GoalInfo {
            Vec3f goal_p{0, 0, 0};
            double goal_yaw{0};
            bool new_goal{true};
            bool goal_valid{true};
            /* Reprojected waypoints after the current target (travel order), supplied by
             * the FSM waypoint window. Empty => legacy single-goal behavior. */
            vec_E<Vec3f> wp_lookahead;
        } gi_;

        FOVChecker::Ptr fov_checker_;

        CmdTraj cmd_traj_info_;
        ExpTraj last_exp_traj_info_;

        /* Online yaw state: updated per-call in getOneCommandFromTraj */
        double last_yaw_{0.0};
        double last_yawdot_{0.0};
        bool   yaw_time_init_{false};
        double yaw_time_last_{0.0};

        vector<double> time_consuming_;

    public:
        EIGEN_MAKE_ALIGNED_OPERATOR_NEW

        explicit SuperPlanner(const std::string &cfg_path,
                              const super_planner::ros_interface::RosInterface::Ptr &ros_ptr,
                              const super_planner::rog_map::ROGMap::Ptr &map_ptr);

        ~SuperPlanner() = default;

        void lockCommittedTraj() {
            cmd_traj_info_.lock();
        }

        void unlockCommittedTraj() {
            cmd_traj_info_.unlock();
        }

        bool goalValid() const {
            return gi_.goal_valid;
        }

        /**
         * Current committed-trajectory provenance: true while the sampled command
         * lies on the fallback (backup) segment.
         *
         * @return True if on the backup trajectory
         */
        bool isOnBackupTraj() const {
            return robot_on_backup_traj_;
        }

        /**
         * Update the lookahead waypoints planned through beyond the current target.
         *
         * @param[in] wps  Reprojected waypoints in travel order [m], empty to clear
         */
        void setWaypointLookahead(const vec_E<Vec3f> &wps) {
            gi_.wp_lookahead = wps;
        }

        typedef std::shared_ptr<SuperPlanner> Ptr;

        void getOneHeartbeatTime(double &start_WT_pos, bool &traj_finish);

        Trajectory getCommittedPositionTrajectory();

        Trajectory getCommittedYawTrajectory();

        void getOneCommandFromTraj(StatePVAJ &pvaj,
                                   double &yaw,
                                   double &yaw_dot,
                                   bool &on_backup_traj,
                                   bool &traj_finish);

        void getModuleTimeConsuming(vector<double> &time);

        /* Tow type of replan strategy */
        RET_CODE PlanFromRest(const Vec3f &goal_p,
                              const double &goal_yaw,
                              const bool &new_goal);

        RET_CODE
        ReplanOnce(const Vec3f &goal_p,
                   const double &goal_yaw,
                   const bool &new_goal);

        /**
         * Target yaw for the YAWING phase: the look-ahead chord heading at the
         * committed trajectory's start, using the same definition as the online
         * yaw tracker and the mid-flight mismatch trigger (shared
         * getLookaheadChordYaw). Converging here means FOLLOW_TRAJ resumes with
         * zero yaw step and the mismatch trigger cannot re-fire right after
         * pre-yaw. No time_forward parameter: the tracker's own look-ahead is
         * used, keeping all three heading definitions identical.
         *
         * @return Target yaw [rad], or NAN if near-vertical
         */
        double getPreYawTarget();

        /**
         * Generate an in-place yaw trajectory from the live odometry heading
         * to the goal yaw for YAWING yaw-only turns.
         *
         * The target yaw is FIRST allocated as the shortest circle path from
         * the current odometry heading (normalizeNextYaw), yielding a
         * continuous euler value; only then is YawTrajOpt run, so the minAcc
         * interpolation never winds around the +/-pi boundary. A
         * zero-displacement standstill position trajectory (duration from the
         * trapezoidal yaw limit) feeds the optimizer's time allocation.
         *
         * @param[in]  target_yaw   Goal yaw [rad]
         * @param[out] yaw_goal_out Allocated shortest-path yaw goal (continuous) [rad]
         * @param[out] out_traj     Optimized yaw trajectory [rad]
         * @return True on success
         */
        bool generateYawOnlyTraj(const double target_yaw, double &yaw_goal_out,
                                 Trajectory &out_traj);

        /**
         * Heading the online yaw tracker commands at eval_t: the chord from the
         * trajectory position to the look-ahead point (same retry semantics as
         * getOneCommandFromTraj). Caller must hold the committed-traj lock.
         *
         * @param[in] eval_t  Trajectory time to evaluate [s]
         * @return Look-ahead chord yaw [rad], or NAN if unavailable
         */
        double getLookaheadChordYaw(const double eval_t);

        /**
         * Yaw of the committed trajectory at the current evaluation time, using
         * the same look-ahead chord definition as the online yaw tracker (the
         * mid-flight mismatch trigger must compare against what the drone is
         * actually commanded to do, not the instantaneous tangent).
         *
         * @return Look-ahead chord yaw [rad], or NAN if unavailable / too slow
         */
        double getTrajTangentYawNow();

        /**
         * Reset the committed trajectory's start wall time after pre-yaw completes.
         *
         * @param[in] new_start_WT  New world start time [s]
         */
        void resetTrajStartWallTime(double new_start_WT);

        /**
         * Drop the committed trajectory so no further PositionCommand is
         * sampled from it (Planner Reset Contract).
         */
        void clearCommittedTraj();

        /**
         * Step the online yaw state toward target_yaw with trapezoidal velocity
         * and acceleration limits.
         *
         * @param[in]  cur_time   Current wall time [s]
         * @param[in]  target_yaw Desired yaw [rad]
         * @param[out] yaw        Resulting yaw [rad]
         * @param[out] yaw_dot    Resulting yaw rate [rad/s]
         */
        void stepOnlineYaw(double cur_time, double target_yaw,
                           double &yaw, double &yaw_dot);

        /**
         * Reset the online yaw integrator so the next stepOnlineYaw call
         * re-synchronizes from the current odometry heading.
         *
         * Called on trajectory-start (re)triggers and on every new goal: after
         * an in-place /agent/stack_reset the odometry yaw jumps back to the launch
         * heading while the integrator keeps the pre-reset value, which made
         * the yaw-only turn command diverge ~180 deg from the true heading and
         * dragged the quadrotor down (thrust lost to roll). Re-syncing from
         * odometry restores smooth in-place turns.
         */
        void resetOnlineYaw() {
            yaw_time_init_ = false;
            last_yaw_ = 0.0;
            last_yawdot_ = 0.0;
            yaw_time_last_ = 0.0;
        }

        bool cfgOnlineYawEnabled() const { return cfg_.online_yaw_en; }

    private:
        RET_CODE generateExpTraj(ExpTraj &last_exp_traj_info,
                                 ExpTraj &out_exp_traj_info);

        /* Fill common context fields and queue a case for dumping at replan exit. */
        void queueCaseDump(ExpOptCaseData &data);

        /* Write the queued case (with flood protection) and emit case_dumped. */
        void flushPendingCase();

        /* Emit the per-replan timing breakdown as a structured ROS log event. */
        void emitReplanTiming(const char *stage, int ret, double total_s);

        /* Replan-exit hook used by ReplanExitGuard (timing event + case flush). */
        void onReplanExit(const char *stage, int ret, double total_s);

        /* For Backup traj generation */
        RET_CODE generateBackupTrajectory(ExpTraj &ref_exp_traj, BackupTraj &back_traj_info);

        int getNearestFurtherGoalPoint(const vec_E<Vec3f> &goals, const Vec3f &start_pt);

        bool PathSearch(const Vec3f &start_pt, const Vec3f &goal,
                        const double &searching_horizon,
                        vec_Vec3f &path);

        /* Low-pass filtered adaptive planning horizon [m]; <=0 uninitialized. */
        double adaptive_horizon_{-1.0};

        /* Low-pass filtered risk-based velocity bound [m/s]; <=0 uninitialized. */
        double risk_vel_{-1.0};

        /* Previous replan's risk velocity bound [m/s]; slew-limit reference. */
        double risk_vel_prev_{-1.0};

        /**
         * Geometric length of the currently committed position trajectory,
         * chord-summed at sample_traj_dt under the commit lock.
         *
         * @return Trajectory length [m]; -1 when nothing committed (first goal)
         */
        double committedTrajLength();

    public:
        void getRobotState(super_planner::rog_map::RobotState &out);

        bool isEasyGoal(const Vec3f &goal_position);

        super_planner::rog_map::ROGMap::Ptr &getMap() {
            return map_ptr_;
        }

        double ft{0}, bt{0};
        int ft_cnt{0}, bt_cnt{0};

        double getFrontendTime() {
            if (ft_cnt == 0) return -1;
            double ave_t = ft / ft_cnt;
            ft = 0;
            ft_cnt = 0;
            return ave_t;
        }

        double getBackendTime() {
            if (bt_cnt == 0) return -1;
            double ave_t = bt / bt_cnt;
            bt = 0;
            bt_cnt = 0;
            return ave_t;
        }

        void updateROGMap(const super_planner::rog_map::PointCloud &cloud, const super_planner::super_utils::Pose &pose) const {
            map_ptr_->updateMap(cloud, pose);
        }

        /**
         * Feed the consecutive replan failure count; arms a one-shot corner-case
         * dump on the next generateExpTraj when the configured threshold is hit.
         *
         * @param[in] consecutive_failures  consecutive failed replans so far [-]
         */
        void notifyConsecutiveFailures(const int consecutive_failures) {
            if (cfg_.case_dump.enable && consecutive_failures >= cfg_.case_dump.consec_failures) {
                forced_dump_reason_ = "repeated_failure";
            }
        }

        LogOneReplan getLatestReplanLog() {
            latest_replan.setSfcPc(cg_ptr_->getLatestCloud());
            latest_replan.setComptT(time_consuming_);
            return latest_replan;
        }
    };
}
