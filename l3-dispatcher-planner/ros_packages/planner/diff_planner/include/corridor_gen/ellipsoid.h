#pragma once

#include <corridor_gen/types.hpp>

namespace corridor_gen {

class Ellipsoid {
  bool undefined_{true};
  Eigen::Matrix3d C_{}, C_inv_{};
  Eigen::Matrix3d R_{};
  Eigen::Vector3d r_{}, d_{};

 public:
  Ellipsoid() = default;
  Ellipsoid(const Eigen::Matrix3d &C, const Eigen::Vector3d &d);
  Ellipsoid(const Eigen::Matrix3d &R, const Eigen::Vector3d &r, const Eigen::Vector3d &d);

  bool empty() const;
  double pointDistaceToEllipsoid(const Eigen::Vector3d &pt,
                                 Eigen::Vector3d &closest_pt_on_ellip) const;
  int nearestPointId(const Eigen::Matrix3Xd &pc) const;
  Eigen::Vector3d nearestPoint(const Eigen::Matrix3Xd &pc) const;
  double nearestPointDis(const Eigen::Matrix3Xd &pc, int &np_id) const;
  Eigen::Matrix3d C() const;
  Eigen::Vector3d d() const;
  Eigen::Matrix3d R() const;
  Eigen::Vector3d r() const;
  Eigen::Vector3d toEllipsoidFrame(const Eigen::Vector3d &pt_w) const;
  Eigen::Matrix3Xd toEllipsoidFrame(const Eigen::Matrix3Xd &pc_w) const;
  Eigen::Vector3d toWorldFrame(const Eigen::Vector3d &pt_e) const;
  Eigen::Vector4d toEllipsoidFrame(const Eigen::Vector4d &plane_w) const;
  Eigen::Vector4d toWorldFrame(const Eigen::Vector4d &plane_e) const;
  Eigen::MatrixX4d toEllipsoidFrame(const Eigen::MatrixX4d &planes_w) const;
  Eigen::MatrixX4d toWorldFrame(const Eigen::MatrixX4d &planes_e) const;
  double dist(const Eigen::Vector3d &pt_w) const;
  Eigen::VectorXd dist(const Eigen::Matrix3Xd &pc_w) const;
  bool noPointsInside(PointCloud &pc, const Eigen::Matrix3d &R, const Eigen::Vector3d &r,
                      const Eigen::Vector3d &p) const;
  bool pointsInside(const Eigen::Matrix3Xd &pc, Eigen::Matrix3Xd &out, int &min_pt_id) const;
  bool inside(const Eigen::Vector3d &pt) const;
};

}  // namespace corridor_gen
