#include "planner_execution/settle_monitor.h"
#include <cmath>
namespace planner_execution {
double norm(const Vec3& v) { return std::sqrt(v[0]*v[0]+v[1]*v[1]+v[2]*v[2]); }
double distance(const Vec3& a, const Vec3& b) { return norm({a[0]-b[0],a[1]-b[1],a[2]-b[2]}); }
void SettleMonitor::reset() { previous_ = State{}; since_ = -1; held_ = 0; }
bool SettleMonitor::update(const State& s, const Config& c, const Target* target) {
  if (!previous_.valid) { previous_ = s; return false; }
  const double dt = s.stamp - previous_.stamp;
  if (dt == 0) return false;
  const double acceleration = dt > 0 ? distance(s.velocity, previous_.velocity)/dt : INFINITY;
  previous_ = s;
  bool ok = dt > 0 && dt <= c.state_timeout_s && norm(s.velocity) <= c.settle_speed_m_s &&
      acceleration <= c.settle_acceleration_m_s2 && std::abs(s.yaw_rate) <= c.settle_yaw_rate_rad_s;
  if (target) {
    const double yaw_error = target->yaw_path==1 ? target->yaw-s.yaw :
        std::atan2(std::sin(target->yaw-s.yaw), std::cos(target->yaw-s.yaw));
    ok = ok && distance(s.position, target->waypoints.back()) <= c.settle_position_m &&
      (target->look_forward || std::abs(yaw_error) <= c.settle_yaw_deg*std::acos(-1.0)/180.0);
  }
  if (!ok) { since_ = -1; held_ = 0; return false; }
  if (since_ < 0) since_ = s.stamp;
  held_ = s.stamp-since_;
  return held_ >= c.settle_hold_s;
}
}
