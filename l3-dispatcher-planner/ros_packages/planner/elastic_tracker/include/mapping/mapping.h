#pragma once
#include <Eigen/Core>
#include <functional>
namespace mapping {
// 原生领域地图查询，直接由当前地图 owner 注入；无消息转发或地图副本。
struct OccGridMap {
  double resolution{0.1};
  std::function<bool(const Eigen::Vector3d&)> occupied;
  Eigen::Vector3i pos2idx(const Eigen::Vector3d& p) const { return (p/resolution).array().floor().cast<int>(); }
  Eigen::Vector3d idx2pos(const Eigen::Vector3i& i) const { return (i.cast<double>().array()+0.5)*resolution; }
  bool isOccupied(const Eigen::Vector3d& p) const { return !p.allFinite() || !occupied || occupied(p); }
  bool isOccupied(const Eigen::Vector3i& i) const { return isOccupied(idx2pos(i)); }
};
}
