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


#ifndef SUPER_PLANNER_CONFIG_HPP
#define SUPER_PLANNER_CONFIG_HPP

#include <rog_map/rog_map_core/config.hpp>
#include <traj_opt/config.hpp>
#include <super_utils/yaml_loader.hpp>

namespace super_planner {
    using namespace super_planner::traj_opt;
    using std::cout;
    using std::endl;

    /* Thresholds for dumping hard optimization problem instances (corner cases)
     * to disk for offline replay and parameter sweeps. */
    struct CaseDumpConfig {
        bool enable{false};
        std::string output_dir{"/tmp/opt_cases"};
        bool dump_on_overtime{true};
        // Dump even on success when L-BFGS cost-functional calls reach this count.
        int slow_iter_num{2000};
        // Dump even on success when the corridor penalty exceeds this (failure is 0.2).
        double pos_penna_warn{0.1};
        // Dump the next replan after this many consecutive replan failures.
        int consec_failures{3};
        // Minimum wall-time between two dumps (flood protection) [s].
        double min_interval_s{1.0};
        // Hard cap on dumped cases per process run (0 = unlimited).
        int max_cases{200};
        // Dump on success when the exp optimizer wall time exceeds this [ms].
        double slow_opt_ms{15.0};
        // Dump when the exp SFC construction wall time exceeds this [ms].
        double slow_sfc_ms{10.0};
    };

    class Config {
    public:
        CaseDumpConfig case_dump;

        enum YawMode{
            YAW_TO_VEL = 1,
            YAW_TO_GOAL = 2
        };

        super_planner::traj_opt::Config exp_traj_cfg, back_traj_cfg;

        // Bool Params
        bool visualization_en{true};
        bool backup_traj_en;
        /* Legacy hot-restart of the backup optimizer with discarded outputs;
         * costs one extra L-BFGS run per replan, keep off unless debugging. */
        bool backup_reopt_en{false};
        bool use_fov_cut, print_log;
        bool goal_vel_en,goal_yaw_en;
        bool visual_process;
        bool frontend_in_known_free;

        double resolution;
        double planning_horizon;
        /* Adaptive planning horizon: narrow gaps shrink toward
         * planning_horizon_min, open space grows toward planning_horizon_max. */
        double planning_horizon_min;
        double planning_horizon_max;
        bool   adaptive_horizon_en;
        /* Low-pass weight on the previous horizon [0,1); higher = smoother. */
        double adaptive_horizon_smooth;
        /* Reactive retry: on frontend failure, shrink the horizon by
         * horizon_shrink_factor and retry, up to shrink_max_attempts. */
        int    horizon_shrink_max_attempts;
        double horizon_shrink_factor;
        /* Risk-based velocity/horizon scaling: per-corridor max occupancy
         * probability (sphere neighborhood of robot_r around each seed-line
         * center) is aggregated to a single risk in [0,1]; risk at/below
         * risk_th_low maps to risk_vel_max / planning_horizon_max, risk
         * at/above risk_th_high maps to risk_vel_min / planning_horizon_min,
         * linear in between. */
        bool   risk_en;
        double risk_vel_min;
        double risk_vel_max;
        /* Risk thresholds for the velocity/horizon ramp [-]: observed-free
         * space reads ~0.12 (p_min clamp), unobserved cells read 0.5,
         * obstacle contact reads ~0.98 (p_max clamp). */
        double risk_th_low;
        double risk_th_high;
        /* Low-pass weight on the previous velocity bound [0,1); higher = smoother. */
        double risk_vel_smooth;
        /* Max allowed drop of the velocity bound per replan cycle [m/s]:
         * keeps the optimizer init state (current flight speed) inside the
         * bound while braking into narrow space. */
        double risk_vel_max_drop;
        /* Upper bound of the risk sampling radius [m]: the committed-traj
         * length grows unbounded in open space, and the ellipsoid scan cost
         * scales with its cube; cap it so a full no-early-exit scan stays
         * inside the replan budget. */
        double risk_radius_max;
        double receding_dis;
        double safe_corridor_line_max_length;
        // for fov cut
        double sensing_horizon;

        // Planning Params
        int obs_skip_num;
        double corridor_bound_dis, corridor_line_max_length;
        double replan_forward_dt;
        double sample_traj_dt;
        double robot_r;
        int iris_iter_num;

        double yaw_dot_max;
        // Yaw mode: 1 heading to velocity, 2 heading to goal
        int yaw_mode = YAW_TO_VEL;
        bool online_yaw_en{true};
        double yaw_time_forward{1.0};
        double yaw_acc_max{3.0};

        super_planner::rog_map::vec_E<super_planner::rog_map::Vec3i> seed_line_neighbour;


        Config() = default;
        Config(const std::string & cfg_path) {
            super_planner::yaml_loader::YamlLoader loader(cfg_path);
            exp_traj_cfg = super_planner::traj_opt::Config(cfg_path, "exp_traj");
            back_traj_cfg = super_planner::traj_opt::Config(cfg_path, "backup_traj");
            loader.LoadParam("debug_log_en", print_log, false);
            loader.LoadParam("super_planner/visualization_en", visualization_en, false);
            loader.LoadParam("super_planner/backup_traj_en", backup_traj_en, false);
            loader.LoadParam("super_planner/backup_reopt_en", backup_reopt_en, false);
            loader.LoadParam("super_planner/goal_vel_en", goal_vel_en, false);
            loader.LoadParam("super_planner/goal_yaw_en", goal_yaw_en, false);
            loader.LoadParam("super_planner/visual_process", visual_process, false);
            loader.LoadParam("super_planner/use_fov_cut", use_fov_cut, false);
            loader.LoadParam("super_planner/frontend_in_known_free", frontend_in_known_free, false);
            loader.LoadParam("super_planner/safe_corridor_line_max_length", safe_corridor_line_max_length, 3.0);
            loader.LoadParam("super_planner/sensing_horizon", sensing_horizon, 3.0);
            loader.LoadParam("super_planner/obs_skip_num", obs_skip_num, 1);
            loader.LoadParam("super_planner/replan_forward_dt", replan_forward_dt, 0.3);
            loader.LoadParam("super_planner/corridor_bound_dis", corridor_bound_dis, 3.0);
            loader.LoadParam("super_planner/corridor_line_max_length", corridor_line_max_length, 3.0);
            loader.LoadParam("super_planner/planning_horizon", planning_horizon, 10.0);
            loader.LoadParam("super_planner/planning_horizon_min", planning_horizon_min, 4.5);
            loader.LoadParam("super_planner/planning_horizon_max", planning_horizon_max, planning_horizon);
            loader.LoadParam("super_planner/adaptive_horizon/enable", adaptive_horizon_en, true);
            loader.LoadParam("super_planner/adaptive_horizon/smooth", adaptive_horizon_smooth, 0.7);
            loader.LoadParam("super_planner/adaptive_horizon/shrink_max_attempts", horizon_shrink_max_attempts, 3);
            loader.LoadParam("super_planner/adaptive_horizon/shrink_factor", horizon_shrink_factor, 0.6);
            loader.LoadParam("super_planner/risk/enable", risk_en, true);
            loader.LoadParam("super_planner/risk/vel_min", risk_vel_min, 0.5);
            loader.LoadParam("super_planner/risk/vel_max", risk_vel_max, 2.5);
            loader.LoadParam("super_planner/risk/th_low", risk_th_low, 0.2);
            loader.LoadParam("super_planner/risk/th_high", risk_th_high, 0.6);
            loader.LoadParam("super_planner/risk/vel_smooth", risk_vel_smooth, 0.7);
            loader.LoadParam("super_planner/risk/vel_max_drop", risk_vel_max_drop, 0.5);
            loader.LoadParam("super_planner/risk/radius_max", risk_radius_max, 2.5);
            /* risk_vel_max is the single velocity-ceiling source: the risk
             * system re-bounds the optimizers every replan, so the traj_opt
             * max_vel only seeds the pre-first-replan window and derived
             * constants (sample_traj_dt below). */
            exp_traj_cfg.max_vel = risk_vel_max;
            back_traj_cfg.max_vel = risk_vel_max;
            loader.LoadParam("super_planner/receding_dis", receding_dis, 5.0);
            loader.LoadParam("super_planner/robot_r", robot_r, 0.3);
            loader.LoadParam("super_planner/iris_iter_num", iris_iter_num, 1);
            loader.LoadParam("super_planner/yaw_mode", yaw_mode, 1);
            loader.LoadParam("super_planner/yaw_dot_max", yaw_dot_max, 3.14);
            loader.LoadParam("super_planner/online_yaw_en", online_yaw_en, true);
            loader.LoadParam("super_planner/yaw_time_forward", yaw_time_forward, 1.0);
            loader.LoadParam("super_planner/yaw_acc_max", yaw_acc_max, 3.0);

            loader.LoadParam("case_dump/enable", case_dump.enable, false);
            loader.LoadParam("case_dump/output_dir", case_dump.output_dir, std::string("/tmp/opt_cases"));
            loader.LoadParam("case_dump/dump_on_overtime", case_dump.dump_on_overtime, true);
            loader.LoadParam("case_dump/slow_iter_num", case_dump.slow_iter_num, 2000);
            loader.LoadParam("case_dump/pos_penna_warn", case_dump.pos_penna_warn, 0.1);
            loader.LoadParam("case_dump/consec_failures", case_dump.consec_failures, 3);
            loader.LoadParam("case_dump/min_interval_s", case_dump.min_interval_s, 1.0);
            loader.LoadParam("case_dump/max_cases", case_dump.max_cases, 200);
            loader.LoadParam("case_dump/slow_opt_ms", case_dump.slow_opt_ms, 15.0);
            loader.LoadParam("case_dump/slow_sfc_ms", case_dump.slow_sfc_ms, 10.0);

            loader.LoadParam("rog_map/resolution", resolution, 0.01, true);

            sample_traj_dt = resolution / exp_traj_cfg.max_vel;

            int step = ceil(robot_r / resolution);
            for (int x = -step; x <= step; x++) {
                for (int y = -step; y <= step; y++) {
                    for (int z = -step; z <= step; z++) {
                        if (x * x + y * y + z * z <= step * step) {
                            seed_line_neighbour.push_back({x, y, z});
                        }
                    }
                }
            }
            std::sort(seed_line_neighbour.begin(), seed_line_neighbour.end(),
                      [](const auto& a, const auto& b) {
                          return a[0] * a[0] + a[1] * a[1] + a[2] * a[2] < b[0] * b[0] + b[1] * b[1] + b[2] * b[2];
                      });
        }


    };
}

#endif
