#include <vis_utils/camera_fov.h>

#include <cmath>

namespace vis_utils {

PerceptionUtils::PerceptionUtils(ros::NodeHandle& nh) {
  nh.param("camera_fov/top_angle", top_angle_, -1.0);
  nh.param("camera_fov/left_angle", left_angle_, -1.0);
  nh.param("camera_fov/right_angle", right_angle_, -1.0);
  nh.param("camera_fov/max_dist", max_dist_, -1.0);
  nh.param("camera_fov/vis_dist", vis_dist_, -1.0);

  n_top_ << 0.0, sin(M_PI_2 - top_angle_), cos(M_PI_2 - top_angle_);
  n_bottom_ << 0.0, -sin(M_PI_2 - top_angle_), cos(M_PI_2 - top_angle_);

  n_left_ << sin(M_PI_2 - left_angle_), 0.0, cos(M_PI_2 - left_angle_);
  n_right_ << -sin(M_PI_2 - right_angle_), 0.0, cos(M_PI_2 - right_angle_);
  T_cb_ << 0, -1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1;
  T_bc_ = T_cb_.inverse();

  const double hor = vis_dist_ * tan(left_angle_);
  const double vert = vis_dist_ * tan(top_angle_);
  const Eigen::Vector3d origin(0, 0, 0);
  const Eigen::Vector3d left_up(vis_dist_, hor, vert);
  const Eigen::Vector3d left_down(vis_dist_, hor, -vert);
  const Eigen::Vector3d right_up(vis_dist_, -hor, vert);
  const Eigen::Vector3d right_down(vis_dist_, -hor, -vert);

  cam_vertices1_.push_back(origin);
  cam_vertices2_.push_back(left_up);
  cam_vertices1_.push_back(origin);
  cam_vertices2_.push_back(left_down);
  cam_vertices1_.push_back(origin);
  cam_vertices2_.push_back(right_up);
  cam_vertices1_.push_back(origin);
  cam_vertices2_.push_back(right_down);

  cam_vertices1_.push_back(left_up);
  cam_vertices2_.push_back(right_up);
  cam_vertices1_.push_back(right_up);
  cam_vertices2_.push_back(right_down);
  cam_vertices1_.push_back(right_down);
  cam_vertices2_.push_back(left_down);
  cam_vertices1_.push_back(left_down);
  cam_vertices2_.push_back(left_up);
}

void PerceptionUtils::setPose(const Eigen::Vector3d& pos, double yaw) {
  pos_ = pos;
  yaw_ = yaw;

  Eigen::Matrix3d R_wb;
  R_wb << cos(yaw_), -sin(yaw_), 0.0, sin(yaw_), cos(yaw_), 0.0, 0.0, 0.0, 1.0;

  Eigen::Matrix4d T_wb = Eigen::Matrix4d::Identity();
  T_wb.block<3, 3>(0, 0) = R_wb;
  T_wb.block<3, 1>(0, 3) = pos_;
  const Eigen::Matrix4d T_wc = T_wb * T_bc_;
  const Eigen::Matrix3d R_wc = T_wc.block<3, 3>(0, 0);
  normals_ = {n_top_, n_bottom_, n_left_, n_right_};
  for (auto& normal : normals_) {
    normal = R_wc * normal;
  }
}

void PerceptionUtils::getFOV(std::vector<Eigen::Vector3d>& list1, std::vector<Eigen::Vector3d>& list2) {
  list1.clear();
  list2.clear();

  Eigen::Matrix3d R_wb;
  R_wb << cos(yaw_), -sin(yaw_), 0, sin(yaw_), cos(yaw_), 0, 0, 0, 1;
  for (size_t i = 0; i < cam_vertices1_.size(); ++i) {
    list1.push_back(R_wb * cam_vertices1_[i] + pos_);
    list2.push_back(R_wb * cam_vertices2_[i] + pos_);
  }
}

bool PerceptionUtils::insideFOV(const Eigen::Vector3d& point) {
  Eigen::Vector3d dir = point - pos_;
  if (dir.norm() > max_dist_) {
    return false;
  }

  dir.normalize();
  for (const auto& normal : normals_) {
    if (dir.dot(normal) < 0.0) {
      return false;
    }
  }
  return true;
}

void PerceptionUtils::getFOVBoundingBox(Eigen::Vector3d& bmin, Eigen::Vector3d& bmax) {
  const double left = yaw_ + left_angle_;
  const double right = yaw_ - right_angle_;
  const Eigen::Vector3d left_pt = pos_ + max_dist_ * Eigen::Vector3d(cos(left), sin(left), 0);
  const Eigen::Vector3d right_pt = pos_ + max_dist_ * Eigen::Vector3d(cos(right), sin(right), 0);
  std::vector<Eigen::Vector3d> points = {left_pt, right_pt};
  if (left > 0 && right < 0) {
    points.push_back(pos_ + max_dist_ * Eigen::Vector3d(1, 0, 0));
  } else if (left > M_PI_2 && right < M_PI_2) {
    points.push_back(pos_ + max_dist_ * Eigen::Vector3d(0, 1, 0));
  } else if (left > -M_PI_2 && right < -M_PI_2) {
    points.push_back(pos_ + max_dist_ * Eigen::Vector3d(0, -1, 0));
  } else if ((left > M_PI && right < M_PI) || (left > -M_PI && right < -M_PI)) {
    points.push_back(pos_ + max_dist_ * Eigen::Vector3d(-1, 0, 0));
  }

  bmax = bmin = pos_;
  for (const auto& point : points) {
    bmax = bmax.array().max(point.array());
    bmin = bmin.array().min(point.array());
  }
}

} // namespace vis_utils
