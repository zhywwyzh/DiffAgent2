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


#ifndef SUPER_FSM_CONFIG_HPP
#define SUPER_FSM_CONFIG_HPP


#include <super_core/config.hpp>
#include <vector>
#include <cstring>
#include <super_utils/yaml_loader.hpp>
namespace super_planner {
namespace fsm {
    using namespace super_planner::traj_opt;
    using namespace super_planner;

    class Config {
    public:
        enum YawMode{
            YAW_TO_VEL = 1,
            YAW_TO_GOAL = 2
        };

        bool timer_en{true};

        // Fsm Params
        bool click_goal_en{}, traj_start_trigger_en{}, visualization_en{};
        double replan_rate{}, resolution{};

        bool click_yaw_en{};
        string cmd_topic, click_goal_topic, traj_start_trigger_topic;
        double yaw_dot_max{};
        int yaw_mode{};
        double yaw_pre_tolerance_deg{5.0};
        double yaw_time_forward{1.0};
        bool pre_yaw_replan_en{true};
        double yaw_replan_threshold_deg{15.0};
        // Radius around an intermediate window waypoint that counts as consumption [m].
        double wp_reach_radius{0.3};
        /* Radius around the final waypoint (or a single goal) that counts as
         * arrival: trajectory-finish completion and plan-time already-there both
         * use this single threshold [m]. */
        double goal_reach_radius{0.3};
        /* Pass-by consumption: lateral distance from the active waypoint's travel
         * plane within which crossing the plane counts as consumption [m]. */
        double wp_passby_lateral{2.0};
        /* Goal-unreachable escalation: after this many trajectory executions that
         * finish away from the goal, or this much time without progress, the FSM
         * stops replanning and reports failure upstream instead of looping forever. */
        int goal_unreachable_max_unfinish{3};
        double goal_unreachable_timeout_s{15.0};

        /* Telemetry: stdout JSONL is the always-on agent interface; mcap is the
         * sim-only binary recording (scene snapshots on key-frames). */
        std::string telemetry_level{"info"};
        bool telemetry_stdout_en{true};
        bool telemetry_mcap_en{false};
        std::string telemetry_mcap_dir{"/workspace/.artifacts/mcap"};
        int telemetry_marker_decimation{15};

        Config() = default;

        Config(const std::string & cfg_path) {
            super_planner::yaml_loader::YamlLoader loader(cfg_path);
            vector<double> tem_gain;
            loader.LoadParam("fsm/timer_en", timer_en, false);
            loader.LoadParam("fsm/click_goal_en", click_goal_en, false);
            loader.LoadParam("fsm/traj_start_trigger_en", traj_start_trigger_en, false);
            loader.LoadParam("fsm/click_yaw_en", click_yaw_en, false);
            loader.LoadParam("fsm/replan_rate", replan_rate, 10.0);
            loader.LoadParam("fsm/cmd_topic", cmd_topic, string("/planning/pos_cmd"));
            loader.LoadParam("fsm/click_goal_topic", click_goal_topic, string("/planning/click_goal_topic"));
            loader.LoadParam("fsm/traj_start_trigger_topic", traj_start_trigger_topic, string("/traj_start_trigger"));
            loader.LoadParam("fsm/wp_reach_radius", wp_reach_radius, 0.3);
            loader.LoadParam("fsm/goal_reach_radius", goal_reach_radius, 0.3);
            loader.LoadParam("fsm/wp_passby_lateral", wp_passby_lateral, 2.0);
            loader.LoadParam("fsm/goal_unreachable_max_unfinish", goal_unreachable_max_unfinish, 3);
            loader.LoadParam("fsm/goal_unreachable_timeout_s", goal_unreachable_timeout_s, 15.0);

            loader.LoadParam("telemetry/level", telemetry_level, string("info"));
            loader.LoadParam("telemetry/stdout_en", telemetry_stdout_en, true);
            loader.LoadParam("telemetry/mcap_en", telemetry_mcap_en, false);
            loader.LoadParam("telemetry/mcap_dir", telemetry_mcap_dir, string("/workspace/.artifacts/mcap"));
            loader.LoadParam("telemetry/marker_decimation", telemetry_marker_decimation, 15);


            loader.LoadParam("super_planner/yaw_dot_max", yaw_dot_max, 1.0, true);
            loader.LoadParam("super_planner/yaw_mode", yaw_mode, 1);
            loader.LoadParam("super_planner/yaw_pre_tolerance_deg", yaw_pre_tolerance_deg, 5.0);
            loader.LoadParam("super_planner/yaw_time_forward", yaw_time_forward, 1.0);
            loader.LoadParam("super_planner/pre_yaw_replan_en", pre_yaw_replan_en, true);
            loader.LoadParam("super_planner/yaw_replan_threshold_deg", yaw_replan_threshold_deg, 15.0);
            loader.LoadParam("super_planner/visualization_en", visualization_en, false, true);
            loader.LoadParam("rog_map/resolution", resolution, 0.1, true);

        }
    };
}
} // namespace super_planner

#endif //SUPER_FSM_CONFIG_H
