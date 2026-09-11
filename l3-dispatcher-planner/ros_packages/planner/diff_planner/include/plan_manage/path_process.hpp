#ifndef _DIFF_PATH_PROCESS_H_
#define _DIFF_PATH_PROCESS_H_

#include <Eigen/Eigen>
#include <algorithm>
#include <iostream>
#include <ros/ros.h>
#include <vector>
#include <cmath>
#include <limits>

namespace diff_planner
{
    inline double computePathLength(const std::vector<Eigen::Vector3d>& path) {
        if (path.size() < 2) {
            return 0.0;
        }
        double len = 0.0;
        for (size_t i = 0; i < path.size() - 1; i++) {
            len += (path[i] - path[i + 1]).norm();
        }
        return len;
    }

    inline void simplePMTimeAllocator_v2(const double &a_max, const double &v_max,
                                        const double &v0, const double &total_dis,
                                        const double &cur_dis, double &t, double &vel) {
        const double a = std::max(a_max, 1e-9);
        const double s = std::max(0.0, std::min(cur_dis, total_dis));
        auto velFromAccelDist = [&](double v_init, double ds) {
            return std::sqrt(std::max(0.0, v_init * v_init + 2.0 * a * ds));
        };
        auto timeAccel = [&](double v_init, double v_fin) {
            return std::max(0.0, (v_fin - v_init) / a);
        };
        auto timeDecel = [&](double v_init, double v_fin) {
            return std::max(0.0, (v_init - v_fin) / a);
        };
        // 从 v0 加速到 v_max 所需路程；从 v_max 减速回 v0 所需路程
        const double s_up   = (v_max * v_max - v0 * v0) / (2.0 * a);
        const double s_down = (v_max * v_max - v0 * v0) / (2.0 * a);
        // ---------- 剖面 A：总长连 v0 都加速不满（原版 Case 1）----------
        const double s_reach_v0_from_rest = (v0 * v0) / (2.0 * a);
        if (total_dis <= s_reach_v0_from_rest) {
            vel = velFromAccelDist(0.0, s);
            t   = vel / a;
            return;
        }
        // ---------- 剖面 B：三角剖面，峰值速度 v_peak < v_max（原版 Case 2）----------
        const double s_trap_min = s_up + s_down;
        if (total_dis <= s_trap_min) {
            // 对称加减速回到 v0：2 * (v_peak^2 - v0^2)/(2a) = total_dis
            const double v_peak = std::sqrt(v0 * v0 + a * total_dis);
            const double s_to_peak = (v_peak * v_peak - v0 * v0) / (2.0 * a);
            if (s <= s_to_peak) {
                vel = velFromAccelDist(v0, s);
                t   = timeAccel(v0, vel);
            } else {
                const double s_in_dec = s - s_to_peak;
                vel = std::sqrt(std::max(0.0, v_peak * v_peak - 2.0 * a * s_in_dec));
                t   = timeAccel(v0, v_peak) + timeDecel(v_peak, vel);
            }
            return;
        }
        // ---------- 剖面 C：梯形 v0 -> v_max -> 匀速 -> v_max -> v0（原版 Case 3）----------
        const double s_cruise = total_dis - s_trap_min;
        const double t_up     = timeAccel(v0, v_max);
        const double t_cruise = s_cruise / std::max(v_max, 1e-9);
        const double t_down   = timeDecel(v_max, v0);
        if (s <= s_up) {
            // 加速段
            vel = velFromAccelDist(v0, s);
            t   = timeAccel(v0, vel);
            return;
        }
        if (s <= s_up + s_cruise) {
            // 匀速段
            const double ds_cruise = s - s_up;
            vel = v_max;
            t   = t_up + ds_cruise / v_max;
            return;
        }
        // 减速段（从末端往回推）
        const double s_from_end = total_dis - s;
        vel = velFromAccelDist(v0, s_from_end);  // 对称：距终点 s_from_end 处速度
        t   = t_up + t_cruise + timeDecel(v_max, vel);
    }

}

#endif