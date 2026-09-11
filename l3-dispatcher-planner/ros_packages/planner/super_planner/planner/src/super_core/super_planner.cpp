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

#include <super_core/super_planner.h>
#include <memory>
#include <chrono>
#include <cmath>
#include <super_utils/scope_timer.hpp>
#include <utils/optimization/polynomial_interpolation.h>
#include <fmt/color.h>

using namespace super_planner::super_utils;

namespace super_planner {
    namespace {
        /**
         * Build a simple multi-segment yaw trajectory following the position
         * trajectory's heading: each interior junction takes the local motion
         * direction as its yaw waypoint, times reuse the position segment
         * durations, and the whole curve is interpolated by minAcc.
         *
         * @param[in] pos_traj   Position trajectory to align with [m]
         * @param[in] init_yaw   Yaw at trajectory start [rad]
         * @param[in] goal_yaw   Yaw at trajectory end [rad]; NaN = last-segment heading
         * @return Segment-aligned yaw trajectory [rad]
         */
        Trajectory buildDirectionalYawTraj(const Trajectory &pos_traj,
                                           const double init_yaw,
                                           const double goal_yaw) {
            const int n = pos_traj.getPieceNum();
            const double total_dur = pos_traj.getTotalDuration();
            const VecDf seg_ts = pos_traj.getDurations();

            /* Local heading at time t from a centered position difference; NaN
             * when horizontal motion is degenerate (near-vertical/stationary). */
            auto headingAt = [&](const double t) -> double {
                const double t0 = std::max(t - 0.1, 0.0);
                const double t1 = std::min(t + 0.1, total_dur);
                const Eigen::Vector3d dir = pos_traj.getPos(t1) - pos_traj.getPos(t0);
                if (dir.head(2).norm() < 0.05) return NAN;
                return atan2(dir.y(), dir.x());
            };

            auto unwrap = [](const double ref, const double y) {
                double d = y - ref;
                while (d > M_PI) d -= 2 * M_PI;
                while (d < -M_PI) d += 2 * M_PI;
                return ref + d;
            };

            double prev = init_yaw;
            Eigen::Matrix<double, 1, -1> y_wps(1, n - 1);
            double t_acc = 0.0;
            for (int i = 0; i < n - 1; i++) {
                t_acc += seg_ts(i);
                double h = headingAt(t_acc);
                if (isnan(h)) h = prev;
                else h = unwrap(prev, h);
                y_wps(0, i) = h;
                prev = h;
            }

            double y_end = goal_yaw;
            if (isnan(y_end)) {
                y_end = headingAt(total_dur);
                if (isnan(y_end)) y_end = prev;
            }
            y_end = unwrap(prev, y_end);

            Eigen::Matrix<double, 1, 2> y_init, y_goal;
            y_init << init_yaw, 0.0;
            y_goal << y_end, 0.0;
            return super_planner::geometry_utils::poly_interpo::minimumAccInterpolation<1>(y_init, y_goal, y_wps, seg_ts);
        }
    }

    /* RAII replan-exit hook: emits replan_timing and flushes any queued case
     * dump on every return path. ret should be overwritten with the outcome
     * RET_CODE once known. */
    struct ReplanExitGuard {
        SuperPlanner *self;
        const char *stage;
        int ret{-999};
        std::chrono::steady_clock::time_point t0 = std::chrono::steady_clock::now();

        ~ReplanExitGuard() {
            const double total_s =
                    std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
            self->onReplanExit(stage, ret, total_s);
        }
    };

    SuperPlanner::SuperPlanner
            (const std::string &cfg_path,
             const super_planner::ros_interface::RosInterface::Ptr &ros_ptr,
             const super_planner::rog_map::ROGMap::Ptr &map_ptr
            ) : cfg_(super_planner::Config(cfg_path)), cfg_path_(cfg_path), ros_ptr_(ros_ptr), map_ptr_(map_ptr) {

        ros_ptr_->setResolution(cfg_.resolution);
        ros_ptr_->setVisualizationEn(cfg_.visualization_en);
        exp_traj_opt_ = std::make_shared<super_planner::traj_opt::ExpTrajOpt>(cfg_.exp_traj_cfg, ros_ptr_);
        back_traj_opt_ = std::make_shared<super_planner::traj_opt::BackupTrajOpt>(cfg_.back_traj_cfg, ros_ptr_);
        yaw_traj_opt_ = std::make_shared<super_planner::traj_opt::YawTrajOpt>(cfg_.yaw_dot_max);
        const auto &rog_map_cfg = map_ptr_->getMapConfig();
        astar_ptr_ = std::make_shared<super_planner::path_search::Astar>(cfg_path, ros_ptr_, map_ptr_);
        cg_ptr_ = std::make_shared<CorridorGenerator>(ros_ptr_, map_ptr_, cfg_.corridor_bound_dis,
                                                      cfg_.corridor_line_max_length,
                                                      cfg_.resolution, rog_map_cfg.virtual_ground_height,
                                                      rog_map_cfg.virtual_ceil_height,
                                                      cfg_.robot_r,
                                                      cfg_.obs_skip_num,
                                                      cfg_.iris_iter_num);
        cg_ptr_->SetLineNeighborList(cfg_.seed_line_neighbour);


        time_consuming_.resize(8);

        robot_state_.rcv = false;
        planner_process_start_WT_ = ros_ptr_->getSimTime();
        fov_checker_ = std::make_shared<FOVChecker>(FOVType::OMNI,
                                                    -1.0,
                                                    -22.0,
                                                    37.0);
    }

    void SuperPlanner::queueCaseDump(ExpOptCaseData &data) {
        if (!cfg_.case_dump.enable || pending_case_) {
            return;
        }
        data.sim_time = ros_ptr_->getSimTime();
        data.robot_p = robot_state_.p;
        data.goal_p = gi_.goal_p;
        data.goal_yaw = gi_.goal_yaw;
        if (data.cloud.empty()) {
            data.cloud = cg_ptr_->peekLatestCloud();
        }
        pending_case_data_ = data;
        pending_case_ = true;
    }

    void SuperPlanner::flushPendingCase() {
        if (!pending_case_) {
            return;
        }
        pending_case_ = false;
        /* Flood protection: a continuously failing planner would otherwise dump
         * one case per replan cycle. */
        const double now_WT = ros_ptr_->getSimTime();
        if (cfg_.case_dump.max_cases > 0 && dump_count_ >= cfg_.case_dump.max_cases) {
            return;
        }
        if (now_WT - last_dump_WT_ < cfg_.case_dump.min_interval_s) {
            return;
        }
        last_dump_WT_ = now_WT;
        dump_count_++;
        const std::string case_id = CaseDumper::dump(cfg_.case_dump, cfg_path_, pending_case_data_);
        if (case_id.empty()) {
            SLOG_EVENT(slog::Level::warn, "case_dump_failed", {
                    slog::F("reason", pending_case_data_.reason),
                    slog::F("output_dir", cfg_.case_dump.output_dir),
            });
            return;
        }
        SLOG_EVENT(slog::Level::warn, "case_dumped", {
                slog::F("case_id", case_id),
                slog::F("reason", pending_case_data_.reason),
                slog::F("stage", pending_case_data_.stage),
                slog::F("dir", cfg_.case_dump.output_dir + "/" + case_id),
        });
    }

    void SuperPlanner::emitReplanTiming(const char *stage, int ret, double total_s) {
        const auto &stats = exp_traj_opt_->getLastOptStats();
        SLOG_EVENT(slog::Level::info, "replan_timing", {
                slog::F("stage", stage),
                slog::F("ret", ret),
                slog::F("total_t", total_s),
                slog::F("frontend_t", time_consuming_[EPX_TRAJ_FRONTEND]),
                slog::F("exp_sfc_t", last_exp_sfc_t_),
                slog::F("exp_opt_t", time_consuming_[EXP_TRAJ_OPT]),
                slog::F("back_frontend_t", time_consuming_[BACK_TRAJ_FRONTEND]),
                slog::F("back_sfc_t", last_back_sfc_t_),
                slog::F("back_opt_t", time_consuming_[BACK_TRAJ_OPT]),
                slog::F("viz_t", time_consuming_[VISUALIZATION]),
                slog::F("goal_shift_t", last_goal_shift_t_),
                slog::F("iter_num", stats.iter_num),
                slog::F("final_cost", stats.final_cost),
        });
    }

    void SuperPlanner::onReplanExit(const char *stage, int ret, double total_s) {
        emitReplanTiming(stage, ret, total_s);
        flushPendingCase();
    }

    RET_CODE
    SuperPlanner::PlanFromRest(const Vec3f &goal_p,
                               const double &goal_yaw,
                               const bool &new_goal) {
        std::lock_guard<std::mutex> guard(replan_lock_);
        ReplanExitGuard exit_guard{this, "PlanFromRest"};
        std::fill(time_consuming_.begin(), time_consuming_.end(), 0.0);
        last_exp_sfc_t_ = 0.0;
        last_back_sfc_t_ = 0.0;
        last_goal_shift_t_ = 0.0;
        latest_replan.reset();
        latest_replan.setGoal(goal_p, goal_yaw, robot_state_);
        if (robot_state_.rcv == false) {
            ros_ptr_->warn(" -- [SUPER] in [PlanFromRest]: No odom, force return.");
            latest_replan.setRetCode(SUPER_RET_CODE::SUPER_NO_ODOM);
            return FAILED;
        }
        gi_.goal_p = goal_p;
        gi_.goal_yaw = goal_yaw;
        gi_.new_goal = new_goal;
        gi_.goal_valid = true;
        vec_Vec3f viz_pts{goal_p, robot_state_.p};

        {
            TimeConsuming t_viz("viz goal path", false);
            ros_ptr_->vizGoalPath(viz_pts);
            time_consuming_[VISUALIZATION] += t_viz.stop();
        }


        /// 1) First, shift the start_point to free space.
        Vec3f local_star_pt;
        TimeConsuming t_goal_shift("t_goal_shift", false);
        const bool start_free = map_ptr_->getNearestCellNot(GridType::OCCUPIED, robot_state_.p, local_star_pt, 3.0);
        last_goal_shift_t_ = t_goal_shift.stop();
        if (!start_free) {
            ros_ptr_->error(
                    " -- [SUPER] in [PlanFromRest] Local start point is deeply occupied, which should not happened.");
            latest_replan.setRetCode(SUPER_RET_CODE::SUPER_NO_START_POINT);
            return FAILED;
        }
        latest_replan.setLocalStartP(local_star_pt);

        /// 2) Generate Exp traj
        ExpTraj exp_traj_info;
        BackupTraj back_traj_info;
        last_exp_traj_info_.setEmpty();
        local_start_p_ = local_star_pt;
        RET_CODE exp_ret_code = generateExpTraj(last_exp_traj_info_, exp_traj_info);
        exit_guard.ret = exp_ret_code;
        //GenerateRestToRestExpTraj(local_star_pt, exp_traj_info);
        if (exp_ret_code == FAILED) {
            ros_ptr_->warn(" -- [SUPER] in [PlanFromRest] GenerateExpTrajectory failed with {}.",
                           RET_CODE_STR[exp_ret_code].c_str());
            return FAILED;
        } else {
            ros_ptr_->info(" -- [SUPER] in [PlanFromRest] GenerateExpTrajectory SUCCESS.");
        }

        back_traj_info.setEmpty();
        RET_CODE back_ret_code = generateBackupTrajectory(exp_traj_info, back_traj_info);;
        exit_guard.ret = back_ret_code;

        if (back_ret_code == SUCCESS) {
            if (cfg_.print_log) {
                ros_ptr_->info(" -- [SUPER] in [PlanFromRest] generateBackupTrajectory SUCCESS.");
            }

            cmd_traj_info_.setTrajectory(exp_traj_info, back_traj_info);
            ros_ptr_->publishOptimizedTraj(cmd_traj_info_.posTraj());
            last_exp_traj_info_ = exp_traj_info;
            robot_on_backup_traj_ = false;
            gi_.new_goal = false;

            // For visualization
            {
                TimeConsuming t_viz("viz goal VisualizeCommitTrajectory", false);
                ros_ptr_->vizCommittedTraj(cmd_traj_info_.posTraj(), cmd_traj_info_.getBackupTrajStartTT());
                time_consuming_[VISUALIZATION] += t_viz.stop();
                latest_replan.setRetCode(SUPER_RET_CODE::SUPER_SUCCESS_WITH_BACKUP);
            }

            return SUCCESS;
        } else if (back_ret_code == FINISH || back_ret_code == NO_NEED) {
            if (cfg_.print_log) {
                ros_ptr_->info(" -- [SUPER] in [PlanFromRest] generateBackupTrajectory Finish or NO_NEED.");
            }
            robot_on_backup_traj_ = false;
            cmd_traj_info_.setTrajectory(exp_traj_info);
            ros_ptr_->publishOptimizedTraj(cmd_traj_info_.posTraj());
            last_exp_traj_info_ = exp_traj_info;
            gi_.new_goal = false;

            // For visualization
            TimeConsuming t_viz("viz goal VisualizeCommitTrajectory", false);
            {
                ros_ptr_->vizCommittedTraj(cmd_traj_info_.posTraj(), -1);
                time_consuming_[VISUALIZATION] += t_viz.stop();
            }
            latest_replan.setRetCode(SUPER_RET_CODE::SUPER_SUCCESS_NO_BACKUP);
            return SUCCESS;
        }
        ros_ptr_->warn(" -- [SUPER] in [PlanFromRest] generateBackupTrajectory return [{}], force return",
                       RET_CODE_STR[back_ret_code].c_str());
        return FAILED;
    }


    RET_CODE
    SuperPlanner::ReplanOnce(const Vec3f &goal_p,
                             const double &goal_yaw,
                             const bool &new_goal) {
        TimeConsuming replan_total_t("ReplanOnce", false);
        std::lock_guard<std::mutex> guard(replan_lock_);
        ReplanExitGuard exit_guard{this, "ReplanOnce"};
        std::fill(time_consuming_.begin(), time_consuming_.end(), 0.0);
        last_exp_sfc_t_ = 0.0;
        last_back_sfc_t_ = 0.0;
        last_goal_shift_t_ = 0.0;

        gi_.goal_p = goal_p;
        gi_.goal_yaw = goal_yaw;
        gi_.new_goal = new_goal;
        gi_.goal_valid = true;
        latest_replan.reset();
        latest_replan.setGoal(goal_p, goal_yaw, robot_state_);

        vec_Vec3f viz_pts{goal_p, robot_state_.p};

        {
            TimeConsuming t_viz("tviz", false);
            ros_ptr_->vizGoalPath(viz_pts);
            time_consuming_[VISUALIZATION] += t_viz.stop();
        }


        /// 1) Replan EXP traj
        ExpTraj exp_traj_info;
        TimeConsuming t_exp("t_exp", false);
        RET_CODE exp_ret_code = generateExpTraj(last_exp_traj_info_, exp_traj_info);
        time_consuming_[GENERATE_EXP_TRAJ] = t_exp.stop();
        exit_guard.ret = exp_ret_code;

        if (exp_ret_code == FAILED) {
            SLOG_EVENT(slog::Level::warn, "generate_exp_failed", {
                    slog::F("stage", "ReplanOnce"),
                    slog::F("dist_to_goal", (robot_state_.p - gi_.goal_p).norm()),
                    slog::F("pos", fmt::format("{}", robot_state_.p.transpose())),
                    slog::F("goal", fmt::format("{}", gi_.goal_p.transpose())),
                    slog::F("vel_norm", robot_state_.v.norm()),
                    slog::F("on_backup", robot_on_backup_traj_),
            });
            ros_ptr_->warn(" -- [SUPER] in [ReplanOnce]: GenerateExpTrajectory failed, force return");
            return FAILED;
        } else if (exp_ret_code == SUCCESS) {
            if (cfg_.print_log) {
                ros_ptr_->info(" -- [SUPER] in [ReplanOnce]: Replan a new exp traj success.");
            }
        } else if (exp_ret_code == NO_NEED) {
            if (cfg_.print_log)
                ros_ptr_->info(" -- [SUPER] in [ReplanOnce]: No need to replan a new exp traj, use last one.");
        }

        {
            TimeConsuming t_viz("tviz", false);
            ros_ptr_->vizYawTraj(exp_traj_info.posTraj(), exp_traj_info.yawTraj());
            time_consuming_[VISUALIZATION] += t_viz.stop();
        }


        BackupTraj back_traj_info;
        // 2）生成back轨迹
        TimeConsuming t_back("t_back", false);
        RET_CODE back_ret_code = generateBackupTrajectory(exp_traj_info, back_traj_info);
        time_consuming_[GENERATE_BACK_TRAJ] = t_back.stop();
        exit_guard.ret = back_ret_code;

        {
            ft += time_consuming_[EPX_TRAJ_FRONTEND] + time_consuming_[BACK_TRAJ_FRONTEND];
            ft_cnt++;
            bt += time_consuming_[BACK_TRAJ_OPT] + time_consuming_[EXP_TRAJ_OPT];
            bt_cnt++;
        }

        double replan_dt = replan_total_t.stop();
        if (replan_dt > cfg_.replan_forward_dt * 0.9) {
            ros_ptr_->warn(" -- [SUPER] in [ReplanOnce]: Replan overtime, check parameters, replan dt = {}.", replan_dt);
            return FAILED;
        }

        if (back_ret_code == SUCCESS) {
            cmd_traj_info_.setTrajectory(exp_traj_info, back_traj_info);
            ros_ptr_->publishOptimizedTraj(cmd_traj_info_.posTraj());
            last_exp_traj_info_ = exp_traj_info;
            robot_on_backup_traj_ = false;
            gi_.new_goal = false;

            {
                // For visualization
                TimeConsuming t_viz("tviz", false);
                ros_ptr_->vizCommittedTraj(cmd_traj_info_.posTraj(), cmd_traj_info_.getBackupTrajStartTT());
                time_consuming_[VISUALIZATION] += t_viz.stop();
            }

            latest_replan.setRetCode(SUPER_SUCCESS_WITH_BACKUP);
            if (cfg_.print_log)
                ros_ptr_->info(" -- [SUPER] in [ReplanOnce]: Replan a new back traj success, all replan success.");
            return SUCCESS;
        } else if (back_ret_code == NO_NEED) {
            // 这次生成backup轨迹的点没有意义,
            robot_on_backup_traj_ = false;
            last_exp_traj_info_ = exp_traj_info;
            gi_.new_goal = false;


            {
                TimeConsuming t_viz("tviz", false);
                ros_ptr_->vizCommittedTraj(cmd_traj_info_.posTraj(), -1);
                time_consuming_[VISUALIZATION] += t_viz.stop();

            }

            if (cfg_.print_log)
                ros_ptr_->info(" -- [SUPER] in [ReplanOnce]: No need back traj success, all replan success.");
            latest_replan.setRetCode(SUPER_SUCCESS_NO_BACKUP);
            return SUCCESS;
        } else if (back_ret_code == FINISH) {
            // Which means the exp traj is all in known free, no need for backup traj
            cmd_traj_info_.setTrajectory(exp_traj_info);
            ros_ptr_->publishOptimizedTraj(cmd_traj_info_.posTraj());
            last_exp_traj_info_ = exp_traj_info;
            robot_on_backup_traj_ = false;
            gi_.new_goal = false;

            {
                TimeConsuming t_viz("tviz", false);
                ros_ptr_->vizCommittedTraj(cmd_traj_info_.posTraj(), -1);
                time_consuming_[VISUALIZATION] += t_viz.stop();
            }

            if (cfg_.print_log)
                ros_ptr_->info(" -- [SUPER] in [ReplanOnce]: No need back traj success, all replan success.");
            latest_replan.setRetCode(SUPER_SUCCESS_NO_BACKUP);
            return SUCCESS;
        }
        ros_ptr_->warn(" -- [SUPER] in [ReplanOnce]: generateBackupTrajectory return {}, replan Failed return",
                       RET_CODE_STR[back_ret_code].c_str());
        return FAILED;
    }

    void SuperPlanner::getOneHeartbeatTime(double &start_WT_pos, bool &traj_finish) {
        double eval_t = (ros_ptr_->getSimTime() - cmd_traj_info_.getStartWallTime());
        traj_finish = false;
        double total_dur = cmd_traj_info_.getTotalDuration();
        if (eval_t > total_dur) {
            traj_finish = true;
            eval_t = total_dur;
        }
        start_WT_pos = cmd_traj_info_.getStartWallTime();
        if (cmd_traj_info_.backupTrajAvilibale() && eval_t > cmd_traj_info_.getBackupTrajStartTT()) {
            robot_on_backup_traj_ = true;
        } else {
            robot_on_backup_traj_ = false;
        }
    }

    Trajectory SuperPlanner::getCommittedPositionTrajectory() {
        return cmd_traj_info_.posTraj();
    }

    Trajectory SuperPlanner::getCommittedYawTrajectory() {
        return cmd_traj_info_.yawTraj();
    }

    bool SuperPlanner::generateYawOnlyTraj(const double target_yaw, double &yaw_goal_out,
                                           Trajectory &out_traj) {
        /* Step 1: allocate the target yaw BEFORE optimization — the shortest
         * circle path from the live odometry heading, as a continuous euler
         * value (e.g. odom=-170 deg, target=179 deg -> -181 deg). Optimizing
         * the raw target would let the minAcc interpolation wind 349 deg
         * around the +/-pi boundary instead of the 11 deg direct turn. */
        yaw_goal_out = target_yaw;
        super_planner::geometry_utils::normalizeNextYaw(robot_state_.yaw, yaw_goal_out);

        /* Step 2: standstill position trajectory; its duration is the
         * trapezoidal yaw-limit time (accel + cruise + decel). */
        const double delta = std::fabs(yaw_goal_out - robot_state_.yaw);
        const double t_acc = cfg_.yaw_acc_max > 1e-6 ? cfg_.yaw_dot_max / cfg_.yaw_acc_max : 0.0;
        const double dur = std::max(2.0, 2.0 * t_acc + delta / std::max(1e-6, cfg_.yaw_dot_max));
        const Vec3f p = robot_state_.p;
        Eigen::Matrix<double, 3, 2> pos_istate, pos_gstate;
        pos_istate << p, Eigen::Vector3d::Zero();
        pos_gstate << p, Eigen::Vector3d::Zero();
        Eigen::Matrix<double, 3, -1> empty_wps(3, 0);
        Eigen::VectorXd seg_times(1);
        seg_times(0) = dur;
        const Trajectory pos_traj =
            super_planner::geometry_utils::poly_interpo::minimumAccInterpolation<3>(
                pos_istate, pos_gstate, empty_wps, seg_times);

        /* Step 3: yaw optimization over the allocated (already continuous)
         * init -> goal pair; euler-space interpolation is then shortest-path
         * by construction. */
        const super_planner::super_utils::Vec4f yaw_istate(
            robot_state_.yaw, 0.0, 0.0, 0.0);
        const super_planner::super_utils::Vec4f yaw_gstate(
            yaw_goal_out, 0.0, 0.0, 0.0);
        if (!yaw_traj_opt_->optimize(yaw_istate, yaw_gstate, pos_traj, out_traj, 3, false, false)) {
            SLOG_EVENT(slog::Level::warn, "yaw_only_traj_failed", {
                    slog::F("target_yaw", target_yaw),
                    slog::F("odom_yaw", robot_state_.yaw),
            });
            return false;
        }
        SLOG_EVENT(slog::Level::info, "yaw_only_traj_alloc", {
                slog::F("odom_yaw", robot_state_.yaw),
                slog::F("goal_yaw_alloc", yaw_goal_out),
                slog::F("duration", dur),
        });
        return true;
    }

    double SuperPlanner::getPreYawTarget() {
        cmd_traj_info_.lock();
        if (cmd_traj_info_.empty()) {
            cmd_traj_info_.unlock();
            return NAN;
        }
        /* Same heading definition as the online yaw tracker and the mid-flight
         * mismatch trigger (look-ahead chord at t=0, shared
         * getLookaheadChordYaw): the drone converges to exactly what FOLLOW_TRAJ
         * commands on resume. Three-point near-start sampling is retired: on
         * rest-to-rest trajectories the first 0.5 s of horizontal motion is
         * < 0.1 m (accelerating from standstill), which misclassified every
         * normal start as near-vertical (pre-yaw NAN, yaw never corrected,
         * tangent-yaw mismatch every replan -> YAWING/FOLLOW_TRAJ deadlock). */
        const double yaw = getLookaheadChordYaw(0.0);
        cmd_traj_info_.unlock();
        return yaw;
    }

    /* The heading the online yaw tracker commands at eval_t: the chord from the
     * current trajectory position to the look-ahead point, with the same
     * slow-start retry semantics as getOneCommandFromTraj. Caller must hold
     * the committed-traj lock. */
    double SuperPlanner::getLookaheadChordYaw(const double eval_t) {
        const double total_dur = cmd_traj_info_.getTotalDuration();
        if (eval_t < 0.0 || eval_t > total_dur) return NAN;
        const Vec3f p0 = cmd_traj_info_.getPos(eval_t);
        double tf = std::min(eval_t + cfg_.yaw_time_forward, total_dur);
        Vec3f dir = cmd_traj_info_.getPos(tf) - p0;
        /* Slow rest-to-rest starts (v ~0.05-0.35 m/s for short goals) move less
         * than 0.1 m in one yaw_time_forward: step the look-ahead in 0.5 s steps
         * (up to the trajectory end) so the chord stays defined for the tracker,
         * the pre-yaw target and the mismatch trigger alike. */
        for (int retry = 0; retry < 3 && dir.head(2).norm() < 0.1; retry++) {
            tf = std::min(tf + 0.5, total_dur);
            dir = cmd_traj_info_.getPos(tf) - p0;
        }
        if (dir.head(2).norm() < 0.1) return NAN;
        return atan2(dir.y(), dir.x());
    }

    double SuperPlanner::getTrajTangentYawNow() {
        cmd_traj_info_.lock();
        if (cmd_traj_info_.empty()) {
            cmd_traj_info_.unlock();
            return NAN;
        }
        const double eval_t = ros_ptr_->getSimTime() - cmd_traj_info_.getStartWallTime();
        /* Same heading definition as the online yaw tracker (look-ahead chord):
         * the mismatch trigger must compare against what the drone is actually
         * commanded to do, not the instantaneous tangent (which diverges from the
         * look-ahead chord by >30 deg in curves and spuriously triggers YAWING). */
        const double yaw = getLookaheadChordYaw(eval_t);
        cmd_traj_info_.unlock();
        return yaw;
    }

    void SuperPlanner::resetTrajStartWallTime(double new_start_WT) {
        cmd_traj_info_.lock();
        cmd_traj_info_.setStartWallTime(new_start_WT);
        cmd_traj_info_.unlock();
    }

    void SuperPlanner::clearCommittedTraj() {
        cmd_traj_info_.lock();
        cmd_traj_info_.setEmpty();
        cmd_traj_info_.unlock();
    }

    void SuperPlanner::stepOnlineYaw(double cur_time, double target_yaw,
                                     double &yaw, double &yaw_dot) {
        if (!yaw_time_init_) {
            /* Sync commanded yaw from current odometry on first call. */
            last_yaw_ = robot_state_.yaw;
            last_yawdot_ = 0.0;
            yaw_time_last_ = cur_time;
            yaw_time_init_ = true;
            yaw = last_yaw_;
            yaw_dot = 0.0;
            return;
        }

        double dt = cur_time - yaw_time_last_;
        yaw_time_last_ = cur_time;
        if (dt <= 1e-6) {
            yaw = last_yaw_;
            yaw_dot = 0.0;
            return;
        }

        double d_yaw = target_yaw - last_yaw_;
        if (d_yaw > M_PI) d_yaw -= 2 * M_PI;
        if (d_yaw < -M_PI) d_yaw += 2 * M_PI;

        const double YDM = d_yaw >= 0 ? cfg_.yaw_dot_max : -cfg_.yaw_dot_max;
        const double YDDM = d_yaw >= 0 ? cfg_.yaw_acc_max : -cfg_.yaw_acc_max;

        double d_yaw_max;
        if (fabs(last_yawdot_ + dt * YDDM) <= fabs(YDM)) {
            d_yaw_max = last_yawdot_ * dt + 0.5 * YDDM * dt * dt;
        } else {
            double t1 = (YDM - last_yawdot_) / YDDM;
            d_yaw_max = (last_yawdot_ * t1 + 0.5 * YDDM * t1 * t1) + YDM * (dt - t1);
        }

        if (fabs(d_yaw) > fabs(d_yaw_max)) {
            d_yaw = d_yaw_max;
        }
        yaw_dot = d_yaw / dt;

        last_yaw_ = last_yaw_ + d_yaw;
        last_yawdot_ = yaw_dot;

        /* Publish on S^1: normalize the output to [-pi, pi]; last_yaw_ keeps the
         * unwrapped continuous angle for internal shortest-path continuity. */
        yaw = last_yaw_;
        while (yaw > M_PI) yaw -= 2 * M_PI;
        while (yaw < -M_PI) yaw += 2 * M_PI;
    }


    void SuperPlanner::getOneCommandFromTraj(StatePVAJ &pvaj,
                                             double &yaw,
                                             double &yaw_dot,
                                             bool &on_backup_traj,
                                             bool &traj_finish) {
        cmd_traj_info_.lock();
        const double &cur_t = ros_ptr_->getSimTime();
        const double &cmd_start_WT = cmd_traj_info_.getStartWallTime();
        const double &total_dur = cmd_traj_info_.getTotalDuration();

        traj_finish = (cur_t - cmd_start_WT) > total_dur;
        const double &eval_t = traj_finish ? total_dur : (cur_t - cmd_start_WT);

        robot_on_backup_traj_ = cmd_traj_info_.isTTOnBackupTraj(eval_t);
        on_backup_traj = robot_on_backup_traj_;

        pvaj = cmd_traj_info_.posTraj().getState(eval_t);

        /// Get Yaw planning
        if (cfg_.online_yaw_en) {
            /* Shared look-ahead chord heading (same definition as the mid-flight
             * mismatch trigger in getTrajTangentYawNow). */
            const double lookahead_yaw = getLookaheadChordYaw(eval_t);
            double target_yaw = last_yaw_;
            if (!isnan(lookahead_yaw)) {
                target_yaw = lookahead_yaw;
                /* Unwrap target_yaw to maintain continuity. */
                double d = target_yaw - last_yaw_;
                while (d > M_PI) d -= 2 * M_PI;
                while (d < -M_PI) d += 2 * M_PI;
                target_yaw = last_yaw_ + d;
            }
            stepOnlineYaw(cur_t, target_yaw, yaw, yaw_dot);
        } else {
            static double last_yaw_poly = robot_state_.yaw;
            yaw = cmd_traj_info_.getYaw(eval_t)[0];
            yaw_dot = cmd_traj_info_.getYawRate(eval_t)[0];
            if (isnan(yaw)) {
                yaw = last_yaw_poly;
                yaw_dot = 0;
            } else {
                last_yaw_poly = yaw;
            }
            if (isnan(yaw_dot)) {
                yaw_dot = 0;
            }
        }

        cmd_traj_info_.unlock();
    }


    void SuperPlanner::getModuleTimeConsuming(vector<double> &time) {
        time = time_consuming_;
        std::fill(time_consuming_.begin(), time_consuming_.end(), 0);
    }


    RET_CODE SuperPlanner::generateExpTraj(ExpTraj &last_exp_traj_info, ExpTraj &out_exp_traj_info) {
        /* 1) Log the exp traj frontend time*/
        TimeConsuming t_exp_frontend("t_exp_frontend", false);

        // use hot init or not, just prepare a guide path, a guide t, init and fina state and sfc for exp traj opt
        StatePVAJ pos_init_state, pos_fina_state;
        PolytopeVec sfc;
        vec_Vec3f guide_path;
        // the guide_stamp saves a TT
        vector<double> guide_stamp;
        double guide_path_end_vel{0.0};
        int reserve_size = cfg_.planning_horizon / cfg_.resolution * 1.2;
        guide_path.reserve(reserve_size);
        guide_stamp.reserve(reserve_size);

        Vec4f init_yaw{robot_state_.yaw, 0, 0, 0};
        Vec4f fina_yaw{0, 0, 0, 0};


        // alias for last_exp_traj_info
        Trajectory guide_pos_traj, guide_yaw_traj, last_exp_traj;

        // record the wall time (WT) and the trajectory time (TT) at the start of the replan.
        const double replan_process_start_WT = ros_ptr_->getSimTime();
        double replan_process_start_TT, replan_state_TT;

        /* 2) Check last exp traj */
        if (last_exp_traj_info.empty()) {
            /* 2.1) Perform rest2rest exp traj generation */
            // just skip the first part of the guide trajectory
            pos_init_state.setZero();
            pos_init_state.col(0) = local_start_p_;
            replan_process_start_TT = -1;
            replan_state_TT = -1;
        } else {
            guide_pos_traj = cmd_traj_info_.posTraj(); // last_exp_traj;
            guide_yaw_traj = cmd_traj_info_.yawTraj(); //last_exp_traj_info.exp_yaw_traj;
            last_exp_traj = last_exp_traj_info.posTraj();

            replan_process_start_TT = replan_process_start_WT - last_exp_traj.start_WT;
            replan_state_TT = replan_process_start_TT + cfg_.replan_forward_dt;
            /* 2.2) Perform collision check on last exp traj*/
            vector<TimePosPair> last_exp_traj_time_pos;
            vector<double> last_exp_traj_vel;


            // check early exit condition
            // 1) if the replan state is beyond the last cmd traj, return NO_NEED
            if (replan_state_TT >= cmd_traj_info_.getTotalDuration()) {
                out_exp_traj_info = last_exp_traj_info;

                if (robot_on_backup_traj_) {
                    if (cfg_.print_log)
                        ros_ptr_->warn(
                                " -- [SUPER] Replan, emergency stop, return FAILED and wait for plan form rest.");
                    return FAILED;
                }

                if (cfg_.print_log) {
                    ros_ptr_->warn(
                            " -- [generateExpTraj] replan_state_TT >= cmd_traj_info_.pos_traj.getTotalDuration(), return NONEED and wait for plan form rest.");
                }
                return NO_NEED;
            }

            if (!last_exp_traj_info.empty()) {
                if (replan_state_TT >= last_exp_traj.getTotalDuration()) {
                    out_exp_traj_info = last_exp_traj_info;
                    if (cfg_.print_log)
                        ros_ptr_->warn(
                                " -- [generateExpTraj] replan_state_TT >= last_exp_traj.getTotalDuration(), return NONEED and wait for plan form rest.");
                    if (robot_on_backup_traj_) {
                        if (cfg_.print_log)
                            ros_ptr_->warn(
                                    " -- [SUPER] Replan, emergency stop, return FAILED and wait for plan form rest.");
                        return FAILED;
                    } else {
                        return NO_NEED;
                    }
                }

                /// 1) Check a series of early termination conditions.
                if (!gi_.new_goal && last_exp_traj_info.getSFCSize() == 1 && last_exp_traj_info.connectedToGoal()) {
                    if (cfg_.print_log) {
                        ros_ptr_->warn(
                                " -- [SUPER] Replan, last exp have only one corridor and connected to goal return NONEED.");
                    }

                    out_exp_traj_info = last_exp_traj_info;
                    if (robot_on_backup_traj_) {
                        if (cfg_.print_log)
                            ros_ptr_->warn(
                                    " -- [SUPER] Replan, emergency stop, return FAILED and wait for plan form rest.");
                        return FAILED;
                    } else {
                        return NO_NEED;
                    }
                }

                if (!gi_.new_goal && gi_.wp_lookahead.empty() &&
                    (gi_.goal_p - last_exp_traj.getPos(replan_state_TT)).norm() < cfg_.resolution * 3) {
                    // Return if the traj close to goal
                    out_exp_traj_info = last_exp_traj_info;
                    out_exp_traj_info.setGoalConnectedFlag(true);

                    ros_ptr_->warn(" -- [SUPER] Replan, close to goal and return NONEED.");
                    if (robot_on_backup_traj_) {
                        ros_ptr_->warn(
                                " -- [SUPER] Replan, emergency stop, return FAILED and wait for plan form rest.");
                        return FAILED;
                    } else {
                        return NO_NEED;
                    }
                }
            }
            /// Ready for replan.
            out_exp_traj_info.setGoalConnectedFlag(false);

            // * 2) Check if in backup trajectory. While in backup trajectory,
            // *    the guide trajectory should be a part of cmd trajectory.
            // TODO: Why cannot directly replan on cmd traj? 241121

            // * 3) Perform collision check on the guide trajectory.
            // TODO 0929 critical change for hot init.
            double eval_t = replan_state_TT; //replan_process_start_TT;
            double guide_pos_traj_total_time = guide_pos_traj.getTotalDuration();

            Vec3f temp_pt, last_sample_pt;
            last_exp_traj_time_pos.clear();
            last_exp_traj_info.setWholeTrajKnownFreeFlag(true);
            last_sample_pt = guide_pos_traj.getPos(eval_t);
            eval_t += cfg_.sample_traj_dt;
            // * 4) 记录replan点在evaluated_pts上的id
            int replan_id = -1;
            for (; eval_t < guide_pos_traj_total_time; eval_t += cfg_.sample_traj_dt) {
                temp_pt = guide_pos_traj.getPos(eval_t);
                if ((temp_pt - last_sample_pt).norm() < cfg_.resolution * 0.8) {
                    continue;
                }

                super_planner::rog_map::GridType temp_grid = map_ptr_->getInfGridType(temp_pt);

                if (temp_grid == super_planner::rog_map::GridType::OCCUPIED || temp_grid == super_planner::rog_map::GridType::OUT_OF_MAP) {
                    last_exp_traj_info.setWholeTrajKnownFreeFlag(false);
                    break;
                }
                if (eval_t > replan_state_TT && replan_id == -1) {
                    replan_id = last_exp_traj_time_pos.size();
                }
                last_exp_traj_time_pos.emplace_back(eval_t, temp_pt);
                last_exp_traj_vel.emplace_back(guide_pos_traj.getVel(eval_t).norm());
                last_sample_pt = temp_pt;
            }


            // * 6) Decide where to split the original exp trajecory and re-plan a new one with an A*,
            // *    If the whole trajectory if free,  the whole trajectory should be receding and if not, or a new goal
            // *    is given, we should only receiding a small distance and replan new trajectory ASAP
            double split_dis = cfg_.receding_dis;
            if (last_exp_traj_info.wholeTrajKnownFree() && !gi_.new_goal && cfg_.receding_dis > 0.0) {
                split_dis = std::numeric_limits<double>::max();
            }


            // * 7）Begin replan process, first get the replan state from the committed trajectory.
            if (!guide_pos_traj.getState(replan_state_TT, pos_init_state)) {
                ros_ptr_->warn(" -- [SUPER] Invalid traj or eval t");
                return FAILED;
            }
            // * Generate guide path with time stampe, for hot trajectory initialization
            // * the guide stamp is time from the replan start t
            guide_stamp.clear();
            guide_path.clear();
            if (split_dis <= 0 || last_exp_traj_time_pos.empty()) {
                /// No need receding, just path search.
                guide_path.push_back(pos_init_state.col(0));
                guide_stamp.push_back(0.0);
                last_exp_traj_time_pos.clear();
                last_exp_traj_time_pos.emplace_back(replan_state_TT, pos_init_state.col(0));
                guide_path_end_vel = robot_state_.v.norm();
            } else {
                temp_pt = last_exp_traj_time_pos.back().second;
                // * 8) Pop all evaluated pts after the sampled point.
                while (map_ptr_->isOccupiedInflate(temp_pt) ||
                       (temp_pt - pos_init_state.col(0)).norm() > split_dis) {
                    last_exp_traj_time_pos.pop_back();
                    last_exp_traj_vel.pop_back();
                    if (last_exp_traj_time_pos.empty()) {
                        ros_ptr_->warn(" -- [SUPER] WARN, all traj is collide in INF2");
                        break;
                    }
                    temp_pt = last_exp_traj_time_pos.back().second;
                }
                if (!last_exp_traj_time_pos.empty()) {
                    for (long unsigned int i = 0; i < last_exp_traj_time_pos.size(); i++) {
                        guide_path.push_back(last_exp_traj_time_pos[i].second);
                        guide_stamp.push_back(last_exp_traj_time_pos[i].first - last_exp_traj_time_pos.front().first);
                        guide_path_end_vel = last_exp_traj_vel[i];
                    }
                } else {
                    guide_path.push_back(pos_init_state.col(0));
                    guide_stamp.push_back(0.0);
                    last_exp_traj_time_pos.emplace_back(replan_state_TT, pos_init_state.col(0));
                    guide_path_end_vel = robot_state_.v.norm();
                }
            }
        }

        // second, geometry part of the guide path
        ///=================The Second Part of Guide Path ================================================

        if (guide_path.empty() ||
            ((guide_path.front() - pos_init_state.col(0)).norm() > 1e-2)) {
            guide_path.insert(guide_path.begin(), pos_init_state.col(0));
            guide_stamp.insert(guide_stamp.begin(), 0.0);
        }

        /* Risk-driven planning horizon and velocity bound: both are fed by the
         * per-corridor occupancy risk computed after the SFC search below; the
         * values used here come from the previous replan cycle (low-pass
         * filtered), falling back to the static config on the first cycle.
         * The fresh velocity bound is applied to the optimizers right before
         * trajectory optimization. */
        double eff_horizon = cfg_.planning_horizon;
        if (cfg_.adaptive_horizon_en && adaptive_horizon_ > 0.0) {
            eff_horizon = adaptive_horizon_;
        }

        double eff_max_vel = cfg_.exp_traj_cfg.max_vel;
        if (cfg_.risk_en) {
            /* First cycle has no risk history: start conservative (vel_min)
             * instead of full speed; the bound ramps up within a few cycles. */
            eff_max_vel = (risk_vel_ > 0.0) ? risk_vel_ : cfg_.risk_vel_min;
        }

        const double guide_path_prefix_len = super_planner::geometry_utils::computePathLength(guide_path);
        const size_t guide_path_prefix_size = guide_path.size();
        const size_t guide_stamp_prefix_size = guide_stamp.size();

        vector<int> path_passed_waypoint_id;
        vec_Vec3f inside_poly_goals;
        vector<int> sfc_waypoint_ids;
        /* Intermediate waypoints fully reached by the chained A* within the horizon;
         * handed to the exp_traj optimizer as soft pass-through constraints. */
        vec_E<Vec3f> pass_wps;

        /* Geometric extension of the guide path; returns false on truncate /
         * path-search failure so the caller can retry with a shorter horizon. */
        auto try_extend_guide = [&](const double temp_horizon) -> bool {
        // if need a geometry path
        if (temp_horizon > cfg_.resolution * 2) {
            /* Waypoint chain: current target first, then the reprojected lookahead
             * waypoints. A* searches segment by segment within the remaining horizon
             * budget, so the guide path passes through every reachable reprojected
             * waypoint instead of stopping at the first target. */
            vec_E<Vec3f> wp_chain;
            wp_chain.push_back(gi_.goal_p);
            for (const auto &wp : gi_.wp_lookahead) {
                wp_chain.push_back(wp);
            }
            double searched_len{0.0};
            for (size_t w = 0; w < wp_chain.size(); w++) {
                const double remain_horizon = temp_horizon - searched_len;
                if (remain_horizon <= cfg_.resolution * 2) {
                    break;
                }
                const Vec3f &wp = wp_chain[w];
                const bool has_next = (w + 1 < wp_chain.size());
                // if the waypoint is close to the last point of the guide path, just append it
                if ((guide_path.back() - wp).norm() < cfg_.resolution * 5) {
                    searched_len += (guide_path.back() - wp).norm();
                    guide_stamp.push_back(guide_stamp.back() +
                                          (guide_path.back() - wp).norm() / eff_max_vel);
                    guide_path.push_back(wp);
                    if (has_next) {
                        pass_wps.push_back(wp);
                    }
                    continue;
                }
                vec_Vec3f new_path;
                /* Truncate the waypoint onto the remaining planning horizon before
                 * searching, so the A* path ends at a well-defined point on the straight
                 * line toward the real waypoint instead of at wherever the search front
                 * runs out of budget. */
                Vec3f eff_goal = wp;
                const Vec3f seg_start = guide_path.back();
                const double seg_dis = (wp - seg_start).norm();
                bool truncated{false};
                if (seg_dis > remain_horizon) {
                    truncated = true;
                    const Vec3f dir = (wp - seg_start).normalized();
                    double proj_l = remain_horizon;
                    eff_goal = seg_start + dir * proj_l;
                    int proj_iter = 20;
                    while (map_ptr_->isOccupiedInflate(eff_goal) && proj_iter-- > 0) {
                        proj_l -= cfg_.resolution * 5;
                        if (proj_l < cfg_.resolution * 10) {
                            SLOG_EVENT(slog::Level::warn, "goal_truncate_failed", {
                                    slog::F("goal", fmt::format("{}", wp.transpose())),
                                    slog::F("temp_horizon", remain_horizon),
                            });
                            return false;
                        }
                        eff_goal = seg_start + dir * proj_l;
                    }
                    map_ptr_->getNearestInfCellNot(OCCUPIED, eff_goal, eff_goal, 1.0);
                    SLOG_EVENT(slog::Level::info, "goal_truncated", {
                            slog::F("original_dis", seg_dis),
                            slog::F("temp_horizon", remain_horizon),
                            slog::F("eff_goal", fmt::format("{}", eff_goal.transpose())),
                            slog::F("goal", fmt::format("{}", wp.transpose())),
                    });
                }
                if (!PathSearch(seg_start, eff_goal, remain_horizon, new_path)) {
                    SLOG_EVENT(slog::Level::warn, "path_search_failed", {
                            slog::F("seg_idx", w),
                            slog::F("start", fmt::format("{}", guide_path.back().transpose())),
                            slog::F("goal", fmt::format("{}", eff_goal.transpose())),
                            slog::F("temp_horizon", remain_horizon),
                            slog::F("dist_to_goal", (robot_state_.p - gi_.goal_p).norm()),
                            slog::F("guide_path_len", super_planner::geometry_utils::computePathLength(guide_path)),
                    });
                    ros_ptr_->warn(" -- [SUPER] PathSearch for new path failed");
                    return false;
                }
                if (new_path.size() < 2) {
                    SLOG_EVENT(slog::Level::warn, "path_search_too_short", {
                            slog::F("seg_idx", w),
                            slog::F("start", fmt::format("{}", guide_path.back().transpose())),
                            slog::F("goal", fmt::format("{}", eff_goal.transpose())),
                            slog::F("temp_horizon", remain_horizon),
                            slog::F("new_path_size", new_path.size()),
                    });
                    ros_ptr_->warn(" -- [SUPER] PathSearch for new path failed");
                    return false;
                }

                /* Drop consecutive duplicate grid points (A* may repeat the snapped start
                 * cell); they corrupt the backward distance accumulation below. */
                {
                    vec_Vec3f filtered;
                    filtered.reserve(new_path.size());
                    filtered.push_back(new_path.front());
                    for (size_t pi = 1; pi < new_path.size(); pi++) {
                        if ((new_path[pi] - filtered.back()).norm() > 1e-3) {
                            filtered.push_back(new_path[pi]);
                        }
                    }
                    new_path.swap(filtered);
                }

                // compute total dis
                // backward compute dis for all points
                double total_dis{0.0};
                vector<double> dis(new_path.size());
                Vec3f last_p = new_path.back();
                for (int i = new_path.size() - 2; i >= 0; i--) {
                    auto d = (new_path[i] - last_p).norm();
                    total_dis += d;
                    dis[i+1] = total_dis;
                    last_p = new_path[i];
                }
                total_dis += (new_path.front() - guide_path.back()).norm();
                dis[0] = total_dis;
//                for (int i = 0; i < dis.size(); i++) {
//                    cout << dis[i] << " ";
//                }
//                cout << endl;
                vector<double> stamps(new_path.size(), 0);
                vector<double> dt(new_path.size(), 0);
                double last_stamp = 0;
                for (int i = dis.size() - 1; i >= 0; i--) {
                    double vel;
                    super_planner::geometry_utils::simplePMTimeAllocator(cfg_.exp_traj_cfg.max_acc, eff_max_vel,
                                                          guide_path_end_vel,
                                                          total_dis,
                                                          dis[i], stamps[i], vel);
                    dt[i] = stamps[i] - last_stamp;
                    last_stamp = stamps[i];
                }
                double time_stamp = guide_stamp.back();

//                for (int i = 0; i < stamps.size(); i++) {
//                    cout << stamps[i] << " ";
//                }
//                cout << endl;
//
//                for (int i = 0; i < dt.size(); i++) {
//                    cout << dt[i] << " ";
//                }
//                cout << endl;

                double seg_path_len{0.0};
                for (long unsigned int i = 1; i < new_path.size(); i++) {
                    double t = dt[i];
                    if (std::isnan(t) || t < 0.0) {
                        SLOG_EVENT(slog::Level::warn, "guide_dt_nan", {
                                slog::F("seg", w),
                                slog::F("i", i),
                                slog::F("dis", dis[i]),
                                slog::F("total_dis", total_dis),
                                slog::F("end_vel", guide_path_end_vel),
                                slog::F("stamps", stamps[i]),
                        });
                    }
                    time_stamp += t;
                    seg_path_len += (new_path[i] - new_path[i - 1]).norm();
                    guide_path.emplace_back(new_path[i]);
                    guide_stamp.emplace_back(time_stamp);
                }
                searched_len += seg_path_len;
                if (truncated) {
                    break;
                }
                if (has_next) {
                    pass_wps.push_back(wp);
                }
            }
            /* The chain tail is the trajectory terminal, not a pass-through constraint. */
            while (!pass_wps.empty() && (pass_wps.back() - guide_path.back()).norm() < cfg_.resolution) {
                pass_wps.pop_back();
            }
        }
        return true;
        };

        /* Reactive horizon shrink: restore the receding prefix and retry with a
         * shorter budget instead of failing the replan outright. */
        /* Reactive horizon shrink covers BOTH the A* extension and the SFC
         * generation: a corridor that fails in tight space can succeed on a
         * shorter guide path, so retry the whole geom+SFC chain with a shorter
         * budget instead of failing the replan outright. */
        bool geom_ok = false, sfc_ok = false;
        double horizon_try = eff_horizon;
        for (int attempt = 0; attempt < std::max(1, cfg_.horizon_shrink_max_attempts); attempt++) {
            guide_path.resize(guide_path_prefix_size);
            guide_stamp.resize(guide_stamp_prefix_size);
            pass_wps.clear();
            geom_ok = try_extend_guide(horizon_try - guide_path_prefix_len);
            if (geom_ok) {
                sfc.clear();
                shifted_sfc_start_pt_ = Vec3f(9999,9999,9999);
                TimeConsuming t_exp_sfc("t_exp_sfc", false);
                sfc_ok = cg_ptr_->SearchPolytopeOnPath(guide_path, sfc, shifted_sfc_start_pt_, cfg_.use_fov_cut);
                last_exp_sfc_t_ = t_exp_sfc.stop();
                if (sfc_ok) break;
                SLOG_EVENT(slog::Level::warn, "sfc_failed", {
                        slog::F("attempt", attempt),
                        slog::F("guide_path_size", guide_path.size()),
                        slog::F("guide_path_len", super_planner::geometry_utils::computePathLength(guide_path)),
                        slog::F("dist_to_goal", (robot_state_.p - gi_.goal_p).norm()),
                });
            }
            horizon_try = std::max(cfg_.planning_horizon_min, horizon_try * cfg_.horizon_shrink_factor);
            if (attempt + 1 < std::max(1, cfg_.horizon_shrink_max_attempts)) {
                SLOG_EVENT(slog::Level::warn, "horizon_shrink_retry", {
                        slog::F("attempt", attempt + 1),
                        slog::F("next_horizon", horizon_try),
                });
            }
        }
        if (!sfc_ok) {
            ros_ptr_->warn(" -- [SUPER] Guide path extension or SFC generation failed after all horizon attempts.");
            {
                ExpOptCaseData case_data;
                case_data.stage = "frontend";
                case_data.reason = forced_dump_reason_.empty() ? (geom_ok ? "sfc_failed" : "guide_path_failed")
                                   : std::string(geom_ok ? "sfc_failed," : "guide_path_failed,") + forced_dump_reason_;
                forced_dump_reason_.clear();
                case_data.connected_goal = false;
                case_data.head_pvaj = pos_init_state;
                case_data.guide_path = guide_path;
                case_data.guide_t = guide_stamp;
                case_data.pass_wps = pass_wps;
                case_data.sfc_time = last_exp_sfc_t_;
                queueCaseDump(case_data);
            }
            return FAILED;
        }

        bool connected_goal = (guide_path.back().head(2) - gi_.goal_p.head(2)).norm() < cfg_.resolution * 2;
        out_exp_traj_info.setGoalConnectedFlag(connected_goal);

        {
            TimeConsuming t_viz("tviz", false);
            ros_ptr_->vizFrontendPath(guide_path);
            ros_ptr_->publishSearchPath(guide_path);
            time_consuming_[VISUALIZATION] += t_viz.stop();
        }

        /* The corridor may legitimately end early at the local-map boundary
         * (hit_map_bound): trim the guide tail to the last point covered by the
         * SFC so the optimizer terminal state stays inside a polytope instead of
         * deterministically failing SimplifySFC ("Ill corridor"). */
        if (!sfc.empty() && !sfc.back().PointIsInside(guide_path.back())) {
            while (guide_path.size() > 2 && !sfc.back().PointIsInside(guide_path.back())) {
                if (!pass_wps.empty() && (pass_wps.back() - guide_path.back()).norm() < cfg_.resolution) {
                    pass_wps.pop_back();
                }
                guide_path.pop_back();
                guide_stamp.pop_back();
            }
            connected_goal = (guide_path.back().head(2) - gi_.goal_p.head(2)).norm() < cfg_.resolution * 2;
            out_exp_traj_info.setGoalConnectedFlag(connected_goal);
            SLOG_EVENT(slog::Level::warn, "guide_tail_trimmed", {
                    slog::F("new_tail", fmt::format("{}", guide_path.back().transpose())),
                    slog::F("guide_path_size", guide_path.size()),
                    slog::F("sfc_count", sfc.size()),
            });
        }
        {
            TimeConsuming t_viz("tviz", false);
            ros_ptr_->vizExpSfc(sfc);
            time_consuming_[VISUALIZATION] += t_viz.stop();
        }

        /* Per-corridor occupancy risk: flattened-ellipsoid neighborhood around
         * each seed-line center, max occupancy probability inside. The
         * horizontal radius is the geometric length of the currently committed
         * trajectory — the region the drone is committed to fly through —
         * falling back to half the receding distance on the first goal
         * (nothing committed yet); the vertical half-extent is robot_r so the
         * floor/ceiling at cruise altitude does not peg the score.
         * The aggregate max risk drives the velocity bound (fresh, applied
         * below) and the next cycle's planning horizon (via the smoothed
         * members consumed at the top of this function). */
        if (cfg_.risk_en && !sfc.empty()) {
            const double commit_len = committedTrajLength();
            const double risk_radius = std::min(commit_len > 0.0 ? commit_len
                                                                 : cfg_.receding_dis / 2.0,
                                                cfg_.risk_radius_max);
            double max_risk = 0.0;
            for (auto &poly : sfc) {
                const Vec3f mid = (poly.seed_line.first + poly.seed_line.second) / 2.0;
                poly.risk_score = cg_ptr_->computeRiskScore(mid, risk_radius, cfg_.robot_r);
                max_risk = std::max(max_risk, poly.risk_score);
            }
            const double ratio = std::min(std::max(
                    (max_risk - cfg_.risk_th_low) /
                    (cfg_.risk_th_high - cfg_.risk_th_low), 0.0), 1.0);
            const double v_raw = cfg_.risk_vel_min +
                                 (1.0 - ratio) * (cfg_.risk_vel_max - cfg_.risk_vel_min);
            /* Conservative seed: ramp up from vel_min through the low-pass
             * filter instead of jumping straight to v_raw on the first
             * cycle, so takeoff never starts at full speed. */
            if (risk_vel_ <= 0.0) risk_vel_ = cfg_.risk_vel_min;
            risk_vel_ = cfg_.risk_vel_smooth * risk_vel_ +
                        (1.0 - cfg_.risk_vel_smooth) * v_raw;
            /* Asymmetric slew limit: the bound may rise freely but may only
             * fall by max_drop per replan. The exp/backup problems start from
             * the current flight state; a bound that drops faster than the
             * drone can brake puts the init state in violation and the replan
             * fails (hard-brake / freeze behavior). */
            risk_vel_ = std::max(risk_vel_, risk_vel_prev_ - cfg_.risk_vel_max_drop);
            risk_vel_prev_ = risk_vel_;
            /* The backup trajectory starts from a point on the (possibly fast)
             * exp trajectory; its velocity bound must cover that initial speed
             * or the backup problem is infeasible and every replan fails. */
            exp_traj_opt_->setMaxVelBound(risk_vel_);
            back_traj_opt_->setMaxVelBound(risk_vel_);
            SLOG_EVENT(slog::Level::debug, "risk_vel", {
                    slog::F("max_risk", max_risk),
                    slog::F("v_raw", v_raw),
                    slog::F("v_smooth", risk_vel_),
                    slog::F("radius", risk_radius),
            });

            if (cfg_.adaptive_horizon_en) {
                const double h_raw = cfg_.planning_horizon_min +
                                     (1.0 - ratio) * (cfg_.planning_horizon_max - cfg_.planning_horizon_min);
                /* Conservative seed: ramp up from planning_horizon_min. */
                if (adaptive_horizon_ <= 0.0) adaptive_horizon_ = cfg_.planning_horizon_min;
                adaptive_horizon_ = cfg_.adaptive_horizon_smooth * adaptive_horizon_ +
                                    (1.0 - cfg_.adaptive_horizon_smooth) * h_raw;
                SLOG_EVENT(slog::Level::debug, "risk_horizon", {
                        slog::F("max_risk", max_risk),
                        slog::F("h_raw", h_raw),
                        slog::F("h_smooth", adaptive_horizon_),
                });
            }
        }

        time_consuming_[EPX_TRAJ_FRONTEND] = t_exp_frontend.stop();


        pos_fina_state.setZero();
        pos_fina_state.col(0) = guide_path.back();
        if (cfg_.goal_vel_en && (gi_.goal_p - robot_state_.p).norm() > cfg_.planning_horizon / 2) {
            pos_fina_state.col(1) = (gi_.goal_p - robot_state_.p).normalized() * eff_max_vel / 2;
        }
        if ((pos_fina_state.col(0) - gi_.goal_p).norm() < cfg_.resolution * 2) {
            pos_fina_state.col(1).setZero();
            pos_fina_state.col(0) = gi_.goal_p;
        }

        // optimize and update exp traj
        bool temp_ret;
        Trajectory out_traj;
        TimeConsuming t_exp_opt("t_exp_opt", false);
        auto original_sfc = sfc;
        temp_ret = exp_traj_opt_->optimize(pos_init_state,
                                           pos_fina_state,
                                           guide_path,
                                           guide_stamp,
                                           sfc,
                                           out_traj,
                                           pass_wps);
        time_consuming_[EXP_TRAJ_OPT] = t_exp_opt.stop();
        {
            VecDf init_ts;
            vec_Vec3f init_ps;
            exp_traj_opt_->getInitValue(init_ts, init_ps);
            latest_replan.setExpCondition(init_ts, init_ps, pos_init_state, pos_fina_state, sfc);
        }
        {
            /* Corner-case detection: collect every triggered reason and dump the
             * full problem instance once for offline replay / parameter sweeps. */
            std::string dump_reason;
            const auto &opt_stats = exp_traj_opt_->getLastOptStats();
            if (!temp_ret) {
                dump_reason = "exp_opt_failed";
            } else {
                if (opt_stats.iter_num >= cfg_.case_dump.slow_iter_num) {
                    dump_reason = "slow_convergence";
                }
                if (opt_stats.penalty_log.size() > 1 &&
                    opt_stats.penalty_log(1) >= cfg_.case_dump.pos_penna_warn) {
                    dump_reason += dump_reason.empty() ? "high_violation" : ",high_violation";
                }
                const double replan_t_so_far = ros_ptr_->getSimTime() - replan_process_start_WT;
                if (replan_t_so_far > cfg_.replan_forward_dt && cfg_.case_dump.dump_on_overtime) {
                    dump_reason += dump_reason.empty() ? "replan_overtime" : ",replan_overtime";
                }
                if (time_consuming_[EXP_TRAJ_OPT] * 1000.0 > cfg_.case_dump.slow_opt_ms) {
                    dump_reason += dump_reason.empty() ? "slow_opt" : ",slow_opt";
                }
            }
            if (last_exp_sfc_t_ * 1000.0 > cfg_.case_dump.slow_sfc_ms) {
                dump_reason += dump_reason.empty() ? "slow_sfc" : ",slow_sfc";
            }
            if (!forced_dump_reason_.empty()) {
                dump_reason += dump_reason.empty() ? forced_dump_reason_ : "," + forced_dump_reason_;
                forced_dump_reason_.clear();
            }
            if (!dump_reason.empty()) {
                ExpOptCaseData case_data;
                case_data.stage = "backend";
                case_data.reason = dump_reason;
                case_data.connected_goal = connected_goal;
                case_data.head_pvaj = pos_init_state;
                case_data.tail_pvaj = pos_fina_state;
                case_data.guide_path = guide_path;
                case_data.guide_t = guide_stamp;
                case_data.pass_wps = pass_wps;
                case_data.sfc = original_sfc;
                case_data.opt_success = temp_ret;
                case_data.lbfgs_ret = opt_stats.lbfgs_ret;
                case_data.iter_num = opt_stats.iter_num;
                case_data.final_cost = opt_stats.final_cost;
                case_data.opt_time = time_consuming_[EXP_TRAJ_OPT];
                case_data.frontend_time = time_consuming_[EPX_TRAJ_FRONTEND];
                case_data.sfc_time = last_exp_sfc_t_;
                case_data.penalty_log = opt_stats.penalty_log;
                queueCaseDump(case_data);
            }
        }
        if (!temp_ret) {
            SLOG_EVENT(slog::Level::warn, "exp_opt_failed", {
                    slog::F("guide_path_size", guide_path.size()),
                    slog::F("guide_path_len", super_planner::geometry_utils::computePathLength(guide_path)),
                    slog::F("sfc_count", sfc.size()),
                    slog::F("connected_goal", connected_goal),
                    slog::F("dist_to_goal", (robot_state_.p - gi_.goal_p).norm()),
                    slog::F("pos", fmt::format("{}", robot_state_.p.transpose())),
                    slog::F("goal", fmt::format("{}", gi_.goal_p.transpose())),
                    slog::F("init_pos", fmt::format("{}", pos_init_state.col(0).transpose())),
                    slog::F("final_pos", fmt::format("{}", pos_fina_state.col(0).transpose())),
                    slog::F("max_vel", eff_max_vel),
                    slog::F("max_acc", cfg_.exp_traj_cfg.max_acc),
            });
            ros_ptr_->warn(" -- [SUPER] OptimizationExpTrajInPolytopes for new path failed");
            return FAILED;
        }
        double replan_total_t = (ros_ptr_->getSimTime() - replan_process_start_WT);
        if (replan_total_t > cfg_.replan_forward_dt) {
            ros_ptr_->warn(" -- [SUPER] Replan over time({})!!!! Return FAILED", replan_total_t);
            return FAILED;
        }

        {
            TimeConsuming t_viz("tviz", false);
            ros_ptr_->vizExpTraj(out_traj);
            time_consuming_[VISUALIZATION] += t_viz.stop();
        }
        SLOG_EVENT(slog::Level::info, "exp_traj_result", {
                slog::F("duration", out_traj.getTotalDuration()),
                slog::F("sfc_count", sfc.size()),
                slog::F("connected_goal", connected_goal),
                slog::F("guide_path_len", super_planner::geometry_utils::computePathLength(guide_path)),
                slog::F("start", fmt::format("{}", out_traj.getPos(0.0).transpose())),
                slog::F("end", fmt::format("{}", out_traj.getPos(out_traj.getTotalDuration()).transpose())),
                slog::F("goal", fmt::format("{}", gi_.goal_p.transpose())),
        });

        double new_traj_WT = replan_process_start_WT;

        replan_process_start_TT = replan_process_start_WT - guide_pos_traj.start_WT;
        Trajectory temp_exp_traj;
        if (!last_exp_traj_info_.empty() &&
            !guide_pos_traj.getPartialTrajectoryByTime(replan_process_start_TT, replan_state_TT,
                                                       temp_exp_traj)) {
            ros_ptr_->error(" -- [SUPER] in [generateExpTraj]: getPartialTrajectoryByTime failed, force return");
            return FAILED;
        }
        out_exp_traj_info.setSFC(sfc);
        temp_exp_traj = temp_exp_traj + out_traj;
        temp_exp_traj.start_WT = new_traj_WT; //last_exp_traj_info.replan_start_WT ;

        if (!last_exp_traj_info.empty()) {
            StatePVAJ yaw_replan_state;
            if (!guide_yaw_traj.getState(replan_state_TT, yaw_replan_state)) {
                ros_ptr_->warn(" -- [SUPER] Invalid traj or eval t");
                return FAILED;
            }
            init_yaw = yaw_replan_state.row(0);
        }


        bool free_end{true};
        if (cfg_.goal_yaw_en && !isnan(gi_.goal_yaw) && connected_goal) {
            free_end = false;
            fina_yaw[0] = gi_.goal_yaw;
        }
        Trajectory new_traj, old_traj;

        if (cfg_.online_yaw_en) {
            /* Online yaw (stepOnlineYaw) commands the heading: skip the offline
             * yaw optimizer and store a simple direction-following yaw trajectory
             * so downstream readers (getYawState / getState / vizYawTraj) stay
             * valid. free_end=false means the goal yaw is constrained upstream. */
            new_traj = buildDirectionalYawTraj(out_traj, init_yaw(0),
                                               free_end ? NAN : gi_.goal_yaw);
        } else if (!yaw_traj_opt_->optimize(init_yaw, fina_yaw, out_traj, new_traj, 3, false, free_end)) {
            ros_ptr_->error(" -- [SUPER] in [generateExpTraj]: YawTrajOpt failed, force return");
            return FAILED;
        }
        if (!last_exp_traj_info.empty()) {
            if (!guide_yaw_traj.getPartialTrajectoryByTime(replan_process_start_TT, replan_state_TT,
                                                           old_traj)) {
                ros_ptr_->error(" -- [SUPER] in [generateExpTraj]: getPartialTrajectoryByTime failed, force return");
                return FAILED;
            }
        }

        const auto temp_yaw_traj = old_traj + new_traj;
        // check if part of the exp on last backup
        double on_backup_end_TT{-1}, on_backup_start_TT{-1};
        if (!last_exp_traj_info.empty() && replan_state_TT > cmd_traj_info_.getBackupTrajStartTT()) {
            on_backup_start_TT = cmd_traj_info_.getBackupTrajStartTT() - replan_process_start_TT;
            on_backup_end_TT = replan_state_TT - replan_process_start_TT;
        }
        out_exp_traj_info.setTrajectory(new_traj_WT, temp_exp_traj, temp_yaw_traj, on_backup_start_TT,
                                        on_backup_end_TT);

        latest_replan.setExpYawTraj(temp_yaw_traj);
        latest_replan.setExpTraj(temp_exp_traj);

        return SUCCESS;
    }

    /* Scope timer that always writes the backup frontend bucket on exit, so
     * early-return paths (NO_NEED/FINISH/FAILED) are also accounted for. */
    struct BackFrontendTimer {
        TimeConsuming t;
        double *bucket;
        explicit BackFrontendTimer(double *b) : t("t_back_frontend", false), bucket(b) {}
        ~BackFrontendTimer() { *bucket = t.stop(); }
    };

    RET_CODE SuperPlanner::generateBackupTrajectory(ExpTraj &ref_exp_traj, BackupTraj &back_traj_info) {
        drone_state_mutex_.lock();
        back_traj_info.setRobotPos(robot_state_.p);
        drone_state_mutex_.unlock();
        BackFrontendTimer back_frontend_timer{&time_consuming_[BACK_TRAJ_FRONTEND]};
        double total_dur = ref_exp_traj.getTotalDuration();
        double start_t = ros_ptr_->getSimTime() - ref_exp_traj.getStartWallTime();


        if (start_t > total_dur - 0.01) {
            if (cfg_.print_log) {
                ros_ptr_->info(" -- [SUPER] in [generateBackupTrajectory]: start_t > total_dur, return NO_NEED");
            }
            return NO_NEED;
        }

        Vec3f temp_point;
        double out_t;
        bool all_traj_visible{true};
        // 同时记录每一个点的刹车时间和刹车距离
        vector<double> min_stop_dis;
        vector<TimePosPair> eval_ps;
        Vec3f temp_vel;

        // 记录当前时刻到最远时刻的所有可视部分
        Vec3f last_pos = ref_exp_traj.getPos(start_t);
        for (out_t = start_t; out_t < total_dur; out_t += cfg_.sample_traj_dt) {
            temp_point = ref_exp_traj.getPos(out_t);
            if ((last_pos - temp_point).norm() < cfg_.resolution * 0.8) {
                continue;
            }
            last_pos = temp_point;
            temp_vel = ref_exp_traj.getVel(out_t);
            // Compute initial
            double v_norm = temp_vel.norm();
            min_stop_dis.push_back(v_norm * v_norm / 2.0 / cfg_.exp_traj_cfg.max_acc);
            eval_ps.push_back(std::pair<double, Vec3f>(out_t, temp_point));
            const double min_dis =
                    cfg_.sensing_horizon > 0 ? std::min(cfg_.sensing_horizon, cfg_.safe_corridor_line_max_length)
                                             : cfg_.safe_corridor_line_max_length;
            if (!map_ptr_->isLineFree(back_traj_info.getRobotPos(),
                                      temp_point,
                                      min_dis,
                                      cfg_.seed_line_neighbour)) {
                all_traj_visible = false;
                break;
            }
        }

        if (all_traj_visible) {
            back_traj_info.setEmpty();
            {
                double dur = ref_exp_traj.getTotalDuration();
                Vec3f seed_pt = ref_exp_traj.getPos(dur);
                Line line{back_traj_info.getRobotPos(), seed_pt};
                Polytope temp_poly;
                TimeConsuming t_back_sfc("t_back_sfc", false);
                const bool back_sfc_ok = cg_ptr_->GeneratePolytopeFromLine(line, temp_poly);
                last_back_sfc_t_ = t_back_sfc.stop();
                if (back_sfc_ok) {
                    back_traj_info.setSFC(temp_poly);
                    {
                        TimeConsuming t_viz("tviz", false);
                        ros_ptr_->vizBackupSfc(temp_poly);
                        time_consuming_[VISUALIZATION] += t_viz.stop();
                    }
                }
            }
            return FINISH;
        }
        Vec3f invisible_p = eval_ps.back().second;
        while (out_t > start_t) {
            out_t -= cfg_.sample_traj_dt;
            Vec3f out_p = ref_exp_traj.getPos(out_t);
            if ((out_p - invisible_p).norm() > cfg_.robot_r) {
                break;
            }
        }

        double seed_point_t = std::max(start_t, out_t);

        // TODO check this logic, comment on Dec. 13
        // if
        // 1) last exp traj has a backup traj
        // 2) last backup WT is larger than this term
        // 3) last exp is collision free
        // if (ref_exp_traj.back_traj_start_TT > 0 &&
        // seed_point_t < ref_exp_traj.back_traj_start_TT) {
        // return NO_NEED;
        // }


        Vec3f seed_point = ref_exp_traj.getPos(seed_point_t);

        Vec3f shifted_robot_p = shifted_sfc_start_pt_.norm()> 999?robot_state_.p:shifted_sfc_start_pt_;
        if (!map_ptr_->getNearestCellNot(GridType::OCCUPIED, shifted_robot_p, shifted_robot_p, 3.0)) {
            ros_ptr_->error(
                    " -- [SUPER] in [PlanFromRest] Local start point is deeply occupied, which should not happened.");
            latest_replan.setRetCode(SUPER_RET_CODE::SUPER_NO_START_POINT);
            return FAILED;
        }

        Line line{shifted_robot_p, seed_point};
        Polytope temp_poly;
        TimeConsuming t_back_sfc("t_back_sfc", false);
        const bool back_sfc_ok = cg_ptr_->GeneratePolytopeFromLine(line, temp_poly);
        last_back_sfc_t_ = t_back_sfc.stop();
        if (!back_sfc_ok) {
            ros_ptr_->warn(" -- [SUPER] GeneratePolytopeFromLine failed, force return");
            return FAILED;
        }
        Eigen::Vector3d inner;
        Eigen::Matrix3Xd vPoly;
        if (!super_planner::geometry_utils::findInterior(temp_poly.GetPlanes(), inner)) {
            ros_ptr_->warn(" -- [SUPER] Cannot generate feasible backup sfc, force return");
            vec_Vec3f seed{back_traj_info.getRobotPos(), seed_point};
            return FAILED;
        }

        if (cfg_.use_fov_cut) {
            if (!fov_checker_->cutPolyByFov(robot_state_.p, robot_state_.q, seed_point,
                                            temp_poly)) {
                ros_ptr_->warn(" -- [SUPER] cutPolyByFov failed, force return");
                return FAILED;
            }
        }
        // cut by sensing horizon
        if (cfg_.sensing_horizon > 0 &&
            !fov_checker_->cutPolyBySensingHorizon(robot_state_.p, seed_point, cfg_.sensing_horizon,
                                                   temp_poly)) {
            ros_ptr_->warn(" -- [SUPER] cutPolyBySensingHorizon failed, force return");
            vec_Vec3f seed{back_traj_info.getRobotPos(), seed_point};
            return FAILED;
        }

        back_traj_info.setSFC(temp_poly);

        {
            TimeConsuming t_viz("tviz", false);
            ros_ptr_->vizBackupSfc(temp_poly);
            time_consuming_[VISUALIZATION] += t_viz.stop();
        }

//        Vec3f out_p = temp_point;
//        double t_R = 0.0;
        double eval_t = eval_ps.back().first + cfg_.sample_traj_dt;
        last_pos = eval_ps.back().second;
        while (temp_poly.PointIsInside(eval_ps.back().second) && eval_t < total_dur) {
            Vec3f cur_pos = ref_exp_traj.getPos(eval_t);

            if ((cur_pos - last_pos).norm() < cfg_.resolution * 0.8) {
                eval_t += cfg_.sample_traj_dt;
                continue;
            }
            temp_vel = ref_exp_traj.getVel(out_t);
            double v_norm = temp_vel.norm();
            min_stop_dis.push_back(v_norm * v_norm / 2.0 / cfg_.exp_traj_cfg.max_acc);
            eval_ps.emplace_back(eval_t, cur_pos);
            last_pos = cur_pos;
            eval_t += cfg_.sample_traj_dt;
        }
        eval_ps.pop_back();
        seed_point = eval_ps.back().second;
        seed_point_t = eval_ps.back().first;

        //        bool use_new{true};
        //        if (use_new) {
        double t0 = ros_ptr_->getSimTime() -
                    ref_exp_traj.getStartWallTime() + 0.01;
        double te = seed_point_t;
        //            cout << "t0: " << t0 << endl;
        //            cout << "te: " << te << endl;
        //            cout << "exp_traj_dur: " << ref_exp_traj.optimized_exp_traj.getTotalDuration() << endl;
        double vel_e_n = ref_exp_traj.getVel(te).norm();
        double heu_ts = std::max((t0 + te) / 2, te - vel_e_n / cfg_.back_traj_cfg.max_acc);
        double heu_dur = te - heu_ts;
        Vec3f heu_p = seed_point;
        TimeConsuming t_back_opt("t_back_opt", false);
        double opt_ts = heu_ts;
        Trajectory temp_pos_traj;
        auto sfc0 = back_traj_info.getSFC();
        bool temp_ret = back_traj_opt_->optimize(ref_exp_traj.posTraj(),
                                                 t0,
                                                 te,
                                                 heu_ts,
                                                 heu_p,
                                                 heu_dur,
                                                 back_traj_info.getSFC(),
                                                 temp_pos_traj,
                                                 opt_ts);
        {
            double init_ts;
            VecDf init_times;
            vec_Vec3f init_ps;
            back_traj_opt_->getInitValue(init_ts, init_times, init_ps);
            latest_replan.setBackupCondition(init_ts, init_times, init_ps,
                                             t0, te,
                                             back_traj_info.getSFC());
            /* Legacy hot-restart whose outputs (traj, out_ts) are discarded; it
             * costs one extra L-BFGS run per replan and is kept only as a
             * debugging aid behind backup_reopt_en. */
            if (cfg_.backup_reopt_en) {
                Trajectory traj;
                double out_ts;
                back_traj_opt_->optimize(ref_exp_traj.posTraj(),
                                         t0,
                                         te,
                                         init_ts,
                                         sfc0,
                                         init_times,
                                         init_ps,
                                         traj,
                                         out_ts
                );
            }
        }
        time_consuming_[BACK_TRAJ_OPT] = t_back_opt.stop();

        if (pending_case_) {
            /* Attach the backup problem so the case can be replayed end to end. */
            pending_case_data_.backup.valid = true;
            pending_case_data_.backup.t0 = t0;
            pending_case_data_.backup.te = te;
            pending_case_data_.backup.heu_ts = heu_ts;
            pending_case_data_.backup.heu_dur = heu_dur;
            pending_case_data_.backup.heu_p = heu_p;
            pending_case_data_.backup.sfc = back_traj_info.getSFC();
            pending_case_data_.backup.opt_success = temp_ret;
            pending_case_data_.backup.opt_time = time_consuming_[BACK_TRAJ_OPT];
        }

        if (!temp_ret) {
            ros_ptr_->warn(" -- [SUPER] OptimizationBakTrajInPolytopes failed, force return");
            back_traj_info.setEmpty();
            return OPT_FAILED;
        } else {
            Vec4f yaw_init_vec = ref_exp_traj.getYawState(opt_ts).row(0);
            Vec4f yaw_goal{0, 0, 0, 0};
            bool free_end{true};
            if (cfg_.goal_yaw_en) {
                if (!isnan(gi_.goal_yaw)) {
                    free_end = false;
                    yaw_goal[0] = gi_.goal_yaw;
                }
            }
            Trajectory temp_yaw_traj;
            if (cfg_.online_yaw_en) {
                /* Online yaw: direction-following yaw trajectory aligned with the
                 * backup position trajectory, no offline optimization. */
                temp_yaw_traj = buildDirectionalYawTraj(temp_pos_traj, yaw_init_vec(0),
                                                        free_end ? NAN : gi_.goal_yaw);
            } else if (!yaw_traj_opt_->optimize(yaw_init_vec, yaw_goal, temp_pos_traj,
                                                temp_yaw_traj, 3, false, free_end)) {
                ros_ptr_->error(" -- [SUPER] in [generateBackupTrajectory] YawTrajOpt FAILD.");
                return OPT_FAILED;
            }


            if (opt_ts < t0) {
                ros_ptr_->error(" -- [SUPER] opt_ts {} < t0 {}", opt_ts, t0);
                return OPT_FAILED;
            }
            double new_ts_WT = ref_exp_traj.getStartWallTime() + opt_ts;
            const auto &committed_ts_WT = cmd_traj_info_.getBackupTrajStartTT();
            if (committed_ts_WT < cmd_traj_info_.getTotalDuration() && new_ts_WT < committed_ts_WT) {
                ros_ptr_->error(" -- [SUPER] new_ts_WT {} < committed_ts_WT {}", new_ts_WT, committed_ts_WT);
                return OPT_FAILED;
            }


            {
                TimeConsuming t_viz("tviz", false);
                ros_ptr_->vizBackupTraj(temp_pos_traj);
                time_consuming_[VISUALIZATION] += t_viz.stop();
            }

            back_traj_info.setTrajectory(new_ts_WT, opt_ts, temp_pos_traj, temp_yaw_traj);
            latest_replan.setBackupTraj(temp_pos_traj);
            latest_replan.setBackupYawTraj(temp_yaw_traj);
            return SUCCESS;
        }
        ros_ptr_->warn(" -- [SUPER] Cannot find backup traj start point.");
        return FAILED;
    }

    int SuperPlanner::getNearestFurtherGoalPoint(const vec_E<Vec3f> &goals, const Vec3f &start_pt) {
        if (goals.size() == 1) {
            return 0;
        }
        Vec3f a = start_pt, b;
        int min_id = 0;
        double min_dis = 1e10;
        for (long unsigned int i = 0; i < goals.size() - 1; i++) {
            b = goals[i];
            double dis = super_planner::geometry_utils::pointLineSegmentDistance(start_pt, a, b);
            if (dis < min_dis) {
                min_dis = dis;
                min_id = i;
            }
            a = b;
        }
        return min_id;
    }

    bool
    SuperPlanner::PathSearch(const Vec3f &start_pt, const Vec3f &goal,
                             const double &searching_horizon,
                             vec_Vec3f &path) {
        using namespace super_planner::path_search;
        if (searching_horizon <= 0.0) {
            ros_ptr_->error(" -- [SUPER] Goal waypoints empty or searching horizon negative, force return.");
            return false;
        }

        // 1) check and shift pts
        // 		For start point, must be collision free
        super_planner::rog_map::GridType start_type;
        start_type = map_ptr_->getGridType(start_pt);

        /// If the start_pt is obstacle in prob map, just shift it to the nearest free point.
        if (start_type == super_planner::rog_map::GridType::OCCUPIED ||
            start_type == super_planner::rog_map::GridType::OUT_OF_MAP) {
            ros_ptr_->warn(
                    " -- [SUPER] The start point in obstacle, this should not happen since the start point should be shift before pathsearch.");
            return false;
        }
        vec_E<Vec3f> start_point_escape_path;

        int flag_es = ON_PROB_MAP | (cfg_.frontend_in_known_free ? UNKNOWN_AS_OCCUPIED : UNKNOWN_AS_FREE);
        vec_Vec3f out_path;
        RET_CODE ret_es = astar_ptr_->escapePathSearch(start_pt, flag_es, out_path);
        if (ret_es != NO_NEED) {
            if (ret_es != REACH_HORIZON && ret_es != REACH_GOAL) {
                ros_ptr_->error(
                        " -- [SUPER] Escape path search failed with [{}], force return.",
                        RET_CODE_STR[ret_es].c_str());
                return false;
            } else {
                start_point_escape_path = out_path;
            }
        }

        Vec3f shifted_start_pt = start_pt;

        if (!start_point_escape_path.empty()) {
            shifted_start_pt = start_point_escape_path.back();
        }

        Vec3f temp_goal_point, temp_start_point;
        temp_start_point = shifted_start_pt;
        double temp_plannning_horizon = searching_horizon;
        //            int start_id = getNearestFurtherGoalPoint(goal_waypoints, start_pt);

        int flag = ON_ASTAR_MAP | (cfg_.frontend_in_known_free ? UNKNOWN_AS_OCCUPIED : UNKNOWN_AS_FREE) |
                   DONT_USE_INF_NEIGHBOR;

        RET_CODE ret_code = astar_ptr_->pointToPointPathSearch(temp_start_point, goal, flag, temp_plannning_horizon,
                                                               path);

        if(ret_code == INIT_ERROR){
            gi_.goal_valid = false;
            return false;
        }
        if (ret_code != REACH_HORIZON && ret_code != REACH_GOAL) {
            ros_ptr_->error(
                    " -- [SUPER] Path search failed with [{}], force return.\n", RET_CODE_STR[ret_code].c_str());
            return false;
        }
        if (!start_point_escape_path.empty()) {
            path.insert(path.begin(), start_point_escape_path.begin(),
                        start_point_escape_path.end());
        }

        if (path.empty()) {
            ros_ptr_->warn(
                    " -- [SUPER] Path search failed with empty segments, force return.");
            return false;
        }
        path.insert(path.begin(), start_pt);
        if (ret_code == REACH_GOAL) {
            path.push_back(goal);
        }
        SLOG_EVENT(slog::Level::debug, "astar_result", {
                slog::F("ret", RET_CODE_STR[ret_code]),
                slog::F("path_size", path.size()),
                slog::F("path_len", super_planner::geometry_utils::computePathLength(path)),
                slog::F("horizon", searching_horizon),
                slog::F("start", fmt::format("{}", start_pt.transpose())),
                slog::F("goal", fmt::format("{}", goal.transpose())),
        });
        return true;
    }


    double SuperPlanner::committedTrajLength() {
        cmd_traj_info_.lock();
        if (cmd_traj_info_.empty()) {
            cmd_traj_info_.unlock();
            return -1.0;
        }
        const auto &traj = cmd_traj_info_.posTraj();
        const double dur = traj.getTotalDuration();
        double len = 0.0;
        Vec3f prev = traj.getPos(0.0);
        for (double t = cfg_.sample_traj_dt; t < dur; t += cfg_.sample_traj_dt) {
            const Vec3f p = traj.getPos(t);
            len += (p - prev).norm();
            prev = p;
        }
        len += (traj.getPos(dur) - prev).norm();
        cmd_traj_info_.unlock();
        return len;
    }

    void SuperPlanner::getRobotState(super_planner::rog_map::RobotState &out) {
        robot_state_ = map_ptr_->getRobotState();
        out = robot_state_;
    }
}
