#pragma once

#include <memory>
#include <vector>

#include <corridor_gen/types.hpp>
#include <corridor_gen/polytope.h>
#include <corridor_gen/ellipsoid.h>
#include <corridor_gen/geometry_utils.h>
#include <corridor_gen/mvie.h>

namespace corridor_gen {

class CIRI {
  double robot_r_{0};
  int iter_num_{1};
  Ellipsoid sphere_template_;
  Polytope optimized_polytope_;

  void findEllipsoid(const Eigen::Matrix3Xd &pc, const Eigen::Vector3d &a,
                     const Eigen::Vector3d &b, Ellipsoid &out_ell);

  static void findTangentPlaneOfSphere(const Eigen::Vector3d &center, const double &r,
                                       const Eigen::Vector3d &pass_point,
                                       const Eigen::Vector3d &seed_p,
                                       Eigen::Vector4d &outter_plane);

  static double distancePointToSegment(const Eigen::Vector3d &P, const Eigen::Vector3d &A,
                                       const Eigen::Vector3d &B) {
    const Eigen::Vector3d AB = B - A;
    const Eigen::Vector3d AP = P - A;
    const double ab_ab = AB.dot(AB);
    /* Degenerate point seed (A == B): the segment is a single point. */
    if (ab_ab < 1e-12) return AP.norm();
    const double ap_ab = AP.dot(AB);
    const double t = ap_ab / ab_ab;
    if (t < 0.0) return (P - A).norm();
    if (t > 1.0) return (P - B).norm();
    return (P - (A + t * AB)).norm();
  }

 public:
  CIRI() = default;

  typedef std::shared_ptr<CIRI> Ptr;

  void setupParams(double robot_r, int iter_num);

  RetCode comvexDecomposition(const Eigen::MatrixX4d &bd, const Eigen::Matrix3Xd &pc,
                              const Eigen::Vector3d &a, const Eigen::Vector3d &b,
                              const std::vector<uint8_t> &point_is_unknown = {});

  void getPolytope(Polytope &optimized_poly);
};

}  // namespace corridor_gen
