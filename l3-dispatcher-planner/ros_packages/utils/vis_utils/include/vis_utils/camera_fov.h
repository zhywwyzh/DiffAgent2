#ifndef VIS_UTILS_CAMERA_FOV_H_
#define VIS_UTILS_CAMERA_FOV_H_

#include <Eigen/Eigen>
#include <ros/ros.h>

#include <memory>
#include <vector>

namespace vis_utils {

class PerceptionUtils {
public:
  using Ptr = std::shared_ptr<PerceptionUtils>;

  explicit PerceptionUtils(ros::NodeHandle& nh);

  void setPose(const Eigen::Vector3d& pos, double yaw);
  void getFOV(std::vector<Eigen::Vector3d>& list1, std::vector<Eigen::Vector3d>& list2);
  bool insideFOV(const Eigen::Vector3d& point);
  void getFOVBoundingBox(Eigen::Vector3d& bmin, Eigen::Vector3d& bmax);
  double getSensorMaxDist() const;

private:
  Eigen::Vector3d pos_;
  double yaw_;
  std::vector<Eigen::Vector3d> normals_;

  double left_angle_, right_angle_, top_angle_, max_dist_, vis_dist_;
  Eigen::Vector3d n_top_, n_bottom_, n_left_, n_right_;
  Eigen::Matrix4d T_cb_, T_bc_;
  std::vector<Eigen::Vector3d> cam_vertices1_, cam_vertices2_;
};

inline double PerceptionUtils::getSensorMaxDist() const { return max_dist_; }

} // namespace vis_utils

#endif
