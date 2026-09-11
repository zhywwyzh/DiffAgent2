#pragma once

#include <corridor_gen/ellipsoid.h>

namespace corridor_gen {

class MVIE {
 public:
  MVIE() = default;
  ~MVIE() = default;

  static void chol3d(const Eigen::Matrix3d &A, Eigen::Matrix3d &L);

  static bool smoothedL1(const double &mu, const double &x, double &f, double &df);

  static double costMVIE(void *data, const double *x, double *g, const int n);

  static bool maxVolInsEllipsoid(const Eigen::MatrixX4d &hPoly, Ellipsoid &ellipsoid);
};

}  // namespace corridor_gen
