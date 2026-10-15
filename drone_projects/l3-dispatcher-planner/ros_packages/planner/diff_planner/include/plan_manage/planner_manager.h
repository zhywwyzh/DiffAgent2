#ifndef _PLANNER_MANAGER_H_
#define _PLANNER_MANAGER_H_

#include <stdlib.h>

#include <optimizer/poly_traj_optimizer.h>
#include <plan_env/grid_map.h>
#include <traj_utils/plan_container.hpp>
#include <traj_utils/traj_stitch.hpp>
#include <ros/ros.h>
#include <traj_utils/planning_visualization.h>
#include <optimizer/poly_traj_utils.hpp>
#include <corridor_gen/corridor_generator.h>
#include <path_searching/path_search.h>

namespace diff_planner
{

  // Fast Planner Manager
  // Key algorithms of mapping and planning are called

  class DiffPlannerManager
  {
    // SECTION stable
  public:
    DiffPlannerManager();
    ~DiffPlannerManager();

    EIGEN_MAKE_ALIGNED_OPERATOR_NEW

    /* main planning interface */
    void initPlanModules(ros::NodeHandle &nh, PlanningVisualization::Ptr vis = NULL);
    bool computeInitState(
        const Eigen::Vector3d &start_pt, const Eigen::Vector3d &start_vel,
        const Eigen::Vector3d &start_acc, const Eigen::Vector3d &local_target_pt,
        const Eigen::Vector3d &local_target_vel, const bool flag_polyInit,
        const bool flag_randomPolyTraj, const double &ts, poly_traj::MinJerkOpt &initMJO);
    bool computeInitStateWithPolySearch(
        const Eigen::Vector3d &start_pt, const Eigen::Vector3d &start_vel,
        const Eigen::Vector3d &start_acc, const Eigen::Vector3d &local_target_pt,
        const Eigen::Vector3d &local_target_vel, const bool flag_polyInit,
        const double &ts, poly_traj::MinJerkOpt &initMJO);
    bool reboundReplan(
        const Eigen::Vector3d &start_pt, const Eigen::Vector3d &start_vel,
        const Eigen::Vector3d &start_acc, const Eigen::Vector3d &end_pt,
        const Eigen::Vector3d &end_vel, const bool flag_polyInit,
        const bool flag_randomPolyTraj, const bool catch_goal);
    bool planGlobalTrajWaypoints(
        const Eigen::Vector3d &start_pos, const Eigen::Vector3d &start_vel,
        const Eigen::Vector3d &start_acc, const std::vector<Eigen::Vector3d> &waypoints,
        const Eigen::Vector3d &end_vel, const Eigen::Vector3d &end_acc);
    void getLocalTarget(
        const double planning_horizen,
        const Eigen::Vector3d &start_pt, const Eigen::Vector3d &global_end_pt,
        Eigen::Vector3d &local_target_pos, Eigen::Vector3d &local_target_vel,
        bool &catch_goal);
    /**
     * Refresh the risk-adaptive velocity bound from the committed-flight region.
     *
     * @param[in] fallback_center  Region center when no trajectory is committed [m]
     */
    void updateRiskVelBound(const Eigen::Vector3d &fallback_center);
    bool EmergencyStop(Eigen::Vector3d stop_pos);
    bool checkCollision(int drone_id);
    bool setLocalTrajFromOpt(const poly_traj::MinJerkOpt &opt, const bool catch_goal);
    void beginReplanStitch(const double replan_start_WT, const double t_cur, const double t_replan_state);
    void clearReplanStitch();
    double getReplanPassedTimeOnLocalTraj() const;
    inline double getReplanProcessStartTT() const
    {
      return replan_stitch_.enable ? replan_stitch_.replan_process_start_TT
                                   : (ros::Time::now().toSec() - traj_.local_traj.start_time);
    }
    inline const ReplanStitchInfo &getReplanStitchInfo() const { return replan_stitch_; }
    inline double getSwarmClearance(void) { return ploy_traj_opt_->get_swarm_clearance_(); }
    inline int getCpsNumPrePiece(void) { return ploy_traj_opt_->get_cps_num_prePiece_(); }
    /**
     * Return the raw A-star / guide search path of the LAST replan when the front-
     * end stage produced one (feed for the canonical /drone_<id>/planner/
     * search_path topic, ground-station-channels.spec.md §2.5). The guide
     * path is warmup + A* merged, i.e. the full front-end search result.
     *
     * @return Empty vector when the last replan had no front-end path
     */
    inline const std::vector<Eigen::Vector3d>& getSearchPath() const { return last_search_path_; }
    // inline PtsChk_t getPtsCheck(void) { return ploy_traj_opt_->get_pts_check_(); }

    PlanParameters pp_;
    GridMap::Ptr grid_map_;
    TrajContainer traj_;
    corridor_gen::PolytopeVec init_sfc_;
    SfcCorridorInitData sfc_init_data_;
    bool keep_last_traj_{false};
    bool touch_goal_{false};
    ReplanStitchInfo replan_stitch_;

  private:
    PlanningVisualization::Ptr visualization_;
    PolyTrajOptimizer::Ptr ploy_traj_opt_;
    corridor_gen::CorridorGenerator::Ptr corridor_gen_;
    PathSearcher path_searcher_;

    int continous_failures_count_{0};
    double risk_vel_{-1.0}, risk_vel_prev_{-1.0};
    std::vector<Eigen::Vector3d> last_search_path_;

  public:
    typedef unique_ptr<DiffPlannerManager> Ptr;

    // !SECTION
  };
} // namespace diff_planner

#endif