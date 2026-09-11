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

#include <queue>
#include <memory>
#include <fstream>
#include <fmt/color.h>
#include <fsm/config.hpp>
#include <super_core/super_planner.h>
namespace super_planner {
namespace fsm {
    class Fsm {
    protected:
        bool stop{false};

        Config cfg_;
        // map, checker, planner
        super_planner::SuperPlanner::Ptr planner_ptr_;
        super_planner::ros_interface::RosInterface::Ptr ros_ptr_;

        double yaw_{0}, yaw_dot_{0};

        super_planner::rog_map::RobotState robot_state_;

        // params
        bool started_{false}, plan_from_rest_{false};
        bool waiting_traj_start_trigger_{true};

        struct GoalInfo {
            bool new_goal;
            Vec3f goal_p;
            double goal_yaw;
            int yaw_mode{0};
            int yaw_path_mode{0};
            bool look_forward{false};
            /* Waypoint window state (multi-goal batch from the upper layer).
             * wp_list holds the valid reprojected waypoints in travel order;
             * wp_list[wp_active_idx] == goal_p while the batch is active. */
            uint32_t batch_id{0};
            vec_E<Vec3f> wp_list;
            std::vector<int> wp_orig_idx;
            int wp_window_size{0};
            int wp_active_idx{0};
            uint8_t wp_skipped_mask{0};
            double pending_goal_yaw{NAN};
        } gi_;

        Eigen::Vector3d auto_pilot_vel_w_;

        // execution states
        enum MACHINE_STATE {
            INIT = 0,
            WAIT_TARGET,
            YAWING,
            GENERATE_TRAJ,
            FOLLOW_TRAJ
        };

        vector<string> MACHINE_STATE_STR{
                "INIT",
                "WAIT_TARGET",
                "YAWING",
                "GENERATE_TRAJ",
                "FOLLOW_TRAJ"
        };


        MACHINE_STATE machine_state_{INIT};

        /* Reset request (Planner Reset Contract): set by the /planner/reset
         * service callback (service thread), consumed by callMainFsmOnce on
         * the FSM thread — no state is mutated from the service thread. */
        bool reset_requested_{false};
        void requestReset() { reset_requested_ = true; }
        /**
         * Execute the reset on the FSM thread: clear the active goal / window,
         * drop the committed trajectory, re-sync yaw, return to WAIT_TARGET.
         */
        void handleReset();


    public:
        Fsm() = default;
        ~Fsm();

        void updateROGMap(const super_planner::rog_map::PointCloud &cloud, const super_planner::super_utils::Pose &pose) {
            planner_ptr_->updateROGMap(cloud, pose);
        }

        void callPlanOnce(const Vec3f &goal) {
            TimeConsuming tc("Call replan once time", true);
            SLOG_INFO(" -- [Fsm] Call plan once, cur state {}.", MACHINE_STATE_STR[machine_state_]);
            // check current state;
            Quatf q(NAN, NAN, NAN, NAN);
            setGoalPosiAndYaw(goal, q);

            callMainFsmOnce();

            if (machine_state_ == FOLLOW_TRAJ) {
                callReplanOnce();
            }

            SLOG_INFO(" -- Replan ret code: {}", planner_ptr_->getLatestReplanLog().getRetCode());
        }

        Eigen::Quaterniond eulerToQuaternion(double roll, double pitch, double yaw) {
            double half_roll = roll * 0.5;
            double half_pitch = pitch * 0.5;
            double half_yaw = yaw * 0.5;

            double sin_r = std::sin(half_roll);
            double cos_r = std::cos(half_roll);
            double sin_p = std::sin(half_pitch);
            double cos_p = std::cos(half_pitch);
            double sin_y = std::sin(half_yaw);
            double cos_y = std::cos(half_yaw);

            // 计算四元数分量
            Eigen::Quaterniond q;
            q.w() = cos_r * cos_p * cos_y + sin_r * sin_p * sin_y;
            q.x() = sin_r * cos_p * cos_y - cos_r * sin_p * sin_y;
            q.y() = cos_r * sin_p * cos_y + sin_r * cos_p * sin_y;
            q.z() = cos_r * cos_p * sin_y - sin_r * sin_p * cos_y;

            return q;
        }

    protected:
        /* Key-frame bookkeeping for mcap scene snapshots: state transitions and
         * async triggers (backup-traj consumption) mark keyframe_pending_, which
         * the next recordReplan consumes. */
        bool keyframe_pending_{false};
        int ambient_cnt_{0};

        /* Callback functions */
        bool finish_plan = false;
        double system_start_time_;
        /* Pre-yaw state */
        double pre_yaw_target_{NAN};
        double pre_yaw_start_time_{0.0};
        /* YAWING entry provenance: true when entered from GENERATE_TRAJ (the
         * trajectory was generated from rest, so the frozen-clock resume is
         * consistent); false when entered mid-flight (tangent-yaw mismatch) —
         * then the executed trajectory must be re-generated from the actual
         * hover state after yaw convergence (YAWING -> GENERATE_TRAJ). */
        bool yaw_from_rest_{false};

        /* Yaw-only task: goal position already reached but goal_yaw differs
         * (in-place turn). Entered from GENERATE_TRAJ's already-arrived branch;
         * YAWING turns in place via pre_yaw_target_, then consumes the goal at
         * rest instead of resuming a trajectory. */
        bool yaw_only_task_{false};

        bool traj_finish_{false};
        double last_progress_log_t_{-1.0};
        double last_progress_dist_{-1.0};
        double last_progress_move_t_{-1.0};
        int consecutive_replan_failures_{0};

        /* Consecutive PlanFromRest failures in GENERATE_TRAJ: without escalation
         * the FSM retries at 100 Hz forever on a deterministic frontend failure. */
        int plan_from_rest_failures_{0};
        static constexpr int kPlanFromRestMaxFailures{100};

        void callReplanOnce();

        void callMainFsmOnce();

        bool closeToGoal(const double &thresh_dis);

        void logNavigationProgress();

        void setGoalPosiAndYaw(const Vec3f &p, const Quatf &q, int yaw_mode = 0, int yaw_path_mode = 0, bool look_forward = false);

        /**
         * Accept a waypoint window: reproject each waypoint onto the nearest free cell,
         * drop deeply occupied ones (reported via skipped_mask), and track wp_list[0].
         *
         * @param[in] batch_id  Monotonic batch identifier from the upper layer
         * @param[in] raw_wps   Raw waypoints in travel order (at most 3) [m]
         * @return True if at least one waypoint survived reprojection
         */
        bool setGoalWindow(uint32_t batch_id, const std::vector<Vec3f> &raw_wps,
                           const Quatf &q, int yaw_mode, int yaw_path_mode, bool look_forward);

        /**
         * Advance the active waypoint when the robot reaches (or passes by) the current
         * target; publishes WaypointProgress on every consumption.
         */
        void updateWaypointProgress();

        /**
         * Consume the active waypoint on arrival: advances the window and publishes
         * per-waypoint progress, or closes the batch when exhausted.
         *
         * @return True if the goal/window is fully completed (caller reports
         *         exec_finished and goes WAIT_TARGET); false if the window advanced
         *         to the next waypoint (caller should replan).
         */
        bool consumeArrivedWaypoint();

        void pushWaypointLookaheadToPlanner();

        virtual void publishWaypointProgress(bool all_consumed) = 0;

        /* Goal-unreachable escalation state: counts trajectory executions that
         * finish away from the goal; reset on new goal or successful finish. */
        int goal_unfinish_count_{0};

        /* Report the unreachable goal upstream (plan_status=false); subclass hook. */
        virtual void publishMissionFailure() {}

        /**
         * Called when the drone is already at the goal position (< 0.3 m) during
         * GENERATE_TRAJ, before silently transitioning back to WAIT_TARGET. Subclass
         * should publish feedback (e.g. exec_finished=true) so the mission layer
         * knows this goal was consumed without trajectory generation.
         */
        virtual void onGoalConsumedAtRest() {}

        /* Stop the replan loop for a goal that cannot be reached: report failure
         * and wait for a new goal instead of replanning forever. */
        void declareGoalUnreachable(const std::string &reason);

        void ChangeState(const string &call_func, const MACHINE_STATE &new_state);

        virtual void publishCurPoseToPath() = 0;

        virtual void resetVisualizedPath() = 0;
    };
}
} // namespace super_planner
