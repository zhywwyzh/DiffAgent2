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

#ifndef SRC_ROS1_VISUALIZER_HPP
#define SRC_ROS1_VISUALIZER_HPP

#include "ros_interface/ros1/ros1_adapter.hpp"
#include "ros_interface/ros1/telemetry_sinks.hpp"

#include <nav_msgs/Path.h>
#include <quadrotor_msgs/PiecewisePolynomial.h>
#include <quadrotor_msgs/piecewise_from_poly.hpp>
namespace super_planner {
namespace ros_interface {
class Ros1Interface : public RosInterface {
public:
  explicit Ros1Interface(const ros::NodeHandle& nh) : nh_(nh) {

    /*=============================FOR Planner========================================*/
    goal_pub_ = nh_.advertise<visualization_msgs::MarkerArray>("visualization/goal", 100);

    exp_traj_pub_ = nh_.advertise<visualization_msgs::MarkerArray>("visualization/exp_traj", 100);
    backup_traj_pub_ = nh_.advertise<visualization_msgs::MarkerArray>("visualization/backup_traj", 100);
    committed_traj_pub_ = nh_.advertise<visualization_msgs::MarkerArray>("visualization/committed_traj", 100);

    exp_sfcs_pub_ = nh_.advertise<visualization_msgs::MarkerArray>("visualization/exp_sfc", 100);
    backup_sfc_pub_ = nh_.advertise<visualization_msgs::MarkerArray>("visualization/backup_sfc", 100);

    guide_path_pub_ = nh_.advertise<visualization_msgs::MarkerArray>("visualization/frontend_path", 100);
    search_path_pub_ = nh_.advertise<nav_msgs::Path>("planner/search_path", 10);
    optimized_traj_pub_ = nh_.advertise<quadrotor_msgs::PiecewisePolynomial>("planner/optimized_traj", 10);

    yaw_traj_pub_ = nh_.advertise<visualization_msgs::MarkerArray>("visualization/yaw_traj", 100);

    fov_pub_ = nh_.advertise<visualization_msgs::Marker>("visualization/fov", 10);

    /*=============================FOR A* debug ========================================*/
    astar_mkr_pub_ = nh_.advertise<visualization_msgs::MarkerArray>("visualization/astar_debug", 100);

    /*=============================FOR A* debug ========================================*/
    ciri_mkr_pub_ = nh_.advertise<visualization_msgs::MarkerArray>("visualization/ciri_debug_mkr", 100);
    ciri_pc_pub_ = nh_.advertise<sensor_msgs::PointCloud2>("visualization/ciri_debug_pc", 100);
  }

  /*=============================FOR ROS logger ========================================*/
  void debug(const std::string& msg) override { slog::debug(msg); }
  void info(const std::string& msg) override { slog::info(msg); }
  void warn(const std::string& msg) override { slog::warn(msg); }
  void error(const std::string& msg) override { slog::error(msg); }
  void fatal(const std::string& msg) override { slog::error(msg); }

  /* Telemetry wiring: stdout JSONL is always-on; mcap recording is the
   * sim-only binary sink owned by the global slog registry. */
  void initTelemetry(const std::string& level, const bool stdout_en, const bool mcap_en, const std::string& mcap_dir) {
    slog::set_level(slog::level_from_string(level));
    slog::set_stdout_en(stdout_en);
    slog::set_time_fn([]() -> int64_t {
      const ros::Time t = ros::Time::now();
      return static_cast<int64_t>(t.sec) * 1000000000LL + static_cast<int64_t>(t.nsec);
    });
    if (mcap_en) {
      auto sink = std::make_unique<super_planner::telemetry::McapSink>();
      if (sink->open(mcap_dir)) {
        mcap_ = sink.get();
        slog::add_sink(std::move(sink));
      }
    }
  }

  super_planner::telemetry::McapSink* mcap() { return mcap_; }

  double getSimTime() override { return ros::Time::now().toSec(); }

  void getSimTime(int32_t& sec, uint32_t& nsec) override {
    ros::Time now = ros::Time::now();
    sec = now.sec;
    nsec = now.nsec;
  }

  void setSimTime(const double& sim_time) override { ros::Time::setNow(ros::Time(sim_time)); }

  /*=============================FOR Planner========================================*/
  void vizExpTraj(const Trajectory& traj, const std::string& ns = "exp_traj") override {
    if (!visualization_en_) {
      return;
    }
    if (exp_traj_pub_.getNumSubscribers() <= 0) {
      return;
    }
    if (traj.empty()) {
      return;
    }
    Ros1Adapter::deleteAllMarkerArray(exp_traj_pub_);
    visualization_msgs::MarkerArray mkr_arr;
    Ros1Adapter::addTrajectoryToMarkerArray(mkr_arr, traj, ns, Color::Green(), 0.08, true, true);
    exp_traj_pub_.publish(mkr_arr);
  }

  void vizBackupTraj(const Trajectory& traj) {
    if (!visualization_en_) {
      return;
    }
    if (backup_traj_pub_.getNumSubscribers() <= 0) {
      return;
    }
    if (traj.empty()) {
      return;
    }
    Ros1Adapter::deleteAllMarkerArray(backup_traj_pub_);
    visualization_msgs::MarkerArray mkr_arr;
    Ros1Adapter::addTrajectoryToMarkerArray(mkr_arr, traj, "backup_traj", Color::Green(), 0.08, true, false);
    Ros1Adapter::addPointToMarkerArray(mkr_arr, traj.getPos(0), Color::Gray(), "backup_traj_start", 0.31);
    backup_traj_pub_.publish(mkr_arr);
  }

  void vizFrontendPath(const super_planner::super_utils::vec_Vec3f& path) override {
    if (!visualization_en_) {
      return;
    }
    if (path.empty()) {
      return;
    }
    Ros1Adapter::deleteAllMarkerArray(guide_path_pub_);
    visualization_msgs::MarkerArray mkr_arr;
    Ros1Adapter::addPathToMarkerArray(mkr_arr, path, Color::Pink(), "guide_path", 0.1, 0.05);
    guide_path_pub_.publish(mkr_arr);
  }

  /* Canonical station topics (ground-station-channels.spec.md §2.5):
   * raw A* front-end search result + committed optimized trajectory,
   * published on the remapped /drone_<id>/planner/search_path and
   * /drone_<id>/planner/optimized_traj. Unlike the viz callbacks these
   * are NOT gated by visualization_en_ — the ground station is a data
   * consumer, not a viewer. */
  void publishSearchPath(const super_planner::super_utils::vec_Vec3f& path) override {
    if (path.empty()) {
      return;
    }
    nav_msgs::Path msg;
    msg.header.stamp = ros::Time::now();
    msg.header.frame_id = "world";
    msg.poses.reserve(path.size());
    for (const auto& p : path) {
      geometry_msgs::PoseStamped ps;
      ps.header = msg.header;
      ps.pose.position.x = p.x();
      ps.pose.position.y = p.y();
      ps.pose.position.z = p.z();
      ps.pose.orientation.w = 1.0;
      msg.poses.push_back(ps);
    }
    search_path_pub_.publish(msg);
  }

  void publishOptimizedTraj(const super_planner::geometry_utils::Trajectory& committed_traj) override {
    if (committed_traj.empty()) {
      return;
    }
    quadrotor_msgs::PiecewisePolynomial msg;
    msg.header.stamp = ros::Time::now();
    msg.header.frame_id = "world";
    /* SUPER stores coefficients descending-power (Piece col j = t^(D-j),
     * see data_structure/base/piece.h); the canonical wire format is
     * ascending-power (index j = t^j), so reverse each axis. */
    quadrotor_msgs::FillPiecewisePolynomial(
        committed_traj, committed_traj[0].getDegree(),
        [](const super_planner::geometry_utils::Trajectory& t, int i) { return t[i]; },
        [](const super_planner::geometry_utils::Piece& piece, int axis, int power) {
          return piece.getCoeffMat()(axis, piece.getDegree() - power);
        },
        msg);
    optimized_traj_pub_.publish(msg);
  }

  void vizExpSfc(const PolytopeVec& sfcs) override {
    if (!visualization_en_) {
      return;
    }
    if (exp_sfcs_pub_.getNumSubscribers() <= 0) {
      return;
    }
    if (sfcs.empty()) {
      return;
    }
    Ros1Adapter::deleteAllMarkerArray(exp_sfcs_pub_);
    visualization_msgs::MarkerArray mkr_arr;
    int color_num = sfcs.size();
    int color_id = 0;
    for (auto p : sfcs) {
      double color_ratio = 1.0 - (double)color_id / color_num;
      Vec3f color_mag = tinycolormap::GetColor(color_ratio, tinycolormap::ColormapType::Jet).ConvertToEigen();
      color_id++;
      Color c(color_mag[0], color_mag[1], color_mag[2]);
      Ros1Adapter::addPolytopeToMarkerArray(mkr_arr, p, "exp_sfc", false, Color::SteelBlue(), c, Color::Orange(), 0.15,
                                            resolution_ / 2);
    }
    exp_sfcs_pub_.publish(mkr_arr);
  }

  void vizBackupSfc(const Polytope& sfc) override {
    if (!visualization_en_) {
      return;
    }
    if (backup_sfc_pub_.getNumSubscribers() <= 0) {
      return;
    }
    Ros1Adapter::deleteAllMarkerArray(backup_sfc_pub_);
    visualization_msgs::MarkerArray mkr_arr;
    Ros1Adapter::addPolytopeToMarkerArray(mkr_arr, sfc, "backup_sfc", false, Color::Chartreuse(), Color::Green(),
                                          Color::Green(), 0.15, resolution_ / 2);
    backup_sfc_pub_.publish(mkr_arr);
  }

  void vizGoalPath(const super_planner::super_utils::vec_Vec3f& path) override {
    if (!visualization_en_) {
      return;
    }

    if (goal_pub_.getNumSubscribers() <= 0) {
      return;
    }

    if (path.empty()) {
      return;
    }

    Ros1Adapter::deleteAllMarkerArray(goal_pub_);

    visualization_msgs::MarkerArray mkr_arr;
    Ros1Adapter::addPathToMarkerArray(mkr_arr, path, Color::Yellow(), "goal", 0.3, 0.15);
    goal_pub_.publish(mkr_arr);
  }

  void vizCommittedTraj(const super_planner::geometry_utils::Trajectory& committed_traj,
                        const double& backup_traj_start_TT) override {
    if (!visualization_en_) {
      return;
    }
    if (committed_traj_pub_.getNumSubscribers() <= 0) {
      return;
    }

    if (committed_traj.empty()) {
      return;
    }

    Ros1Adapter::deleteAllMarkerArray(committed_traj_pub_);

    visualization_msgs::MarkerArray mkr_arr;

    double traj_dur = committed_traj.getTotalDuration();

    if (backup_traj_start_TT > 0 && backup_traj_start_TT < traj_dur) {
      Trajectory exp_traj;
      if (!committed_traj.getPartialTrajectoryByTime(0, backup_traj_start_TT, exp_traj)) {
        ROS_ERROR("Failed to get partial trajectory");
        return;
      }
      Trajectory backup_traj;
      if (!committed_traj.getPartialTrajectoryByTime(backup_traj_start_TT, traj_dur, backup_traj)) {
        ROS_ERROR("Failed to get partial trajectory");
        return;
      }
      visualization_msgs::MarkerArray mkr_arr;
      Ros1Adapter::addTrajectoryToMarkerArray(mkr_arr, exp_traj, "committed_exp", Color::SteelBlue(), 0.08, true,
                                              false);
      Ros1Adapter::addTrajectoryToMarkerArray(mkr_arr, backup_traj, "committed_backup", Color::Green(), 0.1, false,
                                              false);
      committed_traj_pub_.publish(mkr_arr);
    } else {
      visualization_msgs::MarkerArray mkr_arr;
      Ros1Adapter::addTrajectoryToMarkerArray(mkr_arr, committed_traj, "committed_exp", Color::Green(), 0.1, true,
                                              false);
      committed_traj_pub_.publish(mkr_arr);
    }

    committed_traj_pub_.publish(mkr_arr);
  }

  void vizYawTraj(const Trajectory& pos_traj, const Trajectory& yaw_traj) override {
    if (!visualization_en_ || pos_traj.empty() || yaw_traj.empty()) {
      return;
    }

    if (yaw_traj_pub_.getNumSubscribers() <= 0) {
      return;
    }

    if (pos_traj.empty() || yaw_traj.empty()) {
      return;
    }

    Ros1Adapter::deleteAllMarkerArray(yaw_traj_pub_);
    visualization_msgs::MarkerArray mkr_arr;
    Ros1Adapter::addYawTrajectoryToMarkerArray(mkr_arr, pos_traj, yaw_traj);
    yaw_traj_pub_.publish(mkr_arr);
  }

  void vizFov(const std::vector<Eigen::Vector3d>& list1, const std::vector<Eigen::Vector3d>& list2) {
    if (!visualization_en_)
      return;
    if (fov_pub_.getNumSubscribers() <= 0)
      return;

    visualization_msgs::Marker mk;
    mk.header.frame_id = "world";
    mk.header.stamp = ros::Time::now();
    mk.id = 0;
    mk.ns = "current_pose";
    mk.type = visualization_msgs::Marker::LINE_LIST;
    mk.pose.orientation.w = 1.0;
    mk.color.r = 1.0;
    mk.color.g = 0.0;
    mk.color.b = 0.0;
    mk.color.a = 1.0;
    mk.scale.x = 0.04;

    mk.action = visualization_msgs::Marker::DELETE;
    fov_pub_.publish(mk);

    if (list1.empty())
      return;

    mk.action = visualization_msgs::Marker::ADD;
    geometry_msgs::Point pt;
    for (size_t i = 0; i < list1.size(); ++i) {
      pt.x = list1[i].x();
      pt.y = list1[i].y();
      pt.z = list1[i].z();
      mk.points.push_back(pt);
      pt.x = list2[i].x();
      pt.y = list2[i].y();
      pt.z = list2[i].z();
      mk.points.push_back(pt);
    }
    fov_pub_.publish(mk);
  }

  /*=============================FOR A* debug ========================================*/
  void vizAstarBoundingBox(const super_planner::super_utils::Vec3f& bbox_min,
                           const super_planner::super_utils::Vec3f& bbox_max) override {
    if (!visualization_en_) {
      return;
    }

    if (astar_mkr_pub_.getNumSubscribers() <= 0) {
      return;
    }

    visualization_msgs::MarkerArray mkr_arr;
    Ros1Adapter::addBoundingBoxToMarkerArray(mkr_arr, bbox_min, bbox_max, "local_map", Color::Chartreuse());
    astar_mkr_pub_.publish(mkr_arr);
  }

  void vizAstarPoints(const super_planner::super_utils::Vec3f& position, const Color& c, const std::string& ns = "none",
                      const double& size = 0.1, const int& id = 0) override {
    if (!visualization_en_) {
      return;
    }

    if (astar_mkr_pub_.getNumSubscribers() <= 0) {
      return;
    }

    visualization_msgs::MarkerArray mkr_arr;
    Ros1Adapter::addPointToMarkerArray(mkr_arr, position, c, ns, size);
    astar_mkr_pub_.publish(mkr_arr);
  }

  /*=============================FOR replan log ========================================*/
  static void buildReplanMarkers(const Trajectory& exp_traj, const Trajectory& backup_traj,
                                 const Trajectory& exp_yaw_traj, const Trajectory& backup_yaw_traj,
                                 const PolytopeVec& exp_sfc, const Polytope& backup_sfc,
                                 visualization_msgs::MarkerArray& mkr_arr) {
    super_planner::ros_interface::Ros1Adapter::addTrajectoryToMarkerArray(mkr_arr, exp_traj, "exp_traj",
                                                                          Color::Orange(), 0.1, false, false);
    super_planner::ros_interface::Ros1Adapter::addTrajectoryToMarkerArray(mkr_arr, backup_traj, "backup_traj",
                                                                          Color::Green(), 0.1, false, false);
    super_planner::ros_interface::Ros1Adapter::addYawTrajectoryToMarkerArray(mkr_arr, exp_traj, exp_yaw_traj,
                                                                             "exp_yaw_traj");
    super_planner::ros_interface::Ros1Adapter::addYawTrajectoryToMarkerArray(mkr_arr, backup_traj, backup_yaw_traj,
                                                                             "backup_yaw_traj");

    int color_id = 0;
    int color_num = exp_sfc.size();

    for (auto p : exp_sfc) {
      double color_ratio = 1.0 - (double)color_id / color_num;
      Vec3f color_mag = tinycolormap::GetColor(color_ratio, tinycolormap::ColormapType::Jet).ConvertToEigen();
      color_id++;
      Color c(color_mag[0], color_mag[1], color_mag[2]);
      super_planner::ros_interface::Ros1Adapter::addPolytopeToMarkerArray(
          mkr_arr, p, "exp_sfc", false, Color::SteelBlue(), c, Color::Orange(), 0.15, 0.02);
    }

    super_planner::ros_interface::Ros1Adapter::addPolytopeToMarkerArray(
        mkr_arr, backup_sfc, "backup_sfc", false, Color::Chartreuse(), Color::Green(), Color::Green(), 0.15, 0.02);
  }

  static void buildReplanPointCloud(const vec_Vec3f& pc_for_sfc, sensor_msgs::PointCloud2& pc2) {
    super_planner::rog_map::PointCloud pc;
    for (auto p_e : pc_for_sfc) {
      super_planner::rog_map::PclPoint p;
      p.x = p_e.x();
      p.y = p_e.y();
      p.z = p_e.z();
      pc.push_back(p);
    }
    pcl::toROSMsg(pc, pc2);
    pc2.header.frame_id = "world";
    pc2.header.stamp = ros::Time::now();
  }

  void recordReplan(const Trajectory& exp_traj, const Trajectory& backup_traj, const Trajectory& exp_yaw_traj,
                    const Trajectory& backup_yaw_traj, const PolytopeVec& exp_sfc, const Polytope& backup_sfc,
                    const vec_Vec3f& pc_for_sfc, const bool keyframe, const bool ambient) override {
    if (!mcap_) {
      return;
    }
    const ros::Time t = ros::Time::now();
    const int64_t ts_ns = static_cast<int64_t>(t.sec) * 1000000000LL + static_cast<int64_t>(t.nsec);
    if (ambient || keyframe) {
      visualization_msgs::MarkerArray mkr_arr;
      buildReplanMarkers(exp_traj, backup_traj, exp_yaw_traj, backup_yaw_traj, exp_sfc, backup_sfc, mkr_arr);
      mcap_->writeMarkers("/replan_log/mkr", mkr_arr, ts_ns);
    }
    if (keyframe && !pc_for_sfc.empty()) {
      sensor_msgs::PointCloud2 pc2;
      buildReplanPointCloud(pc_for_sfc, pc2);
      mcap_->writePointCloud("/replan_log/pc", pc2, ts_ns);
      mcap_->flush();
    }
  }

  void recordCommand(const quadrotor_msgs::PositionCommand& cmd) {
    if (!mcap_) {
      return;
    }
    const ros::Time t = ros::Time::now();
    mcap_->writeCommand(cmd, static_cast<int64_t>(t.sec) * 1000000000LL + static_cast<int64_t>(t.nsec));
  }

  void vizCiriSeedLine(const super_planner::super_utils::Vec3f& a, const super_planner::super_utils::Vec3f& b,
                       const double& robot_r) override {
    if (!visualization_en_) {
      return;
    }
    if (ciri_mkr_pub_.getNumSubscribers() <= 0) {
      return;
    }
    visualization_msgs::MarkerArray mkr_arr;
    super_planner::ros_interface::Ros1Adapter::addLineToMarkerArray(mkr_arr, a, b, Color::Pink(), Color::Orange(),
                                                                    "seed_line", robot_r * 2, robot_r * 2);
    ciri_mkr_pub_.publish(mkr_arr);
  }

  void vizCiriEllipsoid(const super_planner::geometry_utils::Ellipsoid& ellipsoid) override {
    if (!visualization_en_) {
      return;
    }
    if (ciri_mkr_pub_.getNumSubscribers() <= 0) {
      return;
    }
    visualization_msgs::MarkerArray mkr_arr;
    super_planner::ros_interface::Ros1Adapter::addEllipsoidToMarkerArray(mkr_arr, ellipsoid, "ellipsoid",
                                                                         Color(Color::Orange(), 0.3));
    ciri_mkr_pub_.publish(mkr_arr);
  }

  void vizCiriInfeasiblePoint(const super_planner::super_utils::Vec3f p) override {
    if (!visualization_en_) {
      return;
    }
    if (ciri_mkr_pub_.getNumSubscribers() <= 0) {
      return;
    }
    visualization_msgs::MarkerArray mkr_arr;
    super_planner::ros_interface::Ros1Adapter::addPointToMarkerArray(mkr_arr, p, Color::Red(), "infeasible_pt", 0.1);
    ciri_mkr_pub_.publish(mkr_arr);
  }

  void vizCiriPolytope(const super_planner::geometry_utils::Polytope& polytope, const std::string& ns) override {
    if (!visualization_en_) {
      return;
    }
    if (ciri_mkr_pub_.getNumSubscribers() <= 0) {
      return;
    }
    visualization_msgs::MarkerArray mkr_arr;
    super_planner::ros_interface::Ros1Adapter::addPolytopeToMarkerArray(
        mkr_arr, polytope, ns, true, Color::Chartreuse(), Color::Green(), Color::Green(), 0.15, 0.02);
    ciri_mkr_pub_.publish(mkr_arr);
  }

  void vizCiriPointCloud(const vec_Vec3f& points) override {
    if (!visualization_en_) {
      return;
    }

    if (ciri_pc_pub_.getNumSubscribers() <= 0) {
      return;
    }

    sensor_msgs::PointCloud2 pc2;
    super_planner::ros_interface::Ros1Adapter::addVecPointsToPointCloud2(points, pc2);
    ciri_pc_pub_.publish(pc2);
  }

private:
  ros::NodeHandle nh_;
  // viz markers
  ros::Publisher goal_pub_, backup_sfc_pub_, backup_traj_pub_, committed_traj_pub_, receding_traj_pub_, exp_sfcs_pub_,
      point_pub_, fov_pub_, exp_traj_pub_, astar_pub_, receding_sfc_pub_, backup_traj_star_point_, yaw_traj_pub_,
      guide_path_pub_;

  ros::Publisher astar_mkr_pub_;

  /* Canonical station topics (spec §2.5): search_path + optimized_traj. */
  ros::Publisher search_path_pub_, optimized_traj_pub_;

  ros::Publisher ciri_mkr_pub_, ciri_pc_pub_;

  super_planner::telemetry::McapSink* mcap_{nullptr};
};
} // namespace ros_interface
} // namespace super_planner

#endif // SRC_ROS1_VISUALIZER_HPP
