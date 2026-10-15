#include <corridor_gen/corridor_generator.h>

#include <cmath>
#include <limits>

#include <plan_env/raycast.h>
#include <ros/ros.h>

namespace corridor_gen {

  CorridorGenerator::CorridorGenerator(const GridMap::Ptr &map_ptr, const double bound_dis,
                                       const double seed_line_max_dis,
                                       const double min_overlap_threshold, const double robot_r,
                                       const int iris_iter_num, bool use_unknown)
      : grid_map_(map_ptr),
        bound_dis_(bound_dis),
        seed_line_max_length_(seed_line_max_dis),
        min_overlap_threshold_(min_overlap_threshold),
        robot_r_(robot_r),
        iris_iter_num_(iris_iter_num),
        use_unknown_(use_unknown)
  {
    ciri_ = std::make_shared<CIRI>();
    ciri_->setupParams(robot_r, iris_iter_num);
  }

void CorridorGenerator::SetLineNeighborList(
    const std::vector<Eigen::Vector3i> &line_seed_neighbor_list) {
  line_seed_neighbor_list_ = line_seed_neighbor_list;
}

void CorridorGenerator::boundBoxByLocalMap(Eigen::Vector3d &box_min, Eigen::Vector3d &box_max) {
  box_min = box_min.cwiseMax(grid_map_->getLocalMapLowBound());
  box_max = box_max.cwiseMin(grid_map_->getLocalMapUpBound());
}

void CorridorGenerator::boxSearchCorridorObstacles(const Eigen::Vector3d &box_min,
                                                   const Eigen::Vector3d &box_max,
                                                   PointCloud &points,
                                                   std::vector<uint8_t> &point_is_unknown) {
  points.clear();
  point_is_unknown.clear();
  if (box_max.x() <= box_min.x() || box_max.y() <= box_min.y() || box_max.z() <= box_min.z())
    return;

  const double resolution_inv = 1.0 / grid_map_->getResolution();
  const int ix0 = static_cast<int>(std::floor(box_min.x() * resolution_inv));
  const int iy0 = static_cast<int>(std::floor(box_min.y() * resolution_inv));
  const int iz0 = static_cast<int>(std::floor(box_min.z() * resolution_inv));
  const int ix1 = static_cast<int>(std::floor(box_max.x() * resolution_inv));
  const int iy1 = static_cast<int>(std::floor(box_max.y() * resolution_inv));
  const int iz1 = static_cast<int>(std::floor(box_max.z() * resolution_inv));

  for (int ix = ix0; ix <= ix1; ++ix)
    for (int iy = iy0; iy <= iy1; ++iy)
      for (int iz = iz0; iz <= iz1; ++iz) {
        const Eigen::Vector3d pos = grid_map_->globalIdx2Pos(Eigen::Vector3i(ix, iy, iz));
        if (pos.x() < box_min.x() || pos.y() < box_min.y() || pos.z() < box_min.z() ||
            pos.x() > box_max.x() || pos.y() > box_max.y() || pos.z() > box_max.z())
          continue;

        if (use_unknown_ && grid_map_->isUnknown(pos))
        {
          points.push_back(pos);
          point_is_unknown.push_back(1);
        }
        else if (grid_map_->getOccupancy(pos) == 1)
        {
          points.push_back(pos);
          point_is_unknown.push_back(0);
        }
      }
}

bool CorridorGenerator::isLineFreeForCorridor(
    const Eigen::Vector3d &start_pt, const Eigen::Vector3d &end_pt, const double max_dis,
    const std::vector<Eigen::Vector3i> &neighbor_list) {
  if (start_pt.array().isNaN().any() || end_pt.array().isNaN().any())
    return false;

  const double resolution = grid_map_->getResolution();
  const auto isWorldPosFree = [&](const Eigen::Vector3d &pos) -> bool {
    if (grid_map_->isUnknown(pos))
      return false;
    if (neighbor_list.empty()) {
      return grid_map_->getOccupancy(pos) != 1;
    }
    const Eigen::Vector3i ray_id = grid_map_->pos2GlobalIdx(pos);
    for (const auto &nei : neighbor_list) {
      const Eigen::Vector3i shift_id = ray_id + nei;
      if (!grid_map_->isInsideBuffer(shift_id))
        continue;
      if (grid_map_->getOccupancy(grid_map_->globalIdx2Pos(shift_id)) == 1)
        return false;
    }
    return true;
  };

  RayCaster raycaster;
  const Eigen::Vector3d start_idx = start_pt / resolution;
  const Eigen::Vector3d end_idx = end_pt / resolution;
  if (!raycaster.setInput(start_idx, end_idx)) {
    return isWorldPosFree(start_pt) && isWorldPosFree(end_pt);
  }

  Eigen::Vector3d ray_idx;
  while (raycaster.step(ray_idx)) {
    const Eigen::Vector3d ray_w = (ray_idx + Eigen::Vector3d::Constant(0.5)) * resolution;
    if (max_dis > 0 && (ray_w - start_pt).norm() > max_dis)
      return false;
    if (!isWorldPosFree(ray_w))
      return false;
  }

  return isWorldPosFree(end_pt);
}

bool CorridorGenerator::SearchPolytopeOnPath(const std::vector<Eigen::Vector3d> &path,
                                             PolytopeVec &sfcs,
                                             Eigen::Vector3d &shifted_start_pt,
                                             const bool use_bigger_inflation) {
  sfcs.clear();
  if (path.empty()) return false;

  int first_id = 0;
  int second_id = 0;
  const int max_loop = 1000;
  int cnt_loop = 0;
  Polytope temp_poly, temp_poly_fix_p;
  Polytope overlap;
  Eigen::Vector3d interior_pt;
  double interior_depth = 0.0;

  while (first_id < static_cast<int>(path.size()) &&
         ((use_unknown_ &&
           (use_bigger_inflation
                ? grid_map_->getInflateOccupancyWithAllUnknownInfBigger(path[first_id]) > 0
                : grid_map_->getInflateOccupancyWithAllUnknownInf(path[first_id]) > 0)) ||
          (!use_unknown_ &&
           (use_bigger_inflation ? grid_map_->getBiggerInflateOccupancy(path[first_id]) > 0
                                 : grid_map_->getInflateOccupancy(path[first_id]) > 0))))
  {
    first_id++;
  }

  if (first_id != 0) {
    shifted_start_pt = path[first_id];
    const double dis = (path[first_id] - path[0]).norm() * 1.2;
    GenerateEmptyPolytope(path[0], dis, temp_poly);
    sfcs.emplace_back(temp_poly);
  }

  while (cnt_loop++ < max_loop) {
    second_id = first_id;
    for (int j = first_id + 1; j < static_cast<int>(path.size()); j++) {
      if (!isLineFreeForCorridor(path[first_id], path[j], seed_line_max_length_,
                                 line_seed_neighbor_list_)) {
        second_id = j - 1;
        if (second_id - 1 > first_id) second_id -= 1;
        break;
      }
      second_id = j;
    }

    if (second_id == first_id && second_id + 1 < static_cast<int>(path.size())) {
      second_id += 1;
    }

    const Line seed_line(path[first_id], path[second_id]);
    if ((path[first_id] - path[second_id]).norm() > seed_line_max_length_ * 1.5) {
      ROS_ERROR("[CorridorGenerator] seed line too long");
      return false;
    }
    if (!GeneratePolytopeFromLine(seed_line, temp_poly)) {
      ROS_WARN("[CorridorGenerator] GeneratePolytopeFromLine failed.");
      return false;
    }

    if (!sfcs.empty()) {
      overlap = sfcs.back().CrossWith(temp_poly);
      interior_depth = findInteriorDist(overlap.GetPlanes(), interior_pt);
      temp_poly.overlap_depth_with_last_one = interior_depth;
      temp_poly.interior_pt_with_last_one = interior_pt;
      if (interior_depth < min_overlap_threshold_) {
        if (!GeneratePolytopeFromPoint(path[first_id], temp_poly_fix_p)) {
          ROS_WARN("[CorridorGenerator] GeneratePolytopeFromPoint failed.");
          return false;
        }
        overlap = sfcs.back().CrossWith(temp_poly_fix_p);
        interior_depth = findInteriorDist(overlap.GetPlanes(), interior_pt);
        if (interior_depth <= 0.01) {
          ROS_WARN("[CorridorGenerator] corridor not continuous, overlap=%.3f", interior_depth);
          return false;
        }
        temp_poly_fix_p.overlap_depth_with_last_one = interior_depth;
        temp_poly_fix_p.interior_pt_with_last_one = interior_pt;
        sfcs.push_back(temp_poly_fix_p);
        overlap = sfcs.back().CrossWith(temp_poly);
        interior_depth = findInteriorDist(overlap.GetPlanes(), interior_pt);
        if (interior_depth <= 0.01) {
          ROS_WARN("[CorridorGenerator] corridor not continuous after bridge, overlap=%.3f",
                   interior_depth);
          return false;
        }
      } else {
        const int temp_id = static_cast<int>(sfcs.size()) - 2;
        if (temp_id > 0) {
          overlap = sfcs[temp_id].CrossWith(temp_poly);
          interior_depth = findInteriorDist(overlap.GetPlanes(), interior_pt);
          if (interior_depth > sfcs[temp_id + 1].overlap_depth_with_last_one * 0.25) {
            temp_poly.overlap_depth_with_last_one = interior_depth;
            temp_poly.interior_pt_with_last_one = interior_pt;
            sfcs.pop_back();
          }
        }
      }
    }

    sfcs.push_back(temp_poly);
    if (second_id == static_cast<int>(path.size()) - 1) break;
    first_id = second_id;
  }

  if (cnt_loop >= max_loop || sfcs.empty()) return false;
  return true;
}

void CorridorGenerator::getSeedBBox(const Eigen::Vector3d &p1, const Eigen::Vector3d &p2,
                                    Eigen::Vector3d &box_min, Eigen::Vector3d &box_max) {
  box_min = p1.cwiseMin(p2);
  box_max = p1.cwiseMax(p2);
  box_min -= Eigen::Vector3d(bound_dis_, bound_dis_, bound_dis_);
  box_max += Eigen::Vector3d(bound_dis_, bound_dis_, bound_dis_);
}

bool CorridorGenerator::GeneratePolytopeFromPoint(const Eigen::Vector3d &pt, Polytope &polytope) {
  Eigen::Vector3d box_max, box_min;
  PointCloud pc;
  std::vector<uint8_t> point_is_unknown;
  getSeedBBox(pt, pt, box_min, box_max);
  boundBoxByLocalMap(box_min, box_max);
  boxSearchCorridorObstacles(box_min, box_max, pc, point_is_unknown);
  box_min.z() += robot_r_;
  box_max.z() -= robot_r_;

  const Eigen::Vector3d a = pt, b = pt;
  Eigen::Matrix<double, 6, 4> bd = Eigen::Matrix<double, 6, 4>::Zero();
  bd(0, 0) = 1.0;
  bd(1, 0) = -1.0;
  bd(2, 1) = 1.0;
  bd(3, 1) = -1.0;
  bd(4, 2) = 1.0;
  bd(5, 2) = -1.0;
  bd(0, 3) = -box_max.x();
  bd(1, 3) = box_min.x();
  bd(2, 3) = -box_max.y();
  bd(3, 3) = box_min.y();
  bd(4, 3) = -box_max.z();
  bd(5, 3) = box_min.z();

  PlaneMat planes;
  if (pc.empty()) {
    planes.resize(6, 4);
    planes.row(0) << 1, 0, 0, -box_max.x();
    planes.row(1) << 0, 1, 0, -box_max.y();
    planes.row(2) << 0, 0, 1, -box_max.z();
    planes.row(3) << -1, 0, 0, box_min.x();
    planes.row(4) << 0, -1, 0, box_min.y();
    planes.row(5) << 0, 0, -1, box_min.z();
    polytope.SetPlanes(planes);
    polytope.SetSeedLine(Line{pt, pt});
    return true;
  }

  latest_pc_.insert(latest_pc_.end(), pc.begin(), pc.end());
  Eigen::Map<const Eigen::Matrix<double, 3, -1, Eigen::ColMajor>> pp(pc[0].data(), 3, pc.size());
  if (ciri_->comvexDecomposition(bd, pp, a, b, point_is_unknown) == SUCCESS) {
    ciri_->getPolytope(polytope);
    polytope.SetSeedLine(Line{pt, pt});
    return true;
  }
  polytope.Reset();
  return false;
}

bool CorridorGenerator::GenerateEmptyPolytope(const Eigen::Vector3d &pt, const double dis,
                                              Polytope &polytope) {
  const Eigen::Vector3d box_min = pt - Eigen::Vector3d(dis, dis, dis);
  const Eigen::Vector3d box_max = pt + Eigen::Vector3d(dis, dis, dis);
  PlaneMat planes(6, 4);
  planes.row(0) << 1, 0, 0, -box_max.x();
  planes.row(1) << 0, 1, 0, -box_max.y();
  planes.row(2) << 0, 0, 1, -box_max.z();
  planes.row(3) << -1, 0, 0, box_min.x();
  planes.row(4) << 0, -1, 0, box_min.y();
  planes.row(5) << 0, 0, -1, box_min.z();
  polytope.SetPlanes(planes);
  polytope.SetSeedLine(Line{pt, pt});
  return true;
}

bool CorridorGenerator::GeneratePolytopeFromLine(const Line &line, Polytope &polytope) {
  Eigen::Vector3d box_max, box_min;
  PointCloud pc;
  std::vector<uint8_t> point_is_unknown;
  getSeedBBox(line.first, line.second, box_min, box_max);
  boundBoxByLocalMap(box_min, box_max);
  boxSearchCorridorObstacles(box_min, box_max, pc, point_is_unknown);
  box_min.z() += robot_r_;
  box_max.z() -= robot_r_;

  const Eigen::Vector3d a = line.first, b = line.second;
  Eigen::Matrix<double, 6, 4> bd = Eigen::Matrix<double, 6, 4>::Zero();
  bd(0, 0) = 1.0;
  bd(1, 0) = -1.0;
  bd(2, 1) = 1.0;
  bd(3, 1) = -1.0;
  bd(4, 2) = 1.0;
  bd(5, 2) = -1.0;
  bd(0, 3) = -box_max.x();
  bd(1, 3) = box_min.x();
  bd(2, 3) = -box_max.y();
  bd(3, 3) = box_min.y();
  bd(4, 3) = -box_max.z();
  bd(5, 3) = box_min.z();

  PlaneMat planes;
  if (pc.empty()) {
    planes.resize(6, 4);
    planes.row(0) << 1, 0, 0, -box_max.x();
    planes.row(1) << 0, 1, 0, -box_max.y();
    planes.row(2) << 0, 0, 1, -box_max.z();
    planes.row(3) << -1, 0, 0, box_min.x();
    planes.row(4) << 0, -1, 0, box_min.y();
    planes.row(5) << 0, 0, -1, box_min.z();
    polytope.SetPlanes(planes);
    polytope.SetSeedLine(line);
    return true;
  }

  latest_pc_.insert(latest_pc_.end(), pc.begin(), pc.end());
  Eigen::Map<const Eigen::Matrix<double, 3, -1, Eigen::ColMajor>> pp(pc[0].data(), 3, pc.size());
  if (ciri_->comvexDecomposition(bd, pp, a, b, point_is_unknown) == SUCCESS) {
    ciri_->getPolytope(polytope);
    polytope.SetSeedLine(line);
    return true;
  }
  polytope.Reset();
  return false;
}

}  // namespace corridor_gen
