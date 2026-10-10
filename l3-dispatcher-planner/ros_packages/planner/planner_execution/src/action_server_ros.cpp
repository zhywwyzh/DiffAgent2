#include "planner_execution/action_server_ros.h"
#include <chrono>
#include <cmath>
#include <limits>
#include <stdexcept>
namespace planner_execution {
namespace {
Config read_config() {
  ros::NodeHandle p("/planner_execution"); Config c;
  if (!p.getParam("world_frame",c.world_frame)) throw std::runtime_error("missing planner_execution/world_frame");
#define PARAM(key) if (!p.getParam(#key,c.key)) throw std::runtime_error("missing planner_execution/" #key)
  PARAM(min_height); PARAM(max_height); p.getParam("ground_z",c.ground_z); PARAM(state_timeout_s);
  PARAM(action_timeout_s); PARAM(stop_timeout_s); PARAM(settle_position_m);
  PARAM(settle_speed_m_s); PARAM(settle_acceleration_m_s2); PARAM(settle_yaw_rate_rad_s);
  PARAM(settle_hold_s); PARAM(settle_yaw_deg);
#undef PARAM
  c.validate(); return c;
}
}
double WaypointActionServer::now() {
  return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
WaypointActionServer::WaypointActionServer(ros::NodeHandle nh, Backend backend, std::recursive_mutex& mutex, bool external_output, const std::string& command_topic)
    : nh_(nh), config_(read_config()), mutex_(mutex), execution_(config_,std::move(backend)),
      boot_id_(std::chrono::system_clock::now().time_since_epoch().count()) {
  nh_.setCallbackQueue(&queue_);
  output_=std::make_shared<CommandOutput>(nh,false,!external_output,command_topic);
  output_->set_boot(boot_id_);
  std::string topic;
  nh_.param<std::string>("/planner_execution/odometry_topic",topic,"/ekf_quat/ekf_odom");
  odometry_=nh_.subscribe(topic,20,&WaypointActionServer::odometry,this);
  readiness_=nh_.advertise<quadrotor_msgs::ExecutionState>("/planner/execution_state",1,true);
  emergency_stop_=nh_.subscribe<std_msgs::Empty>("/command/emergency_stop",1,
      [this](const std_msgs::EmptyConstPtr&){request_stop();});
  server_=std::make_unique<Server>(nh_,"/planner/execute_waypoints",
      [this](Handle h){ goal(h); },[this](Handle h){ cancel(h); },false);
  timer_=nh_.createWallTimer(ros::WallDuration(0.05),&WaypointActionServer::tick,this);
  spinner_=std::make_unique<ros::AsyncSpinner>(3,&queue_);
}
void WaypointActionServer::start() { server_->start(); spinner_->start(); }
WaypointActionServer::~WaypointActionServer() { output_->request_stop(); spinner_->stop(); timer_.stop(); }
void WaypointActionServer::goal(Handle h) {
  std::unique_lock<std::recursive_mutex> guard(mutex_,std::try_to_lock);
  if (!guard.owns_lock()) {
    quadrotor_msgs::ExecuteWaypointsResult result; result.reason="execution_busy";
    h.setRejected(result,"execution_busy"); return;
  }
  if (h.getGoalStatus().status == actionlib_msgs::GoalStatus::RECALLING) {
    quadrotor_msgs::ExecuteWaypointsResult r; r.reason="cancelled_before_execution";
    r.stop_confirmed=execution_.holding(); h.setCanceled(r); return;
  }
  const auto& msg=*h.getGoal(); Target target;
  target.frame=msg.header.frame_id; target.yaw=msg.target.yaw;
  target.look_forward=msg.target.look_forward;
  target.ground_approach=msg.target.ground_approach;
  target.yaw_mode=msg.target.yaw_policy.mode; target.yaw_path=msg.target.yaw_policy.path;
  for (const auto& p:msg.target.waypoints) target.waypoints.push_back({p.x,p.y,p.z});
  apply_stop();
  const std::string reason=active_ ? "execution_busy" :
      (!output_->enabled() && !output_->holding() ? "command_output_unavailable" : execution_.admission(target,now()));
  if (!reason.empty()) {
    quadrotor_msgs::ExecuteWaypointsResult r; r.reason=reason;
    r.stop_confirmed=execution_.holding(); h.setRejected(r,reason); return;
  }
  const auto epoch=output_->generation();
  {
    std::lock_guard<std::recursive_mutex> stop_guard(stop_mutex_);
    active_id_=h.getGoalID().id;
  }
  active_=h; h.setAccepted(); execution_.start(target,now());
  // 停止在规划期间到达时不得重新开启旧目标输出。
  if (execution_.phase()=="executing") {
    if (!output_->resume(epoch)) {
      if (!apply_stop()) execution_.cancel(now());
    }
    else execution_.commit();
  }
  publish_state();
}
void WaypointActionServer::cancel(Handle h) {
  {
    std::lock_guard<std::recursive_mutex> guard(stop_mutex_);
    if (h.getGoalID().id!=active_id_ || active_id_.empty()) return;
    pending_cancel_=true;
    request_stop();
  }
}
void WaypointActionServer::request_stop() {
  {
    std::lock_guard<std::recursive_mutex> guard(stop_mutex_);
    if (!pending_stop_) stop_requested_at_=now();
    pending_stop_=true;
    output_->request_stop();
  }
  // 输出屏障与首次保持已生效。后端数据清理不可绕过规划锁。
  std::unique_lock<std::recursive_mutex> guard(mutex_,std::try_to_lock);
  if (guard.owns_lock()) { apply_stop(); publish_state(); }
  else {
    quadrotor_msgs::ExecutionState state;
    state.header.stamp=ros::Time::now(); state.boot_id=boot_id_;
    state.execution_generation=output_->generation(); state.motion_enabled=false; state.phase="stopping";
    readiness_.publish(state);
  }
}
bool WaypointActionServer::apply_stop() {
  bool cancelled; double started;
  {
    std::lock_guard<std::recursive_mutex> guard(stop_mutex_);
    if (!pending_stop_) return false;
    cancelled=pending_cancel_; started=stop_requested_at_;
    pending_stop_=false; pending_cancel_=false;
  }
  if (cancelled) execution_.cancel(started);
  else execution_.request_stop(started);
  return true;
}
void WaypointActionServer::odometry(const nav_msgs::OdometryConstPtr& msg) {
  State s; const auto& p=msg->pose.pose.position; const auto& q=msg->pose.pose.orientation;
  const auto& v=msg->twist.twist.linear;
  const double n=q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w;
  s.position={p.x,p.y,p.z}; s.velocity={v.x,v.y,v.z};
  s.yaw=n>0 ? std::atan2(2*(q.w*q.z+q.x*q.y)/n,1-2*(q.y*q.y+q.z*q.z)/n) : NAN;
  s.yaw_rate=msg->twist.twist.angular.z; s.frame=msg->header.frame_id;
  s.stamp=msg->header.stamp.toSec(); s.received=now();
  s.source_age=(ros::Time::now()-msg->header.stamp).toSec();
  s.valid=std::isfinite(s.yaw) && std::isfinite(s.yaw_rate) && s.stamp>0 && std::isfinite(n);
  for (double x:s.position) s.valid=s.valid && std::isfinite(x);
  for (double x:s.velocity) s.valid=s.valid && std::isfinite(x);
  std::unique_lock<std::recursive_mutex> guard(mutex_,std::try_to_lock);
  if (guard.owns_lock()) execution_.observe(s);
}
void WaypointActionServer::progress(const Progress& p) {
  std::lock_guard<std::recursive_mutex> guard(mutex_); execution_.progress(p);
}
void WaypointActionServer::fail(const std::string& reason) {
  output_->request_stop();
  std::lock_guard<std::recursive_mutex> guard(mutex_); execution_.fail(reason,now());
}
void WaypointActionServer::tick(const ros::WallTimerEvent&) {
  std::unique_lock<std::recursive_mutex> guard(mutex_,std::try_to_lock);
  if (!guard.owns_lock()) return;
  apply_stop();
  if (execution_.ready() && !output_->enabled() && !output_->holding()) execution_.fail("command_output_unavailable",now());
  execution_.tick(now());
  if (auto result=execution_.take_result()) {
    if (active_) {
      quadrotor_msgs::ExecuteWaypointsResult r;
      r.reason=result->reason; r.stop_confirmed=result->stop_confirmed;
      r.state_valid=execution_.fresh(now());
      r.final_pose.header.frame_id=result->state.frame;
      if (r.state_valid) {
        r.final_pose.header.stamp.fromSec(result->state.stamp);
        auto& p=r.final_pose.pose.position;
        p.x=result->state.position[0]; p.y=result->state.position[1]; p.z=result->state.position[2];
        r.final_pose.pose.orientation.z=std::sin(result->state.yaw/2);
        r.final_pose.pose.orientation.w=std::cos(result->state.yaw/2);
      }
      switch (result->status) {
        case Result::Status::Succeeded: active_->setSucceeded(r); break;
        case Result::Status::Cancelled: active_->setCanceled(r); break;
        case Result::Status::Aborted: active_->setAborted(r); break;
      }
      active_.reset();
      std::lock_guard<std::recursive_mutex> stop_guard(stop_mutex_); active_id_.clear();
    }
  }
  if (active_ && !execution_.target().waypoints.empty()) {
    quadrotor_msgs::ExecuteWaypointsFeedback f;
    f.phase=execution_.phase(); f.active_index=execution_.progress().active_index;
    f.consumed_count=execution_.progress().consumed_count;
    const auto& s=execution_.state(); const auto& t=execution_.target();
    f.position_error_m=execution_.fresh(now()) ? distance(s.position,t.waypoints.back()) : NAN;
    f.yaw_error_rad=std::atan2(std::sin(t.yaw-s.yaw),std::cos(t.yaw-s.yaw));
    f.speed_m_s=norm(s.velocity); f.settled_s=execution_.settled();
    active_->publishFeedback(f);
  }
  publish_state();
}
void WaypointActionServer::publish_state() {
  quadrotor_msgs::ExecutionState state;
  state.header.stamp=ros::Time::now(); state.boot_id=boot_id_;
  state.recovery_generation=execution_.recovery_generation();
  std::lock_guard<std::recursive_mutex> stop_guard(stop_mutex_);
  state.ready=execution_.ready() && !pending_stop_;
  state.stop_confirmed=execution_.holding() && !pending_stop_;
  state.phase=pending_stop_ ? "stopping" : execution_.phase();
  state.execution_generation=output_->generation(); state.motion_enabled=output_->enabled();
  readiness_.publish(state);
}
}
