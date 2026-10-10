#pragma once
#include <Eigen/Dense>
#include <Eigen/Geometry>
#include <deque>
#include <cmath>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <vector>

namespace tracking {
struct PoseSample {
  double stamp;
  Eigen::Vector3d position;
  Eigen::Quaterniond orientation;
};

class PoseHistory {
  std::deque<PoseSample> samples_;
public:
  void add(const PoseSample& p) {
    if (!std::isfinite(p.stamp) || !p.position.allFinite() || !p.orientation.coeffs().allFinite() ||
        p.orientation.norm() < 1e-9) return;
    if (!samples_.empty() && p.stamp < samples_.back().stamp) samples_.clear();
    if (!samples_.empty() && p.stamp == samples_.back().stamp) return;
    samples_.push_back({p.stamp, p.position, p.orientation.normalized()});
    while (samples_.size() > 4000 || p.stamp - samples_.front().stamp > 15.0) samples_.pop_front();
  }
  bool at(double stamp, PoseSample& out, double max_gap = 0.25) const {
    if (samples_.empty() || stamp < samples_.front().stamp || stamp > samples_.back().stamp) return false;
    for (size_t i = 0; i < samples_.size(); ++i) {
      if (samples_[i].stamp == stamp) { out = samples_[i]; return true; }
      if (samples_[i].stamp > stamp && i > 0) {
        const auto &a = samples_[i-1], &b = samples_[i];
        if (b.stamp - a.stamp > max_gap) return false;
        const double t = (stamp-a.stamp)/(b.stamp-a.stamp);
        out = {stamp, (1-t)*a.position+t*b.position, a.orientation.slerp(t,b.orientation)};
        return true;
      }
    }
    return false;
  }
};

inline bool projectWithDepth(double u, double v, double fx, double fy, double cx, double cy,
                            const Eigen::Matrix3d& mount, const Eigen::Vector3d& translation,
                            const PoseSample& body, double depth, double height, Eigen::Vector3d& world) {
  if (!(std::isfinite(fx) && std::isfinite(fy) && fx > 0 && fy > 0 && std::isfinite(height)) ||
      !mount.allFinite() || !translation.allFinite()) return false;
  // Optical right/down/forward -> body forward/left/up, followed by mount rotation.
  Eigen::Matrix3d optical;
  optical << 0,0,1, -1,0,0, 0,-1,0;
  const Eigen::Vector3d ray = body.orientation * (mount * optical * Eigen::Vector3d((u-cx)/fx,(v-cy)/fy,1));
  const Eigen::Vector3d origin = body.position + body.orientation * translation;
  if (!ray.allFinite() || !origin.allFinite()) return false;
  if (!std::isfinite(depth) || depth <= 0) return false;
  world = origin + depth*ray;
  // First measure world XYZ; the requested height must never alter measured X/Y.
  world.z() = height;
  return world.allFinite();
}

// The input is depth registered to the RGB pixel grid. Respect row padding,
// byte order and ROS depth units (16UC1 millimetres, 32FC1 metres).
template <typename Image, typename Box>
inline bool bboxDepth(const Image& image, const Box& box, double& depth) {
  const bool floating = image.encoding == "32FC1";
  if (!floating && image.encoding != "16UC1") return false;
  const size_t bytes = floating ? 4 : 2;
  if (!image.width || !image.height || image.step < size_t(image.width)*bytes ||
      image.data.size() < size_t(image.step)*image.height) return false;
  for (double value : box) if (!std::isfinite(value)) return false;
  if (box[0]<0 || box[1]<0 || box[2]<=box[0] || box[3]<=box[1] ||
      box[2]>image.width || box[3]>image.height) return false;
  std::vector<double> values;
  for (int y=int(std::floor(box[1])); y<int(std::ceil(box[3])); ++y) {
    for (int x=int(std::floor(box[0])); x<int(std::ceil(box[2])); ++x) {
      const size_t offset=size_t(y)*image.step+size_t(x)*bytes;
      uint32_t raw=0;
      for (size_t k=0;k<bytes;++k)
        raw |= uint32_t(image.data[offset+k]) << (8*(image.is_bigendian ? bytes-1-k : k));
      double value;
      if (floating) { float v; std::memcpy(&v,&raw,sizeof(v)); value=v; }
      else value=raw*0.001;
      if (std::isfinite(value) && value>0) values.push_back(value);
    }
  }
  if (values.empty()) return false;
  const size_t mid=values.size()/2;
  std::nth_element(values.begin(),values.begin()+mid,values.end());
  depth=values[mid];
  if (values.size()%2==0) depth=0.5*(depth+*std::max_element(values.begin(),values.begin()+mid));
  return true;
}

// Upstream target_ekf_node's six-state constant-velocity KF, updated at image time.
// Publication predicts a copy; delayed observations never update a future state.
class TargetEstimator {
  using State = Eigen::Matrix<double,6,1>;
  using Cov = Eigen::Matrix<double,6,6>;
  State x_ = State::Zero();
  Cov covariance_ = Cov::Zero();
  double stamp_ = -1;
public:
  void reset() { stamp_ = -1; x_.setZero(); covariance_.setZero(); }
  double observationStamp() const { return stamp_; }
  bool initialized() const { return stamp_ >= 0; }
  bool update(const Eigen::Vector3d& point, double stamp) {
    if (!point.allFinite() || !std::isfinite(stamp) || stamp <= 0 || (initialized() && stamp <= stamp_)) return false;
    if (!initialized() || stamp-stamp_ > 3.0) {
      x_.setZero(); x_.head<3>()=point; covariance_.setZero(); stamp_=stamp; return true;
    }
    const double dt=stamp-stamp_;
    Cov a=Cov::Identity(); a.topRightCorner<3,3>()=dt*Eigen::Matrix3d::Identity();
    Eigen::Matrix<double,6,3> b;
    b.topRows<3>()=0.5*dt*dt*Eigen::Matrix3d::Identity();
    b.bottomRows<3>()=dt*Eigen::Matrix3d::Identity();
    const Cov p=a*covariance_*a.transpose()+b*Eigen::Vector3d(4,4,1).asDiagonal()*b.transpose();
    const State predicted=a*x_;
    const Eigen::Matrix<double,6,3> k=p.leftCols<3>()*(p.topLeftCorner<3,3>()+0.1*Eigen::Matrix3d::Identity()).inverse();
    State candidate=predicted+k*(point-predicted.head<3>());
    if (!candidate.allFinite() || candidate.tail<3>().norm()>4.0) return false;
    // The measurement is a fixed world-height target, not a vertical-motion estimate.
    candidate(2)=point.z(); candidate(5)=0;
    x_=candidate;
    Cov ikh=Cov::Identity(); ikh.leftCols<3>()-=k;
    covariance_=ikh*p*ikh.transpose()+0.1*k*k.transpose();
    stamp_=stamp;
    return true;
  }
  bool estimate(double now, Eigen::Vector3d& position, Eigen::Vector3d& velocity) const {
    if (!initialized() || !std::isfinite(now) || now<stamp_ || now-stamp_>=2.0) return false;
    velocity=x_.tail<3>(); position=x_.head<3>()+(now-stamp_)*velocity;
    return position.allFinite();
  }
  Eigen::Matrix3d positionCovariance(double now) const {
    Eigen::Matrix<double,3,6> c=Eigen::Matrix<double,3,6>::Zero();
    c.leftCols<3>().setIdentity(); c.rightCols<3>()=(now-stamp_)*Eigen::Matrix3d::Identity();
    return c*covariance_*c.transpose();
  }
};
} // namespace tracking
