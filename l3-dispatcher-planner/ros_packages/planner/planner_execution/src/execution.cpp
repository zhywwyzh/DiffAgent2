#include "planner_execution/execution.h"
#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <utility>
namespace planner_execution {
void Config::validate() const {
  for (double v : {state_timeout_s, action_timeout_s, stop_timeout_s, settle_position_m,
      settle_speed_m_s, settle_acceleration_m_s2, settle_yaw_rate_rad_s, settle_hold_s, settle_yaw_deg})
    if (!std::isfinite(v) || v <= 0) throw std::invalid_argument("invalid_execution_limit");
  if (world_frame.empty() || !std::isfinite(min_height) || !std::isfinite(max_height) ||
      min_height > max_height || settle_yaw_deg >= 90 || (!std::isnan(ground_z) && !std::isfinite(ground_z)))
    throw std::invalid_argument("invalid_execution_config");
}
WaypointExecution::WaypointExecution(Config c, Backend b): config_(std::move(c)), backend_(std::move(b)) {
  config_.validate();
}
bool WaypointExecution::fresh(double now) const {
  const double age = now-state_.received;
  return state_.valid && state_.frame == config_.world_frame && age >= 0 && age <= config_.state_timeout_s &&
      state_.source_age >= 0 && state_.source_age+age <= config_.state_timeout_s;
}
std::string WaypointExecution::admission(const Target& t, double now) const {
  if (!ready()) return "execution_not_ready";
  if (!fresh(now)) return "odometry_unavailable";
  if (t.frame != config_.world_frame || t.waypoints.empty() || t.waypoints.size()>3 || !std::isfinite(t.yaw))
    return "invalid_goal";
  if (t.yaw_mode>2 || t.yaw_path>1) return "invalid_yaw_policy";
  if (t.ground_approach && !std::isfinite(config_.ground_z)) return "ground_height_unconfigured";
  const double floor = t.ground_approach ? config_.ground_z : config_.min_height;
  for (auto p:t.waypoints) {
    for (double v:p) if (!std::isfinite(v)) return "invalid_goal";
    if (p[2]<floor || p[2]>config_.max_height) return "goal_height_out_of_bounds";
  }
  return backend_.validate(t);
}
void WaypointExecution::start(const Target& t, double now) {
  target_=t; progress_=Progress{}; result_.reset(); settle_.reset(); previous_=state_;
  continuous_yaw_=state_.yaw;
  active_=true; cancelled_=false; hold_confirmed_=false; started_=now; phase_="executing";
  try { if (!backend_.start(t)) fail("planner_rejected_goal",now); }
  catch (...) { fail("planner_start_failed",now); }
}
void WaypointExecution::observe(const State& s) { state_=s; }
void WaypointExecution::progress(const Progress& p) {
  if (active_ && phase_!="stopping") progress_=p;
}
void WaypointExecution::begin_stop(const std::string& reason, bool cancelled, double now) {
  if (phase_=="stopping") {
    stopping_=std::min(stopping_,now);
    if (cancelled) { cancelled_=true; reason_="cancelled"; }
    return;
  }
  reason_=reason; cancelled_=cancelled; phase_="stopping"; stopping_=now;
  stop_started_=false; hold_confirmed_=false; settle_.reset();
  ++recovery_generation_;
  // 立即尝试；定时推进仅在接管未完成时重试。
  try { stop_started_=backend_.stop(); } catch (...) { stop_started_=false; }
  target_=Target{}; progress_=Progress{};
}
void WaypointExecution::fail(const std::string& reason,double now) { begin_stop(reason,false,now); }
void WaypointExecution::cancel(double now) { if (active_) { if (phase_=="stopping") ++recovery_generation_; begin_stop("cancelled",true,now); } }
void WaypointExecution::request_stop(double now) { if (phase_=="stopping") ++recovery_generation_; begin_stop("safety_stop",false,now); }
void WaypointExecution::finish(Result::Status status,bool stopped) {
  if (active_) result_=Result{status, reason_, stopped, state_};
  active_=false; hold_confirmed_=stopped; phase_=stopped ? "ready" : "fault";
}
void WaypointExecution::tick(double now) {
  if (phase_=="bootstrapping") {
    if (!fresh(now)) return;
    begin_stop("startup_hold",false,now);
  }
  if (phase_=="fault") return;
  if (phase_=="ready") {
    if (!fresh(now)) { phase_="fault"; hold_confirmed_=false; }
    return;
  }
  if (phase_=="stopping") {
    if (now-stopping_ >= config_.stop_timeout_s) { reason_ += ":stop_timeout"; finish(Result::Status::Aborted,false); return; }
    // 接管回执需要持续有效，尤其是独立跟踪进程可能在停稳窗口中掉线。
    try { stop_started_=backend_.stop(); } catch (...) { stop_started_=false; }
    if (!stop_started_) { settle_.reset(); return; }
    if (!fresh(now)) { settle_.reset(); return; }
    if (settle_.update(state_,config_,nullptr))
      finish(cancelled_ ? Result::Status::Cancelled : Result::Status::Aborted,true);
    return;
  }
  if (!fresh(now)) { fail("odometry_unavailable",now); return; }
  const double dt=state_.stamp-previous_.stamp;
  if (dt<0 || dt>config_.state_timeout_s) { fail("odometry_discontinuous",now); return; }
  if (dt>0) {
    if (target_.yaw_path==1 && std::max(std::abs(state_.yaw_rate),std::abs(previous_.yaw_rate))*dt>=std::acos(-1.0)) {
      fail("yaw_observation_ambiguous",now); return;
    }
    continuous_yaw_ += std::atan2(std::sin(state_.yaw-previous_.yaw),std::cos(state_.yaw-previous_.yaw));
  }
  previous_=state_;
  if (progress_.skipped_mask) { fail("waypoint_skipped",now); return; }
  if (now-started_>=config_.action_timeout_s) { fail("action_timeout",now); return; }
  if (!progress_.all_consumed) return;
  phase_="settling";
  State observation=state_;
  if (target_.yaw_path==1) observation.yaw=continuous_yaw_;
  if (settle_.update(observation,config_,&target_)) { reason_="goal_reached"; finish(Result::Status::Succeeded,true); }
}
std::optional<Result> WaypointExecution::take_result() { auto r=result_; result_.reset(); return r; }
}
