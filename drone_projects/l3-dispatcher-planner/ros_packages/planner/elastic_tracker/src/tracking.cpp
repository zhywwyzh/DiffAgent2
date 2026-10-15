#include <elastic_tracker/tracking.h>
#include <elastic_tracker/target_estimator.h>
#include <planning/env/env.hpp>
#include <planning/prediction/prediction.hpp>
#include <planning/traj_opt/traj_opt.h>
#include <mutex>
#include <deque>
#include <optional>
#include <atomic>
#include <stdexcept>
namespace elastic_tracker {
namespace {
planner_execution::Vec3 array(const Eigen::Vector3d& v) { return {v.x(),v.y(),v.z()}; }
}
struct Tracking::Impl {
  MapReader read_map;
  std::string frame;
  AlgorithmConfig config;
  double floor, ceiling;
  std::unique_ptr<env::Env> environment;
  std::unique_ptr<prediction::Predict> prediction;
  std::unique_ptr<traj_opt::TrajOpt> optimizer;
  tracking::PoseHistory poses;
  tracking::TargetEstimator estimator;
  std::deque<Depth> depths;
  std::mutex sensors, commands;
  std::optional<Pose> latest_pose;
  std::optional<planner_execution::TrackObservation> pending;
  planner_execution::TrackRequest request;
  planner_execution::TrackFeedback feedback;
  std::shared_ptr<Trajectory> trajectory;
  Eigen::Vector3d hold_position{Eigen::Vector3d::Zero()}, target{Eigen::Vector3d::Zero()};
  double trajectory_stamp{0}, started{0}, last_plan{0}, yaw{0}, last_sample{0};
  uint64_t sequence{0}, generation{0}, map_epoch{0};
  bool active{false};
  std::atomic<bool> clock_reset{false};
  std::atomic<double> motion_until{0}, wall_motion_until{0}, map_until{0}, wall_map_until{0};
  Impl(MapReader reader,AlgorithmConfig configuration,double low,double high,std::string world):read_map(std::move(reader)),frame(std::move(world)),config(configuration),floor(low),ceiling(high) {
    if(config.samples<2 || config.samples>128 || !read_map || frame.empty() || !std::isfinite(floor) || !std::isfinite(ceiling) || floor>ceiling)
      throw std::invalid_argument("invalid_elastic_config");
    for(double value:{config.max_speed_m_s,config.max_acceleration_m_s2,config.time_weight,config.position_weight,
        config.tracking_weight,config.visibility_weight,config.velocity_weight,config.acceleration_weight,
        config.horizon_s,config.prediction_step_s,config.clearance_m,config.visibility_angle_rad,
        config.prediction_acceleration_weight,config.target_max_speed_m_s})
      if(!std::isfinite(value) || value<=0) throw std::invalid_argument("invalid_elastic_config");
    if(config.horizon_s/config.prediction_step_s<2 || config.horizon_s/config.prediction_step_s>100)
      throw std::invalid_argument("invalid_elastic_horizon");

  }
};
Tracking::Tracking(MapReader map,AlgorithmConfig config,double low,double high,std::string frame):impl_(new Impl(std::move(map),config,low,high,std::move(frame))) {}
Tracking::~Tracking()=default;
std::string Tracking::startTracking(const planner_execution::TrackRequest& request,double now) {
  auto& implementation=*impl_;
  if (implementation.environment) implementation.environment->setMap({});
  const double read_started=monotonicSeconds();
  auto sourceNow=[&](){return now+monotonicSeconds()-read_started;};
  auto map=implementation.read_map();
  if (!map || map->frame!=implementation.frame || !map->fresh(sourceNow(),monotonicSeconds())) return "tracking_map_unavailable";
  {
    std::lock_guard<std::mutex> lock(implementation.sensors);
    if (!implementation.latest_pose || now-implementation.latest_pose->stamp<0 ||
        now-implementation.latest_pose->stamp>request.observation_timeout_s) return "tracking_odometry_unavailable";
    const auto& pose=*implementation.latest_pose;
    implementation.hold_position=pose.position;
    auto forward=pose.orientation*Eigen::Vector3d::UnitX();
    implementation.yaw=std::atan2(forward.y(),forward.x());
  }
  implementation.map_epoch=map->reset_epoch;
  implementation.map_until=std::min(map->source_time,map->fusion_time)+map->timeout_s;
  implementation.wall_map_until=map->fusion_monotonic+map->timeout_s;
  implementation.request=request; implementation.config.follow_distance_m=request.follow_distance_m;
  implementation.config.distance_tolerance_m=request.distance_tolerance_m;
  implementation.environment=std::make_unique<env::Env>(implementation.config,map);
  implementation.prediction=std::make_unique<prediction::Predict>(implementation.config);
  implementation.optimizer=std::make_unique<traj_opt::TrajOpt>(implementation.config);
  implementation.estimator.reset(); implementation.pending.reset(); implementation.feedback={}; implementation.sequence=0;
  implementation.clock_reset=false; implementation.started=monotonicSeconds(); implementation.last_plan=0;
  implementation.motion_until=now+request.observation_timeout_s;
  implementation.wall_motion_until=monotonicSeconds()+request.observation_timeout_s;
  std::lock_guard<std::mutex> lock(implementation.commands);
  implementation.active=false; implementation.trajectory.reset(); implementation.last_sample=now; implementation.target=implementation.hold_position;
  return "";
}
void Tracking::commitExecution(uint64_t generation) {
  auto& implementation=*impl_; std::lock_guard<std::mutex> lock(implementation.commands);
  implementation.generation=generation; implementation.active=true;
}
void Tracking::stopTracking() {
  auto& implementation=*impl_; std::lock_guard<std::mutex> lock(implementation.commands);
  implementation.active=false; implementation.trajectory.reset(); implementation.pending.reset(); implementation.feedback.valid=false;
}
void Tracking::receivePose(const Pose& pose) {
  auto& implementation=*impl_; std::lock_guard<std::mutex> lock(implementation.sensors);
  if (!pose.position.allFinite() || !pose.orientation.coeffs().allFinite() || pose.orientation.norm()<1e-9 || !std::isfinite(pose.stamp)) return;
  if (implementation.latest_pose && pose.stamp<implementation.latest_pose->stamp) implementation.clock_reset=true;
  implementation.poses.add({pose.stamp,pose.position,pose.orientation}); implementation.latest_pose=Pose{pose.stamp,pose.position,pose.orientation.normalized()};
}
void Tracking::receiveDepth(Depth value) {
  auto& implementation=*impl_; std::lock_guard<std::mutex> lock(implementation.sensors);
  if (!implementation.depths.empty() && value.stamp<implementation.depths.back().stamp) {implementation.depths.clear(); implementation.clock_reset=true;}
  implementation.depths.push_back(std::move(value));
  while (implementation.depths.size()>32 || (!implementation.depths.empty() && implementation.depths.back().stamp-implementation.depths.front().stamp>1)) implementation.depths.pop_front();
}
void Tracking::receiveObservation(const planner_execution::TrackObservation& value) {
  auto& implementation=*impl_;
  if (value.session_id!=implementation.request.session_id || value.execution_id!=implementation.request.execution_id || value.sequence<=implementation.sequence ||
      !std::isfinite(value.stamp) || value.stamp<=0 || value.stamp<=implementation.estimator.observationStamp()) return;
  for(double x:value.bbox) if(!std::isfinite(x)) return;
  for(double x:value.intrinsics) if(!std::isfinite(x)) return;
  for(double x:value.translation) if(!std::isfinite(x)) return;
  const auto& b=value.bbox;
  if (b[0]<0 || b[1]<0 || b[2]<=b[0] || b[3]<=b[1] || b[2]>value.width || b[3]>value.height ||
      value.intrinsics[0]<=0 || value.intrinsics[1]<=0) return;
  Eigen::Matrix3d rotation=Eigen::Map<const Eigen::Matrix<double,3,3,Eigen::RowMajor>>(value.rotation.data());
  if (!rotation.allFinite() || (rotation.transpose()*rotation-Eigen::Matrix3d::Identity()).norm()>1e-5 ||
      std::abs(rotation.determinant()-1)>1e-5) return;
  implementation.sequence=value.sequence; implementation.pending=value;
}
std::string Tracking::planTracking(double now) {
  auto& implementation=*impl_;
  if (implementation.clock_reset) return "tracking_clock_reset";
  if (implementation.environment) implementation.environment->setMap({});
  const double read_started=monotonicSeconds();
  auto sourceNow=[&](){return now+monotonicSeconds()-read_started;};
  auto map=implementation.read_map();
  if (!map || map->frame!=implementation.frame || !map->fresh(sourceNow(),monotonicSeconds())) return "tracking_map_unavailable";
  if (map->reset_epoch!=implementation.map_epoch) return "tracking_map_reset";
  implementation.map_until=std::min(map->source_time,map->fusion_time)+map->timeout_s;
  implementation.wall_map_until=map->fusion_monotonic+map->timeout_s;
  if (implementation.pending) {
    const auto b=*implementation.pending;
    if (now-b.stamp<0 || now-b.stamp>implementation.request.observation_timeout_s) implementation.pending.reset();
    else {
      tracking::PoseSample pose;
      std::optional<Depth> depth;
      {
        std::lock_guard<std::mutex> lock(implementation.sensors);
        if (implementation.poses.at(b.stamp,pose)) {
          double delta=0.04;
          for (const auto& candidate:implementation.depths) {
            double gap=std::abs(candidate.stamp-b.stamp);
            if(candidate.width==b.width && candidate.height==b.height && gap<=delta) {delta=gap; depth=candidate;}
          }
        }
      }
      if (depth) {
        double z; Eigen::Vector3d point;
        Eigen::Matrix3d rotation=Eigen::Map<const Eigen::Matrix<double,3,3,Eigen::RowMajor>>(b.rotation.data());
        Eigen::Vector3d translation(b.translation[0],b.translation[1],b.translation[2]);
        if (tracking::bboxDepth(*depth,b.bbox,z) && tracking::projectWithDepth((b.bbox[0]+b.bbox[2])*0.5,
            (b.bbox[1]+b.bbox[3])*0.5,b.intrinsics[0],b.intrinsics[1],b.intrinsics[2],b.intrinsics[3],
            rotation,translation,pose,z,implementation.request.target_height_m,point) && implementation.estimator.update(point,b.stamp)) {
          implementation.feedback.sequence=b.sequence;
          implementation.motion_until=b.stamp+implementation.request.observation_timeout_s;
          implementation.wall_motion_until=monotonicSeconds()+implementation.request.observation_timeout_s-(now-b.stamp);
          implementation.pending.reset();
        }
      }
    }
  }
  Eigen::Vector3d target,velocity;
  implementation.feedback.valid=implementation.estimator.estimate(now,target,velocity) &&
      now-implementation.estimator.observationStamp()>=0 && now-implementation.estimator.observationStamp()<=implementation.request.observation_timeout_s;
  implementation.feedback.stamp=std::max(0.0,implementation.estimator.observationStamp());
  if (!implementation.feedback.valid) {
    if (monotonicSeconds()-implementation.started>implementation.request.observation_timeout_s) return "track_observation_lost";
    return "";
  }
  implementation.feedback.position=array(target); implementation.feedback.velocity=array(velocity);
  if (now-implementation.last_plan<0.1) return "";
  implementation.last_plan=now;
  Eigen::MatrixXd initial=Eigen::MatrixXd::Zero(3,3);
  {
    std::lock_guard<std::mutex> lock(implementation.commands);
    implementation.target=target;
    if(implementation.trajectory && now>=implementation.trajectory_stamp && now-implementation.trajectory_stamp<implementation.trajectory->getTotalDuration()) {
      const double t=now-implementation.trajectory_stamp;
      initial.col(0)=implementation.trajectory->getPos(t); initial.col(1)=implementation.trajectory->getVel(t); initial.col(2)=implementation.trajectory->getAcc(t);
    } else {
      std::lock_guard<std::mutex> sensor_lock(implementation.sensors);
      initial.col(0)=implementation.latest_pose->position;
    }
  }
  implementation.environment->setMap(map);
  std::vector<Eigen::Vector3d> predicted,path,waypoints,visible;
  std::vector<double> angles;
  if(!implementation.prediction->predict(target,velocity,predicted) || predicted.size()<2 ||
      !implementation.environment->findVisiblePath(initial.col(0),predicted,waypoints,path) || waypoints.size()!=predicted.size()) return "track_unreachable";
  predicted.pop_back(); waypoints.pop_back();
  implementation.environment->generate_visible_regions(predicted,waypoints,visible,angles);
  waypoints.insert(waypoints.begin(),initial.col(0)); implementation.environment->pts2path(waypoints,path);
  if(path.size()<2) return "track_unreachable";
  std::vector<Eigen::MatrixXd> corridors;
  std::vector<std::pair<Eigen::Vector3d,Eigen::Vector3d>> segments;
  implementation.environment->generateSFC(path,2.0,corridors,segments);
  if(corridors.empty()) return "track_unreachable";
  Eigen::MatrixXd final=Eigen::MatrixXd::Zero(3,3); final.col(0)=path.back(); final.col(1)=velocity;
  auto trajectory=std::make_shared<Trajectory>();
  if(!implementation.optimizer->generate_traj(initial,final,predicted,visible,angles,corridors,*trajectory)) return "track_unreachable";
  const double duration=trajectory->getTotalDuration();
  if(!std::isfinite(duration) || duration<=0) return "track_invalid_trajectory";
  const double step=std::min(0.02,map->resolution/(2*implementation.config.max_speed_m_s));
  auto latest=implementation.read_map();
  if (!latest || latest->frame!=implementation.frame || latest->reset_epoch!=map->reset_epoch ||
      !latest->fresh(sourceNow(),monotonicSeconds()) || !map->fresh(sourceNow(),monotonicSeconds())) return "tracking_map_changed";
  Eigen::Vector3d previous=trajectory->getPos(0);
  for(double t=0;;t=std::min(t+step,duration)) {
    const Eigen::Vector3d position=trajectory->getPos(t), velocity=trajectory->getVel(t), acceleration=trajectory->getAcc(t);
    if(!position.allFinite() || !velocity.allFinite() || !acceleration.allFinite() ||
        velocity.norm()>implementation.config.max_speed_m_s || acceleration.norm()>implementation.config.max_acceleration_m_s2)
      return "track_invalid_trajectory";
    if(position.z()<implementation.floor || position.z()>implementation.ceiling || !map->flightFree(position)) return "track_trajectory_collision";
    if(!latest->flightFree(position) || !map->clearSegment(previous,position) ||
        !latest->clearSegment(previous,position)) return "track_trajectory_collision";
    previous=position;
    if(t==duration) break;
  }
  if (!latest->fresh(sourceNow(),monotonicSeconds())) return "tracking_map_stale";
  {
    std::lock_guard<std::mutex> lock(implementation.commands);
    implementation.map_until=std::min(latest->source_time,latest->fusion_time)+latest->timeout_s;
    implementation.wall_map_until=latest->fusion_monotonic+latest->timeout_s;
    implementation.trajectory=std::move(trajectory); implementation.trajectory_stamp=now;
  }
  return "";
}
planner_execution::TrackFeedback Tracking::getFeedback() const {return impl_->feedback;}
std::optional<Command> Tracking::sampleCommand(double now) {
  auto& implementation=*impl_; std::lock_guard<std::mutex> lock(implementation.commands);
  if(!implementation.active) return {};
  Command command{}; command.generation=implementation.generation;
  if(!std::isfinite(now) || now>implementation.motion_until ||
      monotonicSeconds()>implementation.wall_motion_until || now>implementation.map_until ||
      monotonicSeconds()>implementation.wall_map_until || implementation.clock_reset) { command.valid=false; return command; }
  Eigen::Vector3d p=implementation.hold_position;
  if(implementation.trajectory) {
    double t=now-implementation.trajectory_stamp;
    if(t<0 || t>implementation.trajectory->getTotalDuration()) { command.valid=false; return command; }
    p=implementation.trajectory->getPos(t); command.velocity=array(implementation.trajectory->getVel(t));
    command.acceleration=array(implementation.trajectory->getAcc(t)); command.jerk=array(implementation.trajectory->getJer(t));
  }
  command.position=array(p);
  Eigen::Vector3d delta=implementation.target-p;
  const double desired=delta.head<2>().norm()>0.001 ? std::atan2(delta.y(),delta.x()) : implementation.yaw;
  const double dt=now-implementation.last_sample;
  if(dt<0 || dt>1) { command.valid=false; return command; }
  const double change=std::clamp(std::remainder(desired-implementation.yaw,2*M_PI),-0.6*dt,0.6*dt);
  implementation.yaw+=change; command.yaw=implementation.yaw; command.yaw_rate=dt>0 ? change/dt : 0; implementation.last_sample=now;
  return command;
}
}
