#pragma once
#include <array>
#include <functional>
#include <string>
#include <vector>
#include <limits>

namespace planner_execution {
using Vec3 = std::array<double, 3>;
struct Target {
  std::vector<Vec3> waypoints;
  std::string frame;
  double yaw{0};
  bool look_forward{true}, ground_approach{false};
  unsigned yaw_mode{0}, yaw_path{0};
};
struct State {
  Vec3 position{}, velocity{};
  double yaw{0}, yaw_rate{0}, stamp{0}, received{0}, source_age{0};
  std::string frame;
  bool valid{false};
};
struct Config {
  std::string world_frame{"world"};
  double min_height{0.3}, max_height{3.0}, ground_z{std::numeric_limits<double>::quiet_NaN()};
  double state_timeout_s{1}, action_timeout_s{60}, stop_timeout_s{5};
  double settle_position_m{0.3}, settle_speed_m_s{0.15}, settle_acceleration_m_s2{0.3};
  double settle_yaw_rate_rad_s{0.2}, settle_hold_s{0.2}, settle_yaw_deg{10};
  void validate() const;
};
struct Progress {
  bool all_consumed{false};
  unsigned active_index{0}, consumed_count{0}, skipped_mask{0};
};
struct Result {
  enum class Status { Succeeded, Aborted, Cancelled } status;
  std::string reason;
  bool stop_confirmed;
  State state;
};
struct Backend {
  std::function<std::string(const Target&)> validate;
  std::function<bool(const Target&)> start;
  // True only after the old trajectory is retired and holding has taken over.
  std::function<bool()> stop;
  std::function<void()> commit;
};
double norm(const Vec3& value);
double distance(const Vec3& a, const Vec3& b);
}
