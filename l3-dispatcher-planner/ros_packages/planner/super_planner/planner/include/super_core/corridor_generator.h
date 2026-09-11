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

#include "memory"

#include <super_core/config.hpp>
#include <super_core/ciri.h>

#include <data_structure/base/polytope.h>
#include <data_structure/base/trajectory.h>

#include <rog_map_ros/rog_map_ros1.hpp>
#include <super_utils/fmt_eigen.hpp>

#include <ros_interface/ros_interface.hpp>



namespace super_planner {
#define DEBUG_FILE_DIR(name) (string(string(ROOT_DIR) + "log/"+name))
    using namespace super_planner::geometry_utils;
    using super_planner::super_utils::Vec3i;
    using super_planner::super_utils::vec_E;
    using super_planner::super_utils::Line;
    using super_planner::super_utils::OCCUPIED;

    class CorridorGenerator {
    private:
        super_planner::ros_interface::RosInterface::Ptr ros_ptr_;
        double bound_dis_;
        double seed_line_max_length_;
        double min_overlap_threshold_;
        double robot_r_;
        int box_search_skip_num_;
        int iris_iter_num_;
        double virtual_groud_height_ = 0.0;
        double virtual_ceil_height_ = 0.0;
        super_planner::rog_map::ROGMap::Ptr map_ptr_;
        vec_E<Vec3i> line_seed_neighbor_list;
        CIRI::Ptr ciri_;
        std::ofstream failed_traj_log;

        vec_Vec3f latest_pc;

        double ciri_t{0};
        int ciri_cnt{0};
    public:
        vec_Vec3f getLatestCloud() {
            vec_Vec3f out = latest_pc;
            latest_pc.clear();
            return out;
        }

        /* Non-destructive read of the point cloud used by the latest SFC search,
         * for offline case dumping (getLatestCloud clears the buffer). */
        vec_Vec3f peekLatestCloud() const {
            return latest_pc;
        }

        CorridorGenerator(const super_planner::ros_interface::RosInterface::Ptr &ros_ptr,
                          const super_planner::rog_map::ROGMap::Ptr & map_ptr,
                          const double bound_dis,
                          const double seed_line_max_dis,
                          const double min_overlap_threshold,
                          const double virtual_groud_height,
                          const double virtual_ceil_height,
                          const double robot_r,
                          const int box_search_skip_num,
                          const int iris_iter_num);

        ~CorridorGenerator() = default;

        void SetLineNeighborList(const vec_E<Vec3i> &line_seed_neighbor_list);

        typedef std::shared_ptr<CorridorGenerator> Ptr;

        bool SearchPolytopeOnPath(const vec_Vec3f &path, PolytopeVec &sfcs,
                                  Vec3f & shifted_start_pt,
                                  bool cut_first_poly = false);

        void getSeedBBox(const Vec3f &p1, const Vec3f &p2,
                         Vec3f &box_min, Vec3f &box_max);

        bool GeneratePolytopeFromPoint(const Vec3f &pt, Polytope &polytope);

        bool GenerateEmptyPolytope(const super_planner::super_utils::Vec3f &pt,
                                   const double & dis,
                                   Polytope & polytope);

        bool GeneratePolytopeFromLine(Line &line, Polytope &polytope);

        /**
         * Max occupancy probability within a flattened ellipsoid around center:
         * horizontal radius radius_xy, vertical half-extent radius_z. The flat
         * z band excludes the floor/ceiling that a full sphere of radius_xy
         * would always intersect at cruise altitude.
         *
         * @param[in] center     Query center in world frame [m]
         * @param[in] radius_xy  Horizontal search radius [m]
         * @param[in] radius_z   Vertical half-extent [m]
         * @return Max probability in [0, 1]; 0 = all free, 1 = obstacle-proximal
         */
        double computeRiskScore(const Vec3f &center, double radius_xy, double radius_z) const;

        double getCiriComputationTime() {
            if (ciri_cnt == 0) {
                return -1;
            }
            double aver_T = ciri_t / ciri_cnt;
            ciri_t = 0;
            ciri_cnt = 0;
            return aver_T;
        }


        void setIterNum(int iter){
            iris_iter_num_ = iter;
        }

    };
}
