#include <elastic_tracker/tracking_ros.h>
#include <stdexcept>
namespace elastic_tracker {
TrackingRos::TrackingRos(ros::NodeHandle nh,MapPort map,planner_execution::WaypointActionServer& execution)
    :nh_(nh),execution_(execution),output_(execution.output()) {
  nh_.setCallbackQueue(&queue_);
  AlgorithmConfig c; ros::NodeHandle params("/elastic_tracker");
#define PARAM(key) params.param(#key,c.key,c.key)
  PARAM(samples); PARAM(max_speed_m_s); PARAM(max_acceleration_m_s2); PARAM(time_weight); PARAM(position_weight);
  PARAM(tracking_weight); PARAM(visibility_weight); PARAM(velocity_weight); PARAM(acceleration_weight);
  PARAM(horizon_s); PARAM(prediction_step_s); PARAM(clearance_m); PARAM(visibility_angle_rad);
  PARAM(prediction_acceleration_weight); PARAM(target_max_speed_m_s);
#undef PARAM
  double low=0.3,high=3.0;
  nh_.getParam("/planner_execution/min_height",low); nh_.getParam("/planner_execution/max_height",high);
  nh_.getParam("/planner_execution/world_frame",frame_);
  tracking_=std::make_unique<Tracking>(std::move(map),c,low,high);
  planner_execution::TrackingBackend backend;
  backend.start=[this](const planner_execution::TrackRequest& r){return tracking_->startTracking(r,ros::Time::now().toSec());};
  backend.observation=[this](const planner_execution::TrackObservation& o){tracking_->receiveObservation(o);};
  backend.tick=[this](double now){return tracking_->planTracking(now);};
  backend.feedback=[this](){return tracking_->getFeedback();};
  backend.commit=[this](uint64_t gen){tracking_->commitExecution(gen); running_=true;};
  backend.stop=[this](){running_=false; tracking_->stopTracking();};
  execution_.enableTracking(std::move(backend));
  std::string topic;
  nh_.param<std::string>("/planner_execution/odometry_topic",topic,"/ekf_quat/ekf_odom");
  pose_=nh_.subscribe(topic,40,&TrackingRos::pose,this);
  nh_.param<std::string>("/elastic_tracker/depth_topic",topic,"/camera/aligned_depth_to_color/image_raw");
  depth_=nh_.subscribe(topic,2,&TrackingRos::depth,this);
  timer_=nh_.createWallTimer(ros::WallDuration(0.01),&TrackingRos::sample,this);
  spinner_=std::make_unique<ros::AsyncSpinner>(3,&queue_); spinner_->start();
}
TrackingRos::~TrackingRos() {shutdown();}
void TrackingRos::shutdown() {running_=false; timer_.stop(); spinner_->stop();}
void TrackingRos::pose(const nav_msgs::OdometryConstPtr& msg) {
  if(msg->header.frame_id!=frame_) return;
  const auto& p=msg->pose.pose.position; const auto& q=msg->pose.pose.orientation;
  tracking_->receivePose({msg->header.stamp.toSec(),{p.x,p.y,p.z},{q.w,q.x,q.y,q.z}});
}
void TrackingRos::depth(const sensor_msgs::ImageConstPtr& msg) {
  tracking_->receiveDepth({msg->header.stamp.toSec(),msg->width,msg->height,msg->step,bool(msg->is_bigendian),msg->encoding,msg->data});
}
void TrackingRos::sample(const ros::WallTimerEvent&) {
  if(!running_) return;
  auto sample=tracking_->sampleCommand(ros::Time::now().toSec());
  if(!sample) return;
  if(!sample->valid) { output_->requestStopIfCurrent(sample->generation); return; }
  quadrotor_msgs::PositionCommand cmd;
  cmd.header.stamp=ros::Time::now(); cmd.header.frame_id=frame_;
  cmd.position.x=sample->position[0]; cmd.position.y=sample->position[1]; cmd.position.z=sample->position[2];
  cmd.velocity.x=sample->velocity[0]; cmd.velocity.y=sample->velocity[1]; cmd.velocity.z=sample->velocity[2];
  cmd.acceleration.x=sample->acceleration[0]; cmd.acceleration.y=sample->acceleration[1]; cmd.acceleration.z=sample->acceleration[2];
  cmd.jerk.x=sample->jerk[0]; cmd.jerk.y=sample->jerk[1]; cmd.jerk.z=sample->jerk[2];
  cmd.yaw=sample->yaw; cmd.yaw_dot=sample->yaw_rate;
  cmd.yaw_control_mode=quadrotor_msgs::PositionCommand::YAW_CONTROL_TARGET;
  cmd.trajectory_flag=quadrotor_msgs::PositionCommand::TRAJECTORY_STATUS_READY;
  // 与同进程 EGO 保持相同的 PositionCommand 增益语义；本层不注入控制器增益。
  output_->publish(cmd,sample->generation);
}
}
