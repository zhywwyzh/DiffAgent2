#include "planner_execution/command_output_ros.h"
#include <cmath>
namespace planner_execution {
CommandOutput::CommandOutput(ros::NodeHandle nh, bool remote, bool publish, const std::string& command_topic)
    : nh_(nh), remote_(remote), publish_(publish) {
  nh_.setCallbackQueue(&queue_);
  std::string topic;
  nh_.param<std::string>("/planner_execution/odometry_topic",topic,"/ekf_quat/ekf_odom");
  nh_.param<std::string>("/planner_execution/world_frame",world_frame_,"world");
  nh_.param("/planner_execution/state_timeout_s",state_timeout_,1.0);
  if (publish_) publisher_=nh_.advertise<quadrotor_msgs::PositionCommand>(command_topic,1);
  if (remote_) confirmation_=nh_.advertise<quadrotor_msgs::CommandState>("/planner/command_state",1);
  if (!publish_) confirmation_sub_=nh_.subscribe<quadrotor_msgs::CommandState>("/planner/command_state",1,
      [this](const quadrotor_msgs::CommandStateConstPtr& msg) {
        std::lock_guard<std::mutex> lock(mutex_);
        confirmed_boot_=msg->boot_id; confirmed_generation_=msg->execution_generation;
        confirmed_hold_=msg->holding; confirmation_received_=ros::WallTime::now();
      });
  odometry_=nh_.subscribe(topic,1,&CommandOutput::odometry,this);
  // 原生 Action Cancel 通过服务端直接调用；外部跟踪进程也独立监听全局停止。
  if (remote_) {
    stop_=nh_.subscribe<std_msgs::Empty>("/command/emergency_stop",1,
      [this](const std_msgs::EmptyConstPtr&){request_stop();});
    state_=nh_.subscribe("/planner/execution_state",1,&CommandOutput::remote_state,this);
  }
  timer_=nh_.createWallTimer(ros::WallDuration(0.01),&CommandOutput::tick,this);
  spinner_=std::make_unique<ros::AsyncSpinner>(1,&queue_); spinner_->start();
}
CommandOutput::~CommandOutput() { spinner_->stop(); timer_.stop(); }
void CommandOutput::hold_locked() {
  if (!publish_) return;
  if (!hold_valid_ && have_pose_ && (ros::WallTime::now()-pose_received_).toSec()<=state_timeout_) {
    hold_=reference_;
    hold_.velocity=geometry_msgs::Vector3(); hold_.acceleration=geometry_msgs::Vector3();
    hold_.jerk=geometry_msgs::Vector3(); hold_.yaw_dot=0;
    hold_.yaw_control_mode=0;
    hold_.trajectory_flag=quadrotor_msgs::PositionCommand::TRAJECTORY_STATUS_READY;
    hold_valid_=true;
  }
  if (hold_valid_) { hold_.header.stamp=ros::Time::now(); publisher_.publish(hold_); hold_sent_=true; }
  if (remote_) {
    quadrotor_msgs::CommandState state; state.header.stamp=ros::Time::now();
    state.boot_id=boot_; state.execution_generation=generation_; state.holding=hold_sent_;
    confirmation_.publish(state);
  }
}
void CommandOutput::request_stop() {
  std::lock_guard<std::mutex> lock(mutex_);
  // 每次接收增加输出代次，防止已在计算的旧 cmd 获得发送权；不改变停止期限。
  ++generation_;
  if (remote_) remote_stop_generation_=generation_-1;
  blocked_=true; hold_locked();
}
bool CommandOutput::requestStopIfCurrent(uint64_t generation) {
  std::lock_guard<std::mutex> lock(mutex_);
  if(blocked_ || generation_!=generation) return false;
  ++generation_; blocked_=true; hold_locked(); return true;
}
bool CommandOutput::resume(uint64_t expected) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (generation_!=expected) return false;
  ++generation_; blocked_=false; hold_valid_=false; hold_sent_=false; return true;
}
uint64_t CommandOutput::generation() const { std::lock_guard<std::mutex> lock(mutex_); return generation_; }
bool CommandOutput::enabled() const { std::lock_guard<std::mutex> lock(mutex_); return !blocked_; }
bool CommandOutput::holding() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return blocked_ && (publish_ ? hold_sent_ : confirmed_hold_ && confirmed_boot_==boot_ &&
      confirmed_generation_==generation_ && (ros::WallTime::now()-confirmation_received_).toSec()<=state_timeout_);
}
void CommandOutput::set_gains(const std::array<double,3>& kx,const std::array<double,3>& kv) {
  std::lock_guard<std::mutex> lock(mutex_);
  for (int i=0;i<3;++i) { reference_.kx[i]=kx[i]; reference_.kv[i]=kv[i]; hold_.kx[i]=kx[i]; hold_.kv[i]=kv[i]; }
}
bool CommandOutput::obsolete(uint64_t boot,uint64_t generation) const {
  std::lock_guard<std::mutex> lock(mutex_);
  return boot==boot_ && (generation<generation_ || (blocked_ && generation==generation_));
}
void CommandOutput::set_boot(uint64_t boot) { std::lock_guard<std::mutex> lock(mutex_); boot_=boot; }
bool CommandOutput::deliver(uint64_t generation,const std::function<void()>& send) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (blocked_ || generation!=generation_) return false;
  send(); return true;
}
bool CommandOutput::matches(uint64_t boot,uint64_t generation) const {
  std::lock_guard<std::mutex> lock(mutex_);
  return !blocked_ && boot==boot_ && generation==generation_ &&
      (!remote_ || (ros::WallTime::now()-last_state_).toSec()<=state_timeout_);
}
bool CommandOutput::publish(const quadrotor_msgs::PositionCommand& cmd,uint64_t generation,uint64_t boot) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (blocked_ || generation!=generation_ || (remote_ && (boot!=boot_ ||
      (ros::WallTime::now()-last_state_).toSec()>state_timeout_))) return false;
  // 锁覆盖最终 publish，停止标志设置后不会再交付旧运动 cmd。
  for (int i=0;i<3;++i) { reference_.kx[i]=cmd.kx[i]; reference_.kv[i]=cmd.kv[i]; }
  publisher_.publish(cmd); return true;
}
void CommandOutput::odometry(const nav_msgs::OdometryConstPtr& msg) {
  const auto& p=msg->pose.pose.position; const auto& q=msg->pose.pose.orientation;
  const double n=q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w;
  const double age=(ros::Time::now()-msg->header.stamp).toSec();
  if (msg->header.frame_id!=world_frame_ || !std::isfinite(n) || n<=0 ||
      !std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z) ||
      msg->header.stamp.isZero() || age<0 || age>state_timeout_) return;
  std::lock_guard<std::mutex> lock(mutex_);
  reference_.header.frame_id=world_frame_; reference_.position=p;
  reference_.yaw=std::atan2(2*(q.w*q.z+q.x*q.y)/n,1-2*(q.y*q.y+q.z*q.z)/n);
  pose_received_=ros::WallTime::now(); have_pose_=true;
  if (blocked_) hold_locked();
}
void CommandOutput::remote_state(const quadrotor_msgs::ExecutionStateConstPtr& msg) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (boot_==msg->boot_id && msg->execution_generation<generation_) return;
  const bool new_boot=boot_!=msg->boot_id;
  if (new_boot) { blocked_=true; hold_valid_=false; remote_stop_generation_=0; }
  boot_=msg->boot_id; generation_=msg->execution_generation; last_state_=ros::WallTime::now();
  if (!msg->motion_enabled) { blocked_=true; hold_locked(); }
  else if (new_boot || generation_>remote_stop_generation_) { blocked_=false; hold_valid_=false; hold_sent_=false; }
}
void CommandOutput::tick(const ros::WallTimerEvent&) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (remote_ && !blocked_ && (ros::WallTime::now()-last_state_).toSec()>state_timeout_) {
    blocked_=true; remote_stop_generation_=generation_;
  }
  if (blocked_) hold_locked();
}
}
