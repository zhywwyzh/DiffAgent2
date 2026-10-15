#pragma once
#include <chrono>
namespace elastic_tracker {
inline double monotonicSeconds() {
  return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
struct AlgorithmConfig {
  int samples{16};
  double max_speed_m_s{1.5}, max_acceleration_m_s2{2.0};
  double time_weight{100}, position_weight{10000}, tracking_weight{1000}, visibility_weight{1000};
  double velocity_weight{1000}, acceleration_weight{1000};
  double horizon_s{2}, prediction_step_s{0.2}, clearance_m{0.2}, visibility_angle_rad{0.1};
  double prediction_acceleration_weight{1}, target_max_speed_m_s{4};
  double follow_distance_m{2.5}, distance_tolerance_m{0.3};
};
}
