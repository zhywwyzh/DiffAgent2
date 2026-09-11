#pragma once

#include <Eigen/Eigen>
#include <utility>
#include <vector>

namespace corridor_gen {

constexpr double kEpsilon = 1e-10;

enum RetCode {
  FAILED = 0,
  NO_NEED = 1,
  SUCCESS = 2,
  FINISH = 3,
  NEW_TRAJ = 4,
  EMER = 5,
  OPT_FAILED = 6,
  INIT_ERROR = 7
};

using Line = std::pair<Eigen::Vector3d, Eigen::Vector3d>;
using PlaneMat = Eigen::Matrix<double, Eigen::Dynamic, 4>;
using PointCloud = std::vector<Eigen::Vector3d, Eigen::aligned_allocator<Eigen::Vector3d>>;

}  // namespace corridor_gen
