#pragma once
#include <Eigen/Core>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <string>
#include <vector>

namespace elastic_tracker {
enum class MapState { Unknown, Free, Occupied, Outside, Boundary };
/** 无融合状态的不可变分类数据。Free 表示历史射线证据，不表示逐格最新观测。 */
struct MapView {
  enum : uint8_t { ObservedFree=1, BaseObstacle=2, InflatedObstacle=4 };
  double resolution{0};
  Eigen::Vector3i origin{Eigen::Vector3i::Zero()}, size{Eigen::Vector3i::Zero()};
  std::vector<uint8_t> cells;
  std::string frame;
  uint64_t revision{0}, reset_epoch{0};
  double source_time{0}, fusion_time{0}, fusion_monotonic{0}, timeout_s{0};
  bool virtual_wall{false};
  double ground{0}, ceiling{0};

  bool contains(const Eigen::Vector3i& i) const {
    const Eigen::Matrix<int64_t,3,1> d=i.cast<int64_t>()-origin.cast<int64_t>();
    return (d.array()>=0).all() && (d.array()<size.cast<int64_t>().array()).all();
  }
  Eigen::Vector3i index(const Eigen::Vector3d& p) const {
    return (p/resolution).array().floor().cast<int>();
  }
  Eigen::Vector3d center(const Eigen::Vector3i& i) const {
    return (i.cast<double>().array()+0.5)*resolution;
  }
  MapState state(const Eigen::Vector3d& p, bool inflated=true) const {
    if(!p.allFinite() || !std::isfinite(resolution) || resolution<=0) return MapState::Outside;
    if(virtual_wall && (p.z()<=ground || p.z()>=ceiling)) return MapState::Boundary;
    const auto q=(p/resolution).array().floor().eval();
    if((q<std::numeric_limits<int>::min()).any() || (q>std::numeric_limits<int>::max()).any()) return MapState::Outside;
    const Eigen::Vector3i i=q.cast<int>();
    if(!contains(i)) return MapState::Outside;
    const Eigen::Vector3i d=i-origin;
    const size_t offset=(size_t(d.z())*size_t(size.y())+size_t(d.y()))*size_t(size.x())+size_t(d.x());
    if(offset>=cells.size()) return MapState::Outside;
    const auto value=cells[offset];
    if(value & (BaseObstacle | (inflated ? InflatedObstacle : 0))) return MapState::Occupied;
    return value & ObservedFree ? MapState::Free : MapState::Unknown;
  }
  bool flightFree(const Eigen::Vector3d& p) const { return state(p)==MapState::Free; }
  bool flightFree(const Eigen::Vector3i& i) const { return contains(i) && flightFree(center(i)); }
  bool fresh(double now, double monotonic_now) const {
    return revision>0 && std::isfinite(now) && std::isfinite(monotonic_now) && timeout_s>0 &&
      source_time>0 && now>=source_time && now-source_time<=timeout_s &&
      fusion_time>0 && fusion_monotonic>0 && now>=fusion_time && now-fusion_time<=timeout_s &&
      monotonic_now>=fusion_monotonic && monotonic_now-fusion_monotonic<=timeout_s;
  }
  /** 保守格遍历；同时跨格时检查所有相邻组合，避免沿格边漏掉障碍。 */
  bool clearSegment(const Eigen::Vector3d& a, const Eigen::Vector3d& b, bool visibility=false) const {
    if(!a.allFinite() || !b.allFinite() || state(a,false)==MapState::Outside || state(b,false)==MapState::Outside ||
       state(a,false)==MapState::Boundary || state(b,false)==MapState::Boundary) return false;
    Eigen::Vector3i i=index(a), end=index(b);
    auto clear=[&](const Eigen::Vector3i& cell) {
      if(visibility && cell==end) return true;
      return state(center(cell),!visibility)==MapState::Free;
    };
    if(!clear(i)) return false;
    const Eigen::Vector3d delta=b-a;
    Eigen::Vector3i step=Eigen::Vector3i::Zero();
    Eigen::Vector3d next, stride;
    for(int axis=0;axis<3;++axis) {
      if(delta[axis]==0) {next[axis]=stride[axis]=std::numeric_limits<double>::infinity(); continue;}
      step[axis]=delta[axis]>0 ? 1 : -1;
      stride[axis]=resolution/std::abs(delta[axis]);
      const double boundary=(double(i[axis])+(step[axis]>0 ? 1.0 : 0.0))*resolution;
      next[axis]=(boundary-a[axis])/delta[axis];
    }
    const int64_t budget=(end.cast<int64_t>()-i.cast<int64_t>()).cwiseAbs().sum()+1;
    for(int64_t count=0;count<budget && i!=end;++count) {
      const double crossing=next.minCoeff();
      int mask=0;
      for(int axis=0;axis<3;++axis) if(next[axis]<=crossing+1e-12) mask|=1<<axis;
      for(int subset=1;subset<8;++subset) if((subset & mask)==subset) {
        auto neighbor=i;
        for(int axis=0;axis<3;++axis) if(subset & (1<<axis)) neighbor[axis]+=step[axis];
        if(!clear(neighbor)) return false;
      }
      for(int axis=0;axis<3;++axis) if(mask & (1<<axis)) {i[axis]+=step[axis]; next[axis]+=stride[axis];}
    }
    return i==end;
  }
};
using MapReader=std::function<std::shared_ptr<const MapView>()>;
}
