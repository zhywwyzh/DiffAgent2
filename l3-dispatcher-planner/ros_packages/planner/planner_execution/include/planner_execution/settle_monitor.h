#pragma once
#include "planner_execution/execution_ports.h"
namespace planner_execution {
class SettleMonitor {
 public:
  void reset();
  bool update(const State& state, const Config& config, const Target* target);
  double held() const { return held_; }
 private:
  State previous_;
  double since_{-1}, held_{0};
};
}
