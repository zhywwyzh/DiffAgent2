#include <elastic_tracker/algorithm_config.h>
#pragma once



#include <Eigen/Core>
#include <iostream>
#include <queue>
#include <string>

namespace prediction {

struct Node {
  Eigen::Vector3d p, v, a;
  double t;
  double score;
  double h;
  Node* parent = nullptr;
};
typedef Node* NodePtr;
class NodeComparator {
 public:
  bool operator()(NodePtr& lhs, NodePtr& rhs) {
    return lhs->score + lhs->h > rhs->score + rhs->h;
  }
};
struct Predict {
 private:
  static constexpr int MAX_MEMORY = 1 << 16;
  // searching

  double dt;
  double pre_dur;
  double rho_a;
  double car_z, vmax;
  bool debug_search_ = false;
  double debug_throttle_ = 0.5;
  double last_debug_log_{0};
  std::vector<Node> storage;
  NodePtr data[MAX_MEMORY];
  int stack_top;

  inline bool isValid(const Eigen::Vector3d& p, const Eigen::Vector3d& v) const {
    return p.allFinite() && v.allFinite() && v.norm() < vmax;
  }

  inline bool debugDue() {
    if (!debug_search_) {
      return false;
    }
    const double now = elastic_tracker::monotonicSeconds();
    if (last_debug_log_ > 0 && (now - last_debug_log_) < debug_throttle_) {
      return false;
    }
    last_debug_log_ = now;
    return true;
  }

  inline void logFailure(const std::string& reason,
                         const Eigen::Vector3d& target_p,
                         const Eigen::Vector3d& target_v,
                         const NodePtr& curPtr,
                         const size_t open_set_size) {
    if (!debugDue()) {
      return;
    }
    std::cout << "[prediction][" << reason << "]"
              << " target_p=[" << target_p.transpose() << "]"
              << " target_v=[" << target_v.transpose() << "]"
              << " target_speed=" << target_v.norm()
              << " pre_dur=" << pre_dur
              << " dt=" << dt
              << " vmax=" << vmax
              << " stack_top=" << stack_top
              << " max_memory=" << MAX_MEMORY
              << " open_set=" << open_set_size;
    if (curPtr != nullptr) {
      std::cout << " current_p=[" << curPtr->p.transpose() << "]"
                << " current_v=[" << curPtr->v.transpose() << "]"
                << " current_t=" << curPtr->t
                << " current_speed=" << curPtr->v.norm();
    }
    std::cout << std::endl;
  }

 public:
  inline Predict(const elastic_tracker::AlgorithmConfig& config) : dt(config.prediction_step_s),
      pre_dur(config.horizon_s), rho_a(config.prediction_acceleration_weight), vmax(config.target_max_speed_m_s), storage(MAX_MEMORY) {
    for (int i = 0; i < MAX_MEMORY; ++i) {
      data[i] = &storage[i];
    }
  }
  Predict(const Predict&) = delete;
  Predict& operator=(const Predict&) = delete;

  inline bool predict(const Eigen::Vector3d& target_p,
                      const Eigen::Vector3d& target_v,
                      std::vector<Eigen::Vector3d>& target_predcit,
                      const double& max_time = 0.1) {
    auto score = [&](const NodePtr& ptr) -> double {
      return rho_a * ptr->a.norm();
    };
    Eigen::Vector3d end_p = target_p + target_v * pre_dur;
    auto calH = [&](const NodePtr& ptr) -> double {
      return 0.001 * (ptr->p - end_p).norm();
    };
    double t_start = elastic_tracker::monotonicSeconds();
    std::priority_queue<NodePtr, std::vector<NodePtr>, NodeComparator> open_set;

    Eigen::Vector3d input(0, 0, 0);

    stack_top = 0;
    NodePtr curPtr = data[stack_top++];
    curPtr->p = target_p;
    curPtr->v = target_v;
    curPtr->a.setZero();
    curPtr->parent = nullptr;
    curPtr->score = 0;
    curPtr->h = 0;
    curPtr->t = 0;
    double dt2_2 = dt * dt / 2;
    while (curPtr->t < pre_dur) {
      for (input.x() = -3; input.x() <= 3; input.x() += 3)
        for (input.y() = -3; input.y() <= 3; input.y() += 3) {
          Eigen::Vector3d p = curPtr->p + curPtr->v * dt + input * dt2_2;
          Eigen::Vector3d v = curPtr->v + input * dt;
          if (!isValid(p, v)) {
            continue;
          }
          if (stack_top == MAX_MEMORY) {
            logFailure("out_of_memory", target_p, target_v, curPtr, open_set.size());
            return false;
          }
          double t_cost = (elastic_tracker::monotonicSeconds() - t_start);
          if (t_cost > max_time) {
            logFailure("too_slow", target_p, target_v, curPtr, open_set.size());
            return false;
          }
          NodePtr ptr = data[stack_top++];
          ptr->p = p;
          ptr->v = v;
          ptr->a = input;
          ptr->parent = curPtr;
          ptr->t = curPtr->t + dt;
          ptr->score = curPtr->score + score(ptr);
          ptr->h = calH(ptr);
          open_set.push(ptr);
          // std::cout << "open set push: " << state.transpose() << std::endl;
        }
      if (open_set.empty()) {
        logFailure("no_way", target_p, target_v, curPtr, open_set.size());
        return false;
      }
      curPtr = open_set.top();
      open_set.pop();
    }
    target_predcit.clear();
    while (curPtr != nullptr) {
      target_predcit.push_back(curPtr->p);
      curPtr = curPtr->parent;
    }
    std::reverse(target_predcit.begin(), target_predcit.end());
    return true;
  }
};

}  // namespace prediction
