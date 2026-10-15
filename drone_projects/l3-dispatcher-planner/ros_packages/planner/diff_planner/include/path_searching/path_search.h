#ifndef _DIFF_PATH_SEARCH_H_
#define _DIFF_PATH_SEARCH_H_

#include <iostream>
#include <memory>
#include <queue>
#include <string>
#include <unordered_map>
#include <vector>

#include <Eigen/Eigen>
#include <plan_env/grid_map.h>
#include <path_searching/dyn_a_star.h>
#include <ros/console.h>
#include <ros/ros.h>

using path_searching::GridNode;
using path_searching::GridNodePtr;
using path_searching::NodeComparator;

enum class PATH_SEARCH_RET
{
  REACH_GOAL,
  REACH_FAR,
  INIT_ERR,
  TIME_OUT,
  OPENSET_EMPTY,
  OVER_POOL,
  SEARCH_ERR
};

const std::unordered_map<PATH_SEARCH_RET, std::string> PATH_SEARCH_RET_STR = {
    {PATH_SEARCH_RET::REACH_GOAL, "REACH_GOAL"},
    {PATH_SEARCH_RET::REACH_FAR, "REACH_FAR"},
    {PATH_SEARCH_RET::INIT_ERR, "INIT_ERR"},
    {PATH_SEARCH_RET::TIME_OUT, "TIME_OUT"},
    {PATH_SEARCH_RET::OPENSET_EMPTY, "OPENSET_EMPTY"},
    {PATH_SEARCH_RET::OVER_POOL, "OVER_POOL"},
    {PATH_SEARCH_RET::SEARCH_ERR, "SEARCH_ERR"}};

class PathSearcher
{
 private:
  struct Vector3iHash
  {
    std::size_t operator()(const Eigen::Vector3i &v) const
    {
      const std::size_t h0 = std::hash<int>()(v(0));
      const std::size_t h1 = std::hash<int>()(v(1));
      const std::size_t h2 = std::hash<int>()(v(2));
      return ((h0 ^ (h1 << 1)) >> 1) ^ (h2 << 1);
    }
  };

  GridMap::Ptr grid_map_;

  double getDiagHeu(GridNodePtr node1, GridNodePtr node2);
  double getManhHeu(GridNodePtr node1, GridNodePtr node2);
  double getEuclHeu(GridNodePtr node1, GridNodePtr node2);
  inline double getHeu(GridNodePtr node1, GridNodePtr node2);

  bool ConvertToIndexAndCheckInit(Eigen::Vector3d &start_pt, Eigen::Vector3d &end_pt,
                                  Eigen::Vector3i &start_idx, Eigen::Vector3i &end_idx,
                                  const bool ignore_unknown, const bool use_bigger_inflation);
  GridNode *getNode(const Eigen::Vector3i &idx);
  void resetSearchPool();
  std::vector<GridNodePtr> retrievePath(GridNodePtr current);

  int pool_size_{100000};
  int pool_used_{0};
//   const double tie_breaker_ = 1.0 + 1.0 / 10000;
const double tie_breaker_ = 1.0 + 0.5;

  std::vector<GridNode> node_pool_;
  std::unordered_map<Eigen::Vector3i, int, Vector3iHash> idx_to_slot_;
  std::vector<GridNodePtr> gridPath_;
  std::priority_queue<GridNodePtr, std::vector<GridNodePtr>, NodeComparator> openSet_;

  int rounds_{0};

 public:
  typedef std::shared_ptr<PathSearcher> Ptr;

  PathSearcher() = default;
  ~PathSearcher() = default;

  void initGridMap(GridMap::Ptr occ_map, int pool_size);

  PATH_SEARCH_RET PathSearch(const double search_dist_max, Eigen::Vector3d start_pt, Eigen::Vector3d end_pt,
                             const double partial_success_min_len = -1.0,
                             const bool ignore_unknown = false,
                             const bool use_bigger_inflation = false);

  std::vector<Eigen::Vector3d> getPath();
};

inline double PathSearcher::getHeu(GridNodePtr node1, GridNodePtr node2)
{
  return tie_breaker_ * getDiagHeu(node1, node2);
}

#endif
