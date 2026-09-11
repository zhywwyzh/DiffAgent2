#pragma once

#include <corridor_gen/types.hpp>
#include <corridor_gen/ellipsoid.h>

namespace corridor_gen {

class Polytope {
  bool undefined{true};
  bool is_known_free{false};
  PlaneMat planes_;
  bool have_seed_line_{false};

 public:
  double overlap_depth_with_last_one{0};
  Eigen::Vector3d interior_pt_with_last_one{Eigen::Vector3d::Zero()};
  Ellipsoid ellipsoid_{};
  Line seed_line_{};
  double robot_r{0};

  Polytope() = default;
  explicit Polytope(const PlaneMat &planes);

  bool empty() const;
  bool HaveSeedLine() const;
  void SetSeedLine(const Line &seed_line, double r = 0);
  int SurfNum() const;
  Polytope CrossWith(const Polytope &b) const;
  PlaneMat GetPlanes() const;
  void Reset();
  bool IsKnownFree();
  void SetKnownFree(bool is_free);
  void SetPlanes(const PlaneMat &planes);
  void SetEllipsoid(const Ellipsoid &ellip);
  bool PointIsInside(const Eigen::Vector3d &pt, const double margin = 0.01) const;
};

using PolytopeVec = std::vector<Polytope>;

bool SimplifySFC(const Eigen::Vector3d &head_p, const Eigen::Vector3d &tail_p, PolytopeVec &sfcs);

}  // namespace corridor_gen
