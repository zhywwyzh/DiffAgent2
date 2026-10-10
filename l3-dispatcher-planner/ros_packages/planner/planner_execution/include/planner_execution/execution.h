#pragma once
#include "planner_execution/settle_monitor.h"
#include <optional>
namespace planner_execution {
class WaypointExecution {
 public:
  WaypointExecution(Config config, Backend backend);
  std::string admission(const Target& target, double now) const;
  void start(const Target& target, double now);
  void startContinuous(double duration, double now);
  void observe(const State& state);
  void commit() { if (backend_.commit) backend_.commit(); }
  void progress(const Progress& progress);
  void fail(const std::string& reason, double now);
  void cancel(double now);
  void request_stop(double now);
  void tick(double now);
  std::optional<Result> take_result();
  bool ready() const { return phase_ == "ready"; }
  unsigned long long recovery_generation() const { return recovery_generation_; }
  bool holding() const { return hold_confirmed_; }
  std::string phase() const { return phase_; }
  const State& state() const { return state_; }
  const Target& target() const { return target_; }
  const Progress& progress() const { return progress_; }
  double settled() const { return settle_.held(); }
  bool fresh(double now) const;
 private:
  void begin_stop(const std::string& reason, bool cancelled, double now);
  void finish(Result::Status status, bool stopped);
  Config config_;
  Backend backend_;
  Target target_;
  State state_, previous_;
  Progress progress_;
  SettleMonitor settle_;
  std::optional<Result> result_;
  std::string phase_{"bootstrapping"}, reason_;
  bool continuous_{false}, completing_{false};
  double duration_{0};
  bool active_{false}, cancelled_{false}, stop_started_{false}, hold_confirmed_{false};
  unsigned long long recovery_generation_{0};
  double started_{0}, stopping_{0}, continuous_yaw_{0};
};
}
