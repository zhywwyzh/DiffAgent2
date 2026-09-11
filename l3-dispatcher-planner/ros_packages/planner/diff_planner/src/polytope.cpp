#include <corridor_gen/polytope.h>
#include <corridor_gen/geometry_utils.h>
#include <ros/ros.h>

namespace corridor_gen {

Polytope::Polytope(const PlaneMat &planes) {
  planes_ = planes;
  undefined = false;
}

bool Polytope::empty() const { return undefined; }

bool Polytope::HaveSeedLine() const { return have_seed_line_; }

void Polytope::SetSeedLine(const Line &seed_line, double r) {
  robot_r = r;
  seed_line_ = seed_line;
  have_seed_line_ = true;
}

int Polytope::SurfNum() const { return undefined ? 0 : static_cast<int>(planes_.rows()); }

Polytope Polytope::CrossWith(const Polytope &b) const {
  PlaneMat curIH(SurfNum() + b.SurfNum(), 4);
  curIH << planes_, b.GetPlanes();
  Polytope out;
  out.SetPlanes(curIH);
  return out;
}

PlaneMat Polytope::GetPlanes() const { return planes_; }

void Polytope::Reset() {
  undefined = true;
  is_known_free = false;
  have_seed_line_ = false;
}

bool Polytope::IsKnownFree() { return !undefined && is_known_free; }

void Polytope::SetKnownFree(bool is_free) { is_known_free = is_free; }

void Polytope::SetPlanes(const PlaneMat &planes) {
  planes_ = planes;
  undefined = false;
}

void Polytope::SetEllipsoid(const Ellipsoid &ellip) { ellipsoid_ = ellip; }

bool Polytope::PointIsInside(const Eigen::Vector3d &pt, const double margin) const {
  if (undefined || planes_.rows() == 0) return false;
  Eigen::Vector4d pt_e;
  pt_e.head<3>() = pt;
  pt_e(3) = 1;
  return (planes_ * pt_e).maxCoeff() <= margin;
}

bool SimplifySFC(const Eigen::Vector3d &head_p, const Eigen::Vector3d &tail_p, PolytopeVec &sfcs) {
  const Eigen::Vector3d path_front = head_p;
  const Eigen::Vector3d path_back = tail_p;
  int start_id{-1}, end_id{-1};
  if (sfcs.size() > 2) {
    for (int i = 0; i < static_cast<int>(sfcs.size()); i++) {
      if (sfcs[i].PointIsInside(path_front)) {
        start_id = i;
      }
      if (sfcs[sfcs.size() - 1 - i].PointIsInside(path_back)) {
        end_id = static_cast<int>(sfcs.size() - 1 - i);
      }
    }
    if (start_id < 0 || end_id < 0) {
      if (start_id < 0)
        ROS_WARN("[corridor_gen] SimplifySFC: head (%.3f, %.3f, %.3f) not inside any polytope",
                 path_front.x(), path_front.y(), path_front.z());
      if (end_id < 0)
        ROS_WARN("[corridor_gen] SimplifySFC: tail (%.3f, %.3f, %.3f) not inside any polytope",
                 path_back.x(), path_back.y(), path_back.z());
      return false;
    }
    if (start_id >= end_id) {
      end_id = start_id;
    }
    PolytopeVec sfcs_new(sfcs.begin() + start_id, sfcs.begin() + end_id + 1);
    if (sfcs_new.size() > 2) {
      Polytope check_cand = sfcs_new[0], last_overlapped = sfcs_new[1];
      PolytopeVec sfcs_final;
      sfcs_final.push_back(sfcs_new[0]);
      for (int i = 2; i < static_cast<int>(sfcs_new.size()); i++) {
        Polytope cross_poly = check_cand.CrossWith(sfcs_new[i]);
        Eigen::Vector3d interior_pt;
        const bool is_overlapped = findInterior(cross_poly.GetPlanes(), interior_pt);
        if (is_overlapped) {
          last_overlapped = sfcs_new[i];
          if (last_overlapped.PointIsInside(path_back)) {
            sfcs_final.push_back(last_overlapped);
            break;
          }
        } else {
          sfcs_final.push_back(last_overlapped);
          check_cand = last_overlapped;
          i--;
        }
      }
      sfcs = sfcs_final;
    } else {
      sfcs = sfcs_new;
    }
  }
  return true;
}

}  // namespace corridor_gen
