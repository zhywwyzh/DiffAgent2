#include "path_searching/path_search.h"

#include <chrono>

using namespace Eigen;

namespace
{
constexpr int kTimeCheckInterval = 64;
constexpr double kSearchTimeLimitSec = 0.09;

inline bool isSearchTimedOut(const std::chrono::steady_clock::time_point &t_start)
{
  return std::chrono::duration<double>(std::chrono::steady_clock::now() - t_start).count() >
         kSearchTimeLimitSec;
}
} // namespace

void PathSearcher::initGridMap(GridMap::Ptr occ_map, int pool_size)
{
  pool_size_ = std::max(1, pool_size);
  node_pool_.assign(pool_size_, GridNode());
  grid_map_ = occ_map;
}

void PathSearcher::resetSearchPool()
{
  pool_used_ = 0;
  idx_to_slot_.clear();
}

GridNode *PathSearcher::getNode(const Eigen::Vector3i &idx)
{
  const auto it = idx_to_slot_.find(idx);
  if (it != idx_to_slot_.end())
    return &node_pool_[it->second];

  if (pool_used_ >= pool_size_)
    return nullptr;

  const int slot = pool_used_++;
  idx_to_slot_.emplace(idx, slot);
  GridNode &node = node_pool_[slot];
  node.index = idx;
  node.rounds = 0;
  node.gScore = path_searching::kGridInf;
  node.fScore = path_searching::kGridInf;
  node.state = GridNode::UNDEFINED;
  node.cameFrom = nullptr;
  return &node;
}

double PathSearcher::getDiagHeu(GridNodePtr node1, GridNodePtr node2)
{
  double dx = abs(node1->index(0) - node2->index(0));
  double dy = abs(node1->index(1) - node2->index(1));
  double dz = abs(node1->index(2) - node2->index(2));

  double h = 0.0;
  int diag = min(min(dx, dy), dz);
  dx -= diag;
  dy -= diag;
  dz -= diag;

  if (dx == 0)
    h = 1.0 * sqrt(3.0) * diag + sqrt(2.0) * min(dy, dz) + 1.0 * abs(dy - dz);
  if (dy == 0)
    h = 1.0 * sqrt(3.0) * diag + sqrt(2.0) * min(dx, dz) + 1.0 * abs(dx - dz);
  if (dz == 0)
    h = 1.0 * sqrt(3.0) * diag + sqrt(2.0) * min(dx, dy) + 1.0 * abs(dx - dy);
  return h;
}

double PathSearcher::getManhHeu(GridNodePtr node1, GridNodePtr node2)
{
  const double dx = abs(node1->index(0) - node2->index(0));
  const double dy = abs(node1->index(1) - node2->index(1));
  const double dz = abs(node1->index(2) - node2->index(2));
  return dx + dy + dz;
}

double PathSearcher::getEuclHeu(GridNodePtr node1, GridNodePtr node2)
{
  return (node2->index - node1->index).norm();
}

std::vector<GridNodePtr> PathSearcher::retrievePath(GridNodePtr current)
{
  std::vector<GridNodePtr> path;
  path.push_back(current);

  while (current->cameFrom != NULL)
  {
    current = current->cameFrom;
    path.push_back(current);
  }

  return path;
}

bool PathSearcher::ConvertToIndexAndCheckInit(Eigen::Vector3d &start_pt, Eigen::Vector3d &end_pt,
                                              Eigen::Vector3i &start_idx, Eigen::Vector3i &end_idx,
                                              const bool ignore_unknown, const bool use_bigger_inflation)
{
  start_idx = grid_map_->pos2GlobalIdx(start_pt);
  end_idx = grid_map_->pos2GlobalIdx(end_pt);
  const auto mapCheck = [&](const Eigen::Vector3d &pt) -> int {
    if (use_bigger_inflation)
    {
      if (ignore_unknown)
        return grid_map_->getBiggerInflateOccupancy(pt);
      return grid_map_->getInflateOccupancyWithAllUnknownInfBigger(pt);
    }
    if (ignore_unknown)
      return grid_map_->getInflateOccupancy(pt);
    return grid_map_->getInflateOccupancyWithAllUnknownInf(pt);
  };
  if (mapCheck(start_pt) < 0)
  {
    ROS_WARN("[PathSearcher] Start point outside the map region.");
    return false;
  }
  if (mapCheck(end_pt) < 0)
  {
    ROS_WARN("[PathSearcher] End point outside the map region.");
    return false;
  }
  return true;
}

PATH_SEARCH_RET PathSearcher::PathSearch(const double search_dist_max, Eigen::Vector3d start_pt,
                                         Eigen::Vector3d end_pt, const double partial_success_min_len,
                                         const bool ignore_unknown, const bool use_bigger_inflation)
{
  const auto t_start = std::chrono::steady_clock::now();
  ++rounds_;
  resetSearchPool();

  Eigen::Vector3i start_idx, end_idx;
  if (!ConvertToIndexAndCheckInit(start_pt, end_pt, start_idx, end_idx, ignore_unknown, use_bigger_inflation))
  {
    ROS_ERROR("[PathSearcher] Unable to handle the initial or end point, force return!");
    return PATH_SEARCH_RET::INIT_ERR;
  }

  const auto isOccupied = [&](const Eigen::Vector3d &pos) -> bool {
    if (use_bigger_inflation)
    {
      if (ignore_unknown)
      {
        return grid_map_->getBiggerInflateOccupancy(pos) > 0;
      }
      return grid_map_->getInflateOccupancyWithAllUnknownInfBigger(pos) > 0;
    }
    if (ignore_unknown)
    {
      return grid_map_->getInflateOccupancy(pos) > 0;
    }
    return grid_map_->getInflateOccupancyWithAllUnknownInf(pos) > 0;
  };

  GridNode *startPtr = getNode(start_idx);
  GridNode *endPtr = getNode(end_idx);
  if (!startPtr || !endPtr)
  {
    ROS_ERROR("[PathSearcher] Node pool exhausted at init, pool_size=%d", pool_size_);
    return PATH_SEARCH_RET::OVER_POOL;
  }

  std::priority_queue<GridNodePtr, std::vector<GridNodePtr>, NodeComparator> empty;
  openSet_.swap(empty);

  startPtr->index = start_idx;
  startPtr->rounds = rounds_;
  startPtr->gScore = 0;
  startPtr->fScore = getHeu(startPtr, endPtr);
  startPtr->state = GridNode::OPENSET;
  startPtr->cameFrom = NULL;
  openSet_.push(startPtr);

  const double map_resolution = grid_map_->getResolution();
  int num_iter = 0;
  GridNodePtr best_progress_ptr = startPtr;
  double best_g_score = 0.0;

  while (!openSet_.empty())
  {
    ++num_iter;
    GridNodePtr current = openSet_.top();
    openSet_.pop();

    if (current->gScore > best_g_score)
    {
      best_g_score = current->gScore;
      best_progress_ptr = current;
    }

    if (current->index(0) == end_idx(0) && current->index(1) == end_idx(1) &&
        current->index(2) == end_idx(2))
    {
      gridPath_ = retrievePath(current);
      return PATH_SEARCH_RET::REACH_GOAL;
    }
    if (search_dist_max > 0 && current->gScore > search_dist_max / map_resolution)
    {
      gridPath_ = retrievePath(current);
      return PATH_SEARCH_RET::REACH_FAR;
    }

    current->state = GridNode::CLOSEDSET;

    for (int dx = -1; dx <= 1; ++dx)
      for (int dy = -1; dy <= 1; ++dy)
        for (int dz = -1; dz <= 1; ++dz)
        {
          if (dx == 0 && dy == 0 && dz == 0)
            continue;

          const Eigen::Vector3i neighborIdx = current->index + Eigen::Vector3i(dx, dy, dz);
          if (!grid_map_->isInsideBuffer(grid_map_->globalIdx2Pos(neighborIdx)))
            continue;

          GridNode *neighborPtr = getNode(neighborIdx);
          if (!neighborPtr)
          {
            ROS_ERROR("[PathSearcher] Node pool exhausted during search, used=%d, pool_size=%d",
                      pool_used_, pool_size_);
            return PATH_SEARCH_RET::OVER_POOL;
          }

          const bool flag_explored = neighborPtr->rounds == rounds_;
          if (flag_explored && neighborPtr->state == GridNode::CLOSEDSET)
            continue;

          neighborPtr->index = neighborIdx;
          neighborPtr->rounds = rounds_;

          if (isOccupied(grid_map_->globalIdx2Pos(neighborIdx)))
            continue;

          const double static_cost = sqrt(dx * dx + dy * dy + dz * dz);
          const double tentative_gScore = current->gScore + static_cost;

          if (!flag_explored)
          {
            neighborPtr->state = GridNode::OPENSET;
            neighborPtr->cameFrom = current;
            neighborPtr->gScore = tentative_gScore;
            neighborPtr->fScore = tentative_gScore + getHeu(neighborPtr, endPtr);
            openSet_.push(neighborPtr);
          }
          else if (tentative_gScore < neighborPtr->gScore)
          {
            neighborPtr->cameFrom = current;
            neighborPtr->gScore = tentative_gScore;
            neighborPtr->fScore = tentative_gScore + getHeu(neighborPtr, endPtr);
          }
        }

    if ((num_iter & (kTimeCheckInterval - 1)) == 0 && isSearchTimedOut(t_start))
    {
      const double searched_len = best_g_score * map_resolution;
      if (partial_success_min_len >= 0.0 && searched_len > partial_success_min_len)
      {
        gridPath_ = retrievePath(best_progress_ptr);
        ROS_WARN("[PathSearcher] A* timeout (%.0fms), partial path len %.3f > guide_use_len %.3f, accept as REACH_FAR.",
                 kSearchTimeLimitSec * 1000.0, searched_len, partial_success_min_len);
        return PATH_SEARCH_RET::REACH_FAR;
      }
      ROS_WARN("[PathSearcher] A* timeout (%.0fms), partial path len %.3f <= guide_use_len %.3f.",
               kSearchTimeLimitSec * 1000.0, searched_len, partial_success_min_len);
      return PATH_SEARCH_RET::TIME_OUT;
    }
  }

  if (isSearchTimedOut(t_start))
  {
    const double searched_len = best_g_score * map_resolution;
    if (partial_success_min_len >= 0.0 && searched_len > partial_success_min_len)
    {
      gridPath_ = retrievePath(best_progress_ptr);
      ROS_WARN("[PathSearcher] A* timeout (%.0fms) with empty open set, partial path len %.3f > guide_use_len %.3f.",
               kSearchTimeLimitSec * 1000.0, searched_len, partial_success_min_len);
      return PATH_SEARCH_RET::REACH_FAR;
    }
    return PATH_SEARCH_RET::TIME_OUT;
  }

  const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - t_start).count();
  if (elapsed > 0.05)
    ROS_WARN("[PathSearcher] Time consume in A star path finding is %.3fs, iter=%d", elapsed, num_iter);

  return PATH_SEARCH_RET::OPENSET_EMPTY;
}

std::vector<Vector3d> PathSearcher::getPath()
{
  std::vector<Vector3d> path;
  for (auto ptr : gridPath_)
    path.push_back(grid_map_->globalIdx2Pos(ptr->index));
  reverse(path.begin(), path.end());
  return path;
}
