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

#include "ros_interface/ros1/fsm_ros1.hpp"

/*
 * Test code:
 *      roslaunch simulator test_env.launch
 * */
#define BACKWARD_HAS_DW 1

#include "super_utils/backward.hpp"

namespace backward {
    backward::SignalHandling sh;
}


using namespace super_planner::fsm;
using namespace std;
FsmRos1::Ptr fsm_ptr;

#include <ros/console.h>
#include <ros/ros.h>
#include <slog/logger.hpp>
#include <slog_ros/rosout_sink.hpp>

int main(int argc, char **argv) {
    ros::init(argc, argv, "fsm_node");
    ros::NodeHandle nh("~");

    bool telemetry_rosout_en = true;
    nh.param<bool>("telemetry/rosout_en", telemetry_rosout_en, true);
    slog_ros::install_rosout_sink(nh, telemetry_rosout_en);

    pcl::console::setVerbosityLevel(pcl::console::L_ALWAYS);
    SLOG_INFO(" -- [Fsm-Test] Begin.");

#define CONFIG_FILE_DIR(name) (string(string(ROOT_DIR) + "config/"+name))
    std::string dft_cfg_path = CONFIG_FILE_DIR("click.yaml");
    std::string cfg_path, cfg_name;
    if (nh.param("config_path", cfg_path, dft_cfg_path)) {
        SLOG_INFO(" -- [Fsm-Test] Load config from: {}", cfg_path);
    } else if(nh.param("config_name", cfg_name, dft_cfg_path)){
        cfg_path = CONFIG_FILE_DIR(cfg_name);
        SLOG_INFO(" -- [Fsm-Test] Load config by file name: {}", cfg_name);
    }

    fsm_ptr = make_shared<FsmRos1>();

    /* Emit the run boundary marker: the audit pipeline slices every later event
     * into this run until the next run_started, keyed by the boot timestamp. */
    const int64_t boot_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
    SLOG_EVENT(slog::Level::info, "run_started", {
            slog::F("run_id", boot_ns),
            slog::F("git_version", std::string(GIT_VERSION)),
            slog::F("config_path", cfg_path),
            slog::F("cfg_name", cfg_name)});

    fsm_ptr->init(nh, cfg_path);

    /* Publisher and subcriber */
    ros::AsyncSpinner spinner(0);
    spinner.start();
    ros::Duration(1.0).sleep();
    ros::waitForShutdown();
    return 0;
}

