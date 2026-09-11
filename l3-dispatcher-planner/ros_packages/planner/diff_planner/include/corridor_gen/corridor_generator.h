#pragma once

#include <memory>
#include <vector>

#include <plan_env/grid_map.h>
#include <corridor_gen/types.hpp>
#include <corridor_gen/ciri.h>
#include <corridor_gen/polytope.h>

namespace corridor_gen {

class CorridorGenerator {
  GridMap::Ptr grid_map_;
  bool use_unknown_;
  double bound_dis_;
  double seed_line_max_length_;
  double min_overlap_threshold_;
  double robot_r_;
  int iris_iter_num_;
  std::vector<Eigen::Vector3i> line_seed_neighbor_list_;
  CIRI::Ptr ciri_;
  PointCloud latest_pc_;

 public:
  CorridorGenerator(const GridMap::Ptr &map_ptr, const double bound_dis,
                    const double seed_line_max_dis, const double min_overlap_threshold,
                    const double robot_r, const int iris_iter_num, bool use_unknown);

  typedef std::shared_ptr<CorridorGenerator> Ptr;

  void SetLineNeighborList(const std::vector<Eigen::Vector3i> &line_seed_neighbor_list);

  bool SearchPolytopeOnPath(const std::vector<Eigen::Vector3d> &path, PolytopeVec &sfcs,
                            Eigen::Vector3d &shifted_start_pt, const bool use_bigger_inflation = false);

  void getSeedBBox(const Eigen::Vector3d &p1, const Eigen::Vector3d &p2,
                   Eigen::Vector3d &box_min, Eigen::Vector3d &box_max);

  bool GeneratePolytopeFromPoint(const Eigen::Vector3d &pt, Polytope &polytope);

  bool GenerateEmptyPolytope(const Eigen::Vector3d &pt, const double dis, Polytope &polytope);

  bool GeneratePolytopeFromLine(const Line &line, Polytope &polytope);

  const PointCloud &getLatestCloud() const { return latest_pc_; }

 private:
  void boundBoxByLocalMap(Eigen::Vector3d &box_min, Eigen::Vector3d &box_max);

  void boxSearchCorridorObstacles(const Eigen::Vector3d &box_min, const Eigen::Vector3d &box_max,
                                  PointCloud &points, std::vector<uint8_t> &point_is_unknown);

  bool isLineFreeForCorridor(const Eigen::Vector3d &start_pt, const Eigen::Vector3d &end_pt,
                             const double max_dis,
                             const std::vector<Eigen::Vector3i> &neighbor_list);
};

}  // namespace corridor_gen
