#include <corridor_gen/ellipsoid.h>
#include <corridor_gen/geometry_utils.h>

#include <limits>
#include <vector>

namespace corridor_gen {

bool Ellipsoid::empty() const { return undefined_; }

Ellipsoid::Ellipsoid(const Eigen::Matrix3d &C, const Eigen::Vector3d &d) : C_(C), d_(d) {
  undefined_ = false;
  C_inv_ = C_.inverse();

  Eigen::JacobiSVD<Eigen::Matrix3d, Eigen::FullPivHouseholderQRPreconditioner> svd(C_, Eigen::ComputeFullU);
  const Eigen::Matrix3d U = svd.matrixU();
  const Eigen::Vector3d S = svd.singularValues();
  if (U.determinant() < 0.0) {
    R_.col(0) = U.col(1);
    R_.col(1) = U.col(0);
    R_.col(2) = U.col(2);
    r_(0) = S(1);
    r_(1) = S(0);
    r_(2) = S(2);
  } else {
    R_ = U;
    r_ = S;
  }
}

Ellipsoid::Ellipsoid(const Eigen::Matrix3d &R, const Eigen::Vector3d &r, const Eigen::Vector3d &d)
    : R_(R), r_(r), d_(d) {
  undefined_ = false;
  C_ = R_ * r_.asDiagonal() * R_.transpose();
  C_inv_ = C_.inverse();
}

double Ellipsoid::pointDistaceToEllipsoid(const Eigen::Vector3d &pt,
                                          Eigen::Vector3d &closest_pt_on_ellip) const {
  Eigen::Vector3d pt_ellip_frame = R_.transpose() * (pt - d_);
  double dist = DistancePointEllipsoid(r_(0), r_(1), r_(2), pt_ellip_frame.x(), pt_ellip_frame.y(),
                                       pt_ellip_frame.z(), closest_pt_on_ellip.x(), closest_pt_on_ellip.y(),
                                       closest_pt_on_ellip.z());
  closest_pt_on_ellip = R_ * closest_pt_on_ellip + d_;
  return dist;
}

int Ellipsoid::nearestPointId(const Eigen::Matrix3Xd &pc) const {
  const Eigen::VectorXd dists = (C_inv_ * (pc.colwise() - d_)).colwise().norm();
  int np_id = 0;
  dists.minCoeff(&np_id);
  return np_id;
}

Eigen::Vector3d Ellipsoid::nearestPoint(const Eigen::Matrix3Xd &pc) const {
  const Eigen::VectorXd dists = (C_inv_ * (pc.colwise() - d_)).colwise().norm();
  int np_id = 0;
  dists.minCoeff(&np_id);
  return pc.col(np_id);
}

double Ellipsoid::nearestPointDis(const Eigen::Matrix3Xd &pc, int &np_id) const {
  const Eigen::VectorXd dists = (C_inv_ * (pc.colwise() - d_)).colwise().norm();
  return dists.minCoeff(&np_id);
}

Eigen::Matrix3d Ellipsoid::C() const { return C_; }

Eigen::Vector3d Ellipsoid::d() const { return d_; }

Eigen::Matrix3d Ellipsoid::R() const { return R_; }

Eigen::Vector3d Ellipsoid::r() const { return r_; }

Eigen::Vector3d Ellipsoid::toEllipsoidFrame(const Eigen::Vector3d &pt_w) const {
  return C_inv_ * (pt_w - d_);
}

Eigen::Matrix3Xd Ellipsoid::toEllipsoidFrame(const Eigen::Matrix3Xd &pc_w) const {
  return C_inv_ * (pc_w.colwise() - d_);
}

Eigen::Vector3d Ellipsoid::toWorldFrame(const Eigen::Vector3d &pt_e) const { return C_ * pt_e + d_; }

Eigen::Vector4d Ellipsoid::toEllipsoidFrame(const Eigen::Vector4d &plane_w) const {
  Eigen::Vector4d plane_e;
  plane_e.head(3) = plane_w.head(3).transpose() * C_;
  plane_e(3) = plane_w(3) + plane_w.head(3).dot(d_);
  return plane_e;
}

Eigen::Vector4d Ellipsoid::toWorldFrame(const Eigen::Vector4d &plane_e) const {
  Eigen::Vector4d plane_w;
  plane_w.head(3) = plane_e.head(3).transpose() * C_inv_;
  plane_w(3) = plane_e(3) - plane_w.head(3).dot(d_);
  return plane_w;
}

Eigen::MatrixX4d Ellipsoid::toEllipsoidFrame(const Eigen::MatrixX4d &planes_w) const {
  Eigen::MatrixX4d planes_e(planes_w.rows(), planes_w.cols());
  planes_e.leftCols(3) = planes_w.leftCols(3) * C_;
  planes_e.rightCols(1) = planes_w.rightCols(1) + planes_w.leftCols(3) * d_;
  return planes_e;
}

Eigen::MatrixX4d Ellipsoid::toWorldFrame(const Eigen::MatrixX4d &planes_e) const {
  Eigen::MatrixX4d planes_w(planes_e.rows(), planes_e.cols());
  planes_w.leftCols(3) = planes_e.leftCols(3) * C_inv_;
  planes_w.rightCols(1) = planes_e.rightCols(1) + planes_w.leftCols(3) * d_;
  return planes_w;
}

double Ellipsoid::dist(const Eigen::Vector3d &pt_w) const { return (C_inv_ * (pt_w - d_)).norm(); }

Eigen::VectorXd Ellipsoid::dist(const Eigen::Matrix3Xd &pc_w) const {
  return (C_inv_ * (pc_w.colwise() - d_)).colwise().norm();
}

bool Ellipsoid::noPointsInside(PointCloud &pc, const Eigen::Matrix3d &R, const Eigen::Vector3d &r,
                               const Eigen::Vector3d &p) const {
  const Eigen::Matrix3d C_inv = r.cwiseInverse().asDiagonal() * R.transpose();
  for (const auto &pt_w : pc) {
    if ((C_inv * (pt_w - p)).norm() <= 1.0) {
      return false;
    }
  }
  return true;
}

bool Ellipsoid::pointsInside(const Eigen::Matrix3Xd &pc, Eigen::Matrix3Xd &out, int &min_pt_id) const {
  const Eigen::VectorXd vec = (C_inv_ * (pc.colwise() - d_)).colwise().norm();
  std::vector<Eigen::Vector3d, Eigen::aligned_allocator<Eigen::Vector3d>> pts;
  pts.reserve(pc.cols());
  int cnt = 0;
  min_pt_id = 0;
  double min_dis = std::numeric_limits<double>::max();
  for (long int i = 0; i < vec.size(); i++) {
    if (vec(i) <= 1.0) {
      pts.push_back(pc.col(i));
      if (vec(i) <= min_dis) {
        min_pt_id = cnt;
        min_dis = vec(i);
      }
      cnt++;
    }
  }
  if (!pts.empty()) {
    out = Eigen::Map<const Eigen::Matrix<double, 3, -1, Eigen::ColMajor>>(pts[0].data(), 3, pts.size());
    return true;
  }
  return false;
}

bool Ellipsoid::inside(const Eigen::Vector3d &pt) const { return dist(pt) <= 1.0; }

}  // namespace corridor_gen
