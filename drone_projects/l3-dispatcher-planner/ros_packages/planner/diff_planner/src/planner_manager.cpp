#include <plan_manage/path_process.hpp>
#include <path_searching/path_search.h>
#include <corridor_gen/corridor_generator.h>
#include <corridor_gen/geometry_utils.h>
#include <plan_manage/planner_manager.h>
#include <thread>
#include "visualization_msgs/Marker.h" // zx-todo

namespace diff_planner
{

  // SECTION interfaces for setup and query

  DiffPlannerManager::DiffPlannerManager() {}

  DiffPlannerManager::~DiffPlannerManager() { std::cout << "des manager" << std::endl; }

  void DiffPlannerManager::initPlanModules(ros::NodeHandle &nh, PlanningVisualization::Ptr vis)
  {
    /* read algorithm parameters */

    nh.param("manager/max_vel", pp_.max_vel_, -1.0);
    nh.param("manager/max_acc", pp_.max_acc_, -1.0);
    nh.param("manager/feasibility_tolerance", pp_.feasibility_tolerance_, 0.0);
    nh.param("manager/polyTraj_piece_length", pp_.polyTraj_piece_length, -1.0);
    nh.param("manager/planning_horizon", pp_.planning_horizon_, 5.0);
    nh.param("manager/use_multitopology_trajs", pp_.use_multitopology_trajs, false);
    nh.param("manager/drone_id", pp_.drone_id, -1);
    nh.param("manager/drone_obs_radius", pp_.drone_obs_radius, -1.0);
    nh.param("manager/avoid_unknown_path_length", pp_.avoid_unknown_path_length, -1.0);
    nh.param("manager/path_warmup_length", pp_.path_warmup_length, -1.0);
    nh.param("manager/corridor_bound_dis", pp_.corridor_bound_dis, 2.0);
    nh.param("manager/corridor_seed_line_max_length", pp_.corridor_seed_line_max_length, 5.0);
    nh.param("manager/corridor_iris_iter_num", pp_.corridor_iris_iter_num, 2);
    nh.param("manager/use_corridor_unknown_avoid", pp_.use_corridor_unknown_avoid, false);
    nh.param("manager/use_unknown", pp_.use_unknown, false);
    nh.param("manager/replan_forward_dt", pp_.replan_forward_dt_, 0.1);
    nh.param("manager/risk/enable", pp_.risk_en, false);
    nh.param("manager/risk/vel_min", pp_.risk_vel_min, 0.8);
    nh.param("manager/risk/vel_max", pp_.risk_vel_max, 2.0);
    nh.param("manager/risk/th_low", pp_.risk_th_low, 0.3);
    nh.param("manager/risk/th_high", pp_.risk_th_high, 0.6);
    nh.param("manager/risk/vel_smooth", pp_.risk_vel_smooth, 0.95);
    nh.param("manager/risk/vel_max_drop", pp_.risk_vel_max_drop, 0.2);
    nh.param("manager/risk/radius_max", pp_.risk_radius_max, 0.8);

    grid_map_.reset(new GridMap);
    grid_map_->initMap(nh);

    path_searcher_.initGridMap(grid_map_, 100000);

    const double map_resolution = grid_map_->getResolution();
    const int neighbor_step = std::max(1, static_cast<int>(std::ceil(pp_.drone_obs_radius / map_resolution)));
    std::vector<Eigen::Vector3i> seed_line_neighbor;
    for (int x = -neighbor_step; x <= neighbor_step; ++x)
      for (int y = -neighbor_step; y <= neighbor_step; ++y)
        for (int z = -neighbor_step; z <= neighbor_step; ++z)
          if (x * x + y * y + z * z <= neighbor_step * neighbor_step)
            seed_line_neighbor.emplace_back(x, y, z);

    corridor_gen_.reset(new corridor_gen::CorridorGenerator(
        grid_map_, pp_.corridor_bound_dis, pp_.corridor_seed_line_max_length, map_resolution,
        pp_.drone_obs_radius, pp_.corridor_iris_iter_num, pp_.use_unknown));
    corridor_gen_->SetLineNeighborList(seed_line_neighbor);

    ploy_traj_opt_.reset(new PolyTrajOptimizer);
    ploy_traj_opt_->setParam(nh);
    ploy_traj_opt_->setEnvironment(grid_map_);

    visualization_ = vis;

    ploy_traj_opt_->setSwarmTrajs(&traj_.swarm_traj);
    ploy_traj_opt_->setDroneId(pp_.drone_id);
  }

  void DiffPlannerManager::updateRiskVelBound(const Eigen::Vector3d &fallback_center)
  {
    if (!pp_.risk_en)
      return;

    /* Committed-flight region: flattened ellipsoid around the current committed
     * trajectory position; the horizontal radius is the remaining committed arc
     * length (fallback: half the planning horizon), the vertical half-extent is
     * the robot radius so floor/ceiling at cruise altitude does not peg the
     * score. Mirrors SUPER's per-corridor occupancy risk. */
    const double res = grid_map_->getResolution();
    Eigen::Vector3d center = fallback_center;
    double commit_len = pp_.planning_horizon_ * 0.5;
    LocalTrajData *info = &traj_.local_traj;
    if (info->traj_id > 0 && info->duration > 1e-3)
    {
      double t_cur = ros::Time::now().toSec() - info->start_time;
      t_cur = std::max(0.0, std::min(info->duration, t_cur));
      center = info->traj.getPos(t_cur);
      double arc = 0.0;
      Eigen::Vector3d prev = center;
      for (double t = t_cur + 0.2; t <= info->duration + 1e-6; t += 0.2)
      {
        const Eigen::Vector3d p = info->traj.getPos(std::min(t, info->duration));
        arc += (p - prev).norm();
        prev = p;
      }
      commit_len = arc;
    }
    const double radius_xy = std::min(commit_len, pp_.risk_radius_max);
    const double radius_z = std::max(pp_.drone_obs_radius, res);

    /* Ellipsoid scan: max occupancy probability inside the committed region. */
    double max_log_odds = -1e30;
    const double r2xy = radius_xy * radius_xy, r2z = radius_z * radius_z;
    for (double dx = -radius_xy; dx <= radius_xy + 1e-9; dx += res)
      for (double dy = -radius_xy; dy <= radius_xy + 1e-9; dy += res)
      {
        const double hxy = (dx * dx + dy * dy) / r2xy;
        if (hxy > 1.0)
          continue;
        for (double dz = -radius_z; dz <= radius_z + 1e-9; dz += res)
        {
          if (hxy + dz * dz / r2z > 1.0)
            continue;
          max_log_odds = std::max(max_log_odds,
                                  grid_map_->getOccupancyLogOdds(center + Eigen::Vector3d(dx, dy, dz)));
        }
      }
    const double max_risk = 1.0 / (1.0 + std::exp(-max_log_odds));

    const double ratio = std::min(std::max(
        (max_risk - pp_.risk_th_low) / (pp_.risk_th_high - pp_.risk_th_low), 0.0), 1.0);
    const double v_raw = pp_.risk_vel_min + (1.0 - ratio) * (pp_.risk_vel_max - pp_.risk_vel_min);
    /* Conservative seed: ramp up from vel_min through the low-pass filter. */
    if (risk_vel_ <= 0.0)
      risk_vel_ = pp_.risk_vel_min;
    risk_vel_ = pp_.risk_vel_smooth * risk_vel_ + (1.0 - pp_.risk_vel_smooth) * v_raw;
    /* Asymmetric slew limit: rise freely, fall by at most max_drop per replan so
     * the optimizer init state stays inside the bound while braking. */
    risk_vel_ = std::max(risk_vel_, risk_vel_prev_ - pp_.risk_vel_max_drop);
    risk_vel_prev_ = risk_vel_;

    ploy_traj_opt_->setMaxVelBound(risk_vel_);
    pp_.max_vel_ = risk_vel_;
    ROS_INFO_THROTTLE(1.0, "[DiffPlanner] risk_vel: max_risk=%.3f v_raw=%.2f v_smooth=%.2f radius_xy=%.2f",
                      max_risk, v_raw, risk_vel_, radius_xy);
  }

  bool DiffPlannerManager::reboundReplan(
      const Eigen::Vector3d &start_pt, const Eigen::Vector3d &start_vel,
      const Eigen::Vector3d &start_acc, const Eigen::Vector3d &local_target_pt,
      const Eigen::Vector3d &local_target_vel, const bool flag_polyInit,
      const bool flag_randomPolyTraj, const bool catch_goal)
  {
    if (flag_polyInit) {
      keep_last_traj_ = false;
      touch_goal_ = false;
    }
    if (keep_last_traj_) {
      ROS_INFO("[reboundReplan] touch goal");
      return true;
    }
    updateRiskVelBound(start_pt);

    ros::Time t_start = ros::Time::now();
    ros::Duration t_init, t_opt;

    static int count = 0;
    cout << "\033[47;30m\n[" << t_start << "] Drone " << pp_.drone_id << " Replan " << count++ << "\033[0m" << endl;
    ROS_INFO("start: [%f, %f, %f], [%f, %f, %f]\nlocal_target: [%f, %f, %f], [%f, %f, %f]",
             start_pt.x(), start_pt.y(), start_pt.z(), start_vel.x(), start_vel.y(), start_vel.z(),
             local_target_pt.x(), local_target_pt.y(), local_target_pt.z(),
             local_target_vel.x(), local_target_vel.y(), local_target_vel.z());
    // cout.precision(3);
    // cout << "start: " << start_pt.transpose() << ", " << start_vel.transpose() << "\ngoal:" << local_target_pt.transpose() << ", " << local_target_vel.transpose()
    //      << endl;
    // if ((start_pt - local_target_pt).norm() < 0.2)
    //   cout << "Close to goal" << endl;

    /*** STEP 1: INIT ***/
    ROS_INFO("reboundReplan1");
    ploy_traj_opt_->setIfTouchGoal(catch_goal);
    double ts = pp_.polyTraj_piece_length / pp_.max_vel_;
    ROS_INFO("reboundReplan2");
    poly_traj::MinJerkOpt initMJO;
    if (pp_.use_corridor_unknown_avoid) {
      if (!computeInitStateWithPolySearch(start_pt, start_vel, start_acc, local_target_pt, local_target_vel,
                          flag_polyInit, ts, initMJO))
      {
        ROS_INFO("reboundReplan3.1");
        return false;
      }
    } else {
      if (!computeInitState(start_pt, start_vel, start_acc, local_target_pt, local_target_vel,
                            flag_polyInit, flag_randomPolyTraj, ts, initMJO))
      {
        ROS_INFO("reboundReplan3.2");
        return false;
      }
    }

    // if (!computeInitState(start_pt, start_vel, start_acc, local_target_pt, local_target_vel,
    //                       flag_polyInit, flag_randomPolyTraj, ts, initMJO))
    // {
    //   return false;
    // }
    ROS_INFO("reboundReplan4");
    Eigen::MatrixXd cstr_pts = initMJO.getInitConstraintPoints(ploy_traj_opt_->get_cps_num_prePiece_());
    vector<std::pair<int, int>> segments;
    if (ploy_traj_opt_->finelyCheckAndSetConstraintPoints(segments, initMJO, true) == PolyTrajOptimizer::CHK_RET::ERR)
    {
      ROS_INFO("reboundReplan5");
      return false;
    }
    ROS_INFO("reboundReplan6");
    t_init = ros::Time::now() - t_start;

    std::vector<Eigen::Vector3d> point_set;
    for (int i = 0; i < cstr_pts.cols(); ++i)
      point_set.push_back(cstr_pts.col(i));
    visualization_->displayInitPathList(point_set, 0.2, 0);
    ROS_INFO("reboundReplan7");
    t_start = ros::Time::now();

    /*** STEP 2: OPTIMIZE ***/
    bool flag_success = false;
    vector<vector<Eigen::Vector3d>> vis_trajs;
    poly_traj::MinJerkOpt best_MJO;

    // ROS_ERROR("BBBB");

    if (pp_.use_multitopology_trajs)
    {
      ROS_INFO("reboundReplan8");
      std::vector<ConstraintPoints> trajs = ploy_traj_opt_->distinctiveTrajs(segments);
      Eigen::VectorXi success = Eigen::VectorXi::Zero(trajs.size());
      poly_traj::Trajectory initTraj = initMJO.getTraj();
      int PN = initTraj.getPieceNum();
      Eigen::MatrixXd all_pos = initTraj.getPositions();
      Eigen::MatrixXd innerPts = all_pos.block(0, 1, 3, PN - 1);
      Eigen::Matrix<double, 3, 3> headState, tailState;
      headState << initTraj.getJuncPos(0), initTraj.getJuncVel(0), initTraj.getJuncAcc(0);
      tailState << initTraj.getJuncPos(PN), initTraj.getJuncVel(PN), initTraj.getJuncAcc(PN);
      double final_cost, min_cost = 999999.0;
      ROS_INFO("reboundReplan8.1");
      for (int i = trajs.size() - 1; i >= 0; i--)
      {
        ploy_traj_opt_->setConstraintPoints(trajs[i]);
        ploy_traj_opt_->setUseMultitopologyTrajs(true);
        if (ploy_traj_opt_->optimizeTrajectory(headState, tailState,
                                               innerPts, initTraj.getDurations(), final_cost))
        {
          success[i] = true;

          if (final_cost < min_cost)
          {
            min_cost = final_cost;
            best_MJO = ploy_traj_opt_->getMinJerkOpt();
            flag_success = true;
          }

          // visualization
          Eigen::MatrixXd ctrl_pts_temp = ploy_traj_opt_->getMinJerkOpt().getInitConstraintPoints(ploy_traj_opt_->get_cps_num_prePiece_());
          std::vector<Eigen::Vector3d> point_set;
          for (int j = 0; j < ctrl_pts_temp.cols(); j++)
          {
            point_set.push_back(ctrl_pts_temp.col(j));
          }
          vis_trajs.push_back(point_set);
        }
      }
      ROS_INFO("reboundReplan8.2");
      t_opt = ros::Time::now() - t_start;

      if (trajs.size() > 1)
      {
        cout << "\033[1;33m"
             << "multi-trajs=" << trajs.size() << ",\033[1;0m"
             << " Success:fail=" << success.sum() << ":" << success.size() - success.sum() << endl;
      }

      visualization_->displayMultiOptimalPathList(vis_trajs, 0.1); // This visuallization will take up several milliseconds.
    }
    else
    {
      ROS_INFO("reboundReplan9");
      poly_traj::Trajectory initTraj = initMJO.getTraj();
      int PN = initTraj.getPieceNum();
      Eigen::MatrixXd all_pos = initTraj.getPositions();
      Eigen::MatrixXd innerPts = all_pos.block(0, 1, 3, PN - 1);
      Eigen::Matrix<double, 3, 3> headState, tailState;
      headState << initTraj.getJuncPos(0), initTraj.getJuncVel(0), initTraj.getJuncAcc(0);
      tailState << initTraj.getJuncPos(PN), initTraj.getJuncVel(PN), initTraj.getJuncAcc(PN);
      double final_cost;
      flag_success = ploy_traj_opt_->optimizeTrajectory(headState, tailState,
                                                        innerPts, initTraj.getDurations(), final_cost);
      best_MJO = ploy_traj_opt_->getMinJerkOpt();

      t_opt = ros::Time::now() - t_start;
    }

    /*** STEP 3: Store and display results ***/
    cout << "Success=" << (flag_success ? "yes" : "no") << endl;

    cstr_pts = best_MJO.getInitConstraintPoints(ploy_traj_opt_->get_cps_num_prePiece_());
    const poly_traj::Trajectory opt_traj = best_MJO.getTraj();
    std::vector<Eigen::Vector3d> junc_pts;
    junc_pts.reserve(opt_traj.getPieceNum() + 1);
    for (int i = 0; i <= opt_traj.getPieceNum(); ++i)
      junc_pts.push_back(opt_traj.getJuncPos(i));
    visualization_->displayOptResult(cstr_pts, junc_pts, flag_success, 0);

    if (flag_success)
    {
      static double sum_time = 0;
      static int count_success = 0;
      sum_time += (t_init + t_opt).toSec();
      count_success++;
      printf("Time:\033[42m%.3fms,\033[0m init:%.3fms, optimize:%.3fms, avg=%.3fms\n",
             (t_init + t_opt).toSec() * 1000, t_init.toSec() * 1000, t_opt.toSec() * 1000, sum_time / count_success * 1000);
      // cout << "total time:\033[42m" << (t_init + t_opt).toSec()
      //      << "\033[0m,init:" << t_init.toSec()
      //      << ",optimize:" << t_opt.toSec()
      //      << ",avg_time=" << sum_time / count_success << endl;
      if (replan_stitch_.enable)
      {
        const double replan_total_t = ros::Time::now().toSec() - replan_stitch_.replan_start_WT;
        if (replan_total_t > pp_.replan_forward_dt_)
        {
          ROS_WARN("[DiffPlanner] Replan overtime (%.3fs > %.3fs), reject trajectory.",
                   replan_total_t, pp_.replan_forward_dt_);
          continous_failures_count_++;
          return false;
        }
      }
      setLocalTrajFromOpt(best_MJO, catch_goal);

      double TOUCH_GOAL_DIST = 1.0;
      double opt_traj_dur = opt_traj.getTotalDuration();
      double opt_traj_end_dist = (opt_traj.getPos(opt_traj_dur) - opt_traj.getPos(0)).norm();
      if (catch_goal && touch_goal_ && opt_traj_end_dist < TOUCH_GOAL_DIST) {
        keep_last_traj_ = true;
      }

      continous_failures_count_ = 0;
    }
    else
    {
      continous_failures_count_++;
    }

    return flag_success;
  }

  bool DiffPlannerManager::computeInitStateWithPolySearch(
      const Eigen::Vector3d &start_pt, const Eigen::Vector3d &start_vel, const Eigen::Vector3d &start_acc,
      const Eigen::Vector3d &local_target_pt, const Eigen::Vector3d &local_target_vel,
      const bool flag_polyInit, const double &ts,
      poly_traj::MinJerkOpt &initMJO)
  {
    static bool flag_first_call = true;

    // Eigen::Matrix3d pos_init_state, pos_fina_state;
    Eigen::Matrix3d headState, tailState;
    std::vector<Eigen::Vector3d> guide_path;
    std::vector<double> guide_stamp;
    double guide_path_end_vel{0.0};
    double map_resolution = grid_map_->getResolution();
    int reserve_size = pp_.planning_horizon_ / map_resolution * 1.2;
    guide_path.reserve(reserve_size);
    guide_stamp.reserve(reserve_size);
    const double replan_process_start_WT = ros::Time::now().toSec();
    double replan_process_start_TT, replan_state_TT;
    double passed_t_on_lctraj = 0.0;
    double t_to_lc_end = 0.0;
    ROS_INFO("computeInitStateWithPolySearch1");

    if (flag_first_call || flag_polyInit) /*** case 1: polynomial initialization ***/
    {
      ROS_INFO("computeInitStateWithPolySearch2");
      flag_first_call = false;
      // headState << start_pt, start_vel, start_acc;
      // tailState << local_target_pt, local_target_vel, Eigen::Vector3d::Zero();
    }
    else /*** case 2: initialize from previous optimal trajectory ***/
    {
      ROS_INFO("computeInitStateWithPolySearch3");
      // 考虑只让当前时刻在正常轨迹内时才往下做
      if (traj_.global_traj.last_glb_t_of_lc_tgt < 0.0)
      {
        ROS_ERROR("You are initialzing a trajectory from a previous optimal trajectory, but no previous trajectories up to now.");
        return false;
      }

      /* the trajectory time system is a little bit complicated... */
      passed_t_on_lctraj = getReplanPassedTimeOnLocalTraj();
      t_to_lc_end = traj_.local_traj.duration - passed_t_on_lctraj;
      if (t_to_lc_end < 0)
      {
        ROS_INFO("t_to_lc_end < 0, exit and wait for another call.");
        return false;
      }

      double eval_t = passed_t_on_lctraj;
      const auto &guide_pos_traj = traj_.local_traj.traj;
      double guide_pos_traj_total_time = guide_pos_traj.getTotalDuration();
      double sample_traj_dt = map_resolution / pp_.max_vel_;

      std::vector<std::pair<double, Eigen::Vector3d>> last_local_traj_time_pos;
      std::vector<double> last_local_traj_vel;
      Eigen::Vector3d temp_pt, last_sample_pt;
      last_sample_pt = guide_pos_traj.getPos(eval_t);
      eval_t += sample_traj_dt;
      ROS_INFO("computeInitStateWithPolySearch4");
      for (; eval_t < guide_pos_traj_total_time; eval_t += sample_traj_dt) {
        temp_pt = guide_pos_traj.getPos(eval_t);
        if ((temp_pt - last_sample_pt).norm() < map_resolution * 0.5) {
          ROS_INFO("(temp_pt - last_sample_pt).norm(): %f, map_resolution * 0.8: %f, temp_pt: [%f, %f, %f], last_sample_pt: [%f, %f, %f], eval_t: %f", 
                    (temp_pt - last_sample_pt).norm(), map_resolution * 0.8, temp_pt.x(), temp_pt.y(), temp_pt.z(), last_sample_pt.x(), last_sample_pt.y(), last_sample_pt.z(), eval_t);
          continue;
        }
        if (grid_map_->getInflateOccupancyWithAllUnknownBigger(temp_pt)) {
          ROS_INFO("temp_pt in inflateOccupancy or unknown, stop searching local traj, temp_pt: [%f, %f, %f]", temp_pt.x(), temp_pt.y(), temp_pt.z());
          break;
        }
        last_local_traj_time_pos.emplace_back(eval_t, temp_pt);
        last_local_traj_vel.emplace_back(guide_pos_traj.getVel(eval_t).norm());
        last_sample_pt = temp_pt;
      }
      ROS_INFO("computeInitStateWithPolySearch5");
      ROS_INFO("last_local_traj_time_pos.size(): %lu", last_local_traj_time_pos.size());
      const auto hasObstacleInOneGridSphericalNeighborhood =
          [this](const Eigen::Vector3d &pt) -> bool {
        const Eigen::Vector3i center_id = grid_map_->pos2GlobalIdx(pt);
        constexpr int inf_step = 1;
        for (int dx = -inf_step; dx <= inf_step; ++dx)
          for (int dy = -inf_step; dy <= inf_step; ++dy)
            for (int dz = -inf_step; dz <= inf_step; ++dz)
            {
              if (inf_step > 1 && dx * dx + dy * dy + dz * dz > inf_step * inf_step)
                continue;
              const Eigen::Vector3d q_pos =
                  grid_map_->globalIdx2Pos(center_id + Eigen::Vector3i(dx, dy, dz));
              if (grid_map_->getInflateOccupancyWithAllUnknownInfBigger(q_pos))
                return true;
            }
        return false;
      };
      if (!last_local_traj_time_pos.empty()) {
        temp_pt = last_local_traj_time_pos.back().second;
        while (hasObstacleInOneGridSphericalNeighborhood(temp_pt) ||
               (temp_pt - start_pt).norm() > pp_.path_warmup_length) {
          ROS_INFO("warmup point blocked in 1-grid spherical neighborhood or too long, temp_pt: [%f, %f, %f], dist_to_start: %f",
                   temp_pt.x(), temp_pt.y(), temp_pt.z(), (temp_pt - start_pt).norm());
          last_local_traj_time_pos.pop_back();
          last_local_traj_vel.pop_back();
          if (last_local_traj_time_pos.empty()) {
              ROS_WARN("[DiffPlanner] all warmup traj points collide in inflated map");
              break;
          }
          temp_pt = last_local_traj_time_pos.back().second;
        }
      }
      ROS_INFO("computeInitStateWithPolySearch6");
      guide_stamp.clear();
      guide_path.clear();
      if (!last_local_traj_time_pos.empty()) {
        for (long unsigned int i = 0; i < last_local_traj_time_pos.size(); i++) {
          guide_path.push_back(last_local_traj_time_pos[i].second);
          guide_stamp.push_back(last_local_traj_time_pos[i].first - last_local_traj_time_pos.front().first);
          guide_path_end_vel = last_local_traj_vel[i];
        }
      } else {
        guide_path.push_back(start_pt);
        guide_stamp.push_back(0.0);
        last_local_traj_time_pos.emplace_back(passed_t_on_lctraj, start_pt);
        guide_path_end_vel = start_vel.norm();
      }
    }
    ROS_INFO("computeInitStateWithPolySearch7");

    if (guide_path.empty() || ((guide_path.front() - start_pt).norm() > 1e-2)) 
    {
      guide_path.insert(guide_path.begin(), start_pt);
      guide_stamp.insert(guide_stamp.begin(), 0.0);
    }

    const Eigen::Vector3d map_low = grid_map_->getLocalMapLowBound();
    const Eigen::Vector3d map_up = grid_map_->getLocalMapUpBound();
    const double map_radius_x = (map_up.x() - map_low.x()) * 0.5;
    const double map_radius_y = (map_up.y() - map_low.y()) * 0.5;
    const double guide_path_length = computePathLength(guide_path);
    const double guide_use_length = std::max(0.0, pp_.avoid_unknown_path_length - guide_path_length);
    const double astar_search_dist_max =
        std::max(0.0, std::min(map_radius_x, map_radius_y) - guide_path_length - 2.0 * map_resolution);

    ROS_INFO("computeInitStateWithPolySearch8");
    std::vector<Eigen::Vector3d> a_star_path;
    ROS_INFO("guide_path.back(): [%f, %f, %f]", guide_path.back().x(), guide_path.back().y(), guide_path.back().z());
    ROS_INFO("local_target_pt: [%f, %f, %f]", local_target_pt.x(), local_target_pt.y(), local_target_pt.z());
    ROS_INFO("A* search dist max: %.3f (map xy radius [%.3f, %.3f]), guide use length: %.3f",
             astar_search_dist_max, map_radius_x, map_radius_y, guide_use_length);
    const double dist_to_target = (start_pt - local_target_pt).norm();
    const bool astar_ignore_unknown = dist_to_target < 2.0 || !pp_.use_unknown;
    PATH_SEARCH_RET ret =
        path_searcher_.PathSearch(astar_search_dist_max, guide_path.back(), local_target_pt, guide_use_length, astar_ignore_unknown, true);
    if (ret == PATH_SEARCH_RET::REACH_GOAL || ret == PATH_SEARCH_RET::REACH_FAR) 
    {
      ROS_INFO("PathSearch for new path succeed by %s", PATH_SEARCH_RET_STR.at(ret).c_str());
      a_star_path = path_searcher_.getPath();

      if (visualization_ && !a_star_path.empty())
      {
        std::vector<Eigen::Vector3d> astar_vis_path;
        astar_vis_path.reserve(a_star_path.size() + 1);
        astar_vis_path.push_back(guide_path.back());
        astar_vis_path.insert(astar_vis_path.end(), a_star_path.begin(), a_star_path.end());
        visualization_->displayAStarList({astar_vis_path}, 0);
      }

      std::vector<Eigen::Vector3d> guide_path_tmp = guide_path;
      double time_stamp = guide_stamp.back();
      double remain_len = guide_use_length;
      Eigen::Vector3d cur_pt = guide_path.back();
      size_t append_cnt = 0;

      for (size_t i = 0; i < a_star_path.size() && remain_len > 1e-6; ++i)
      {
        const Eigen::Vector3d &next_pt = a_star_path[i];
        const double seg_len = (next_pt - cur_pt).norm();
        if (seg_len < 1e-6)
          continue;

        if (seg_len <= remain_len + 1e-6)
        {
          if ((next_pt - guide_path.back()).norm() > 1e-3)
          {
            time_stamp += seg_len / pp_.max_vel_;
            guide_path.emplace_back(next_pt);
            guide_stamp.emplace_back(time_stamp);
            ++append_cnt;
          }
          remain_len -= seg_len;
          cur_pt = next_pt;
        }
        else
        {
          const Eigen::Vector3d clipped_pt = cur_pt + (remain_len / seg_len) * (next_pt - cur_pt);
          time_stamp += remain_len / pp_.max_vel_;
          guide_path.emplace_back(clipped_pt);
          guide_stamp.emplace_back(time_stamp);
          ++append_cnt;
          remain_len = 0.0;
          break;
        }
      }

      // touch_goal only when A* reached goal AND the clipped guide path actually ends at local_target.
      touch_goal_ = false;
      if (ret == PATH_SEARCH_RET::REACH_GOAL)
      {
        const double touch_goal_eps = std::max(2.0 * map_resolution, 1e-2);
        touch_goal_ = (guide_path.back() - local_target_pt).norm() < touch_goal_eps;
      }

      ROS_INFO("path connected, guide_path size: %lu, a_star_path size: %lu, appended: %lu, warmup_path size: %lu, touch_goal: %d",
               guide_path.size(), a_star_path.size(), append_cnt, guide_path_tmp.size(), touch_goal_);
    } 
    else 
    {
      ROS_WARN("PathSearch for init path failed, the error info: %s", PATH_SEARCH_RET_STR.at(ret).c_str());
      return false;
    }

    if (visualization_)
      visualization_->displayGuidePathList(guide_path, 0.12, 0);

    last_search_path_ = guide_path;

    ROS_INFO("grid_map_ occupancy: %d", grid_map_->getOccupancy(Eigen::Vector3d(0.3, 0.3, 1.1)));

    init_sfc_.clear();
    Eigen::Vector3d shifted_sfc_start_pt = Eigen::Vector3d::Zero();
    ROS_INFO("computeInitStateWithPolySearch9");
    if (!corridor_gen_->SearchPolytopeOnPath(guide_path, init_sfc_, shifted_sfc_start_pt, true))
    {
      ROS_WARN("[DiffPlanner] SearchPolytopeOnPath failed on guide_path with size %lu", guide_path.size());
      return false;
    }
    ROS_INFO("[DiffPlanner] Generated %lu corridor polytopes from guide_path size %lu",
             init_sfc_.size(), guide_path.size());

    if (!corridor_gen::SimplifySFC(guide_path.front(), guide_path.back(), init_sfc_))
    {
      ROS_WARN("[DiffPlanner] SimplifySFC failed for guide_path front->back (local_target may be beyond corridor when REACH_FAR)");
      return false;
    }
    ROS_INFO("[DiffPlanner] After SimplifySFC: %lu corridor polytopes", init_sfc_.size());

    const int sfc_piece_num = static_cast<int>(init_sfc_.size());
    if (sfc_piece_num < 1)
    {
      ROS_WARN("[DiffPlanner] Empty SFC after SearchPolytopeOnPath");
      return false;
    }
    ROS_INFO("computeInitStateWithPolySearch10");
    /* init MJO pieces:
     * - 1 corridor: always 2 traj pieces, both use hPolyIdx=0 (LBFGS needs inner spatial DOF).
     * - touch_goal: tail = guide_path.back(), no extra piece to local_target.
     * - !touch_goal, multi corridor: tail pieces wp0->local_target with hPolyIdx=-1;
     *   dist >= avg_junc_dist: insert by avg_junc_dist;
     *   polyTraj_piece_length <= dist < avg_junc_dist: 2 tail pieces (midpoint);
     *   dist < polyTraj_piece_length: 1 tail piece. */

    const Eigen::Vector3d wp0 = guide_path.back();
    const Eigen::Vector3d wp1 = local_target_pt;
    const Eigen::Vector3d wp1_vel = local_target_vel;

    std::vector<Eigen::Vector3d> sfc_junctions;
    sfc_junctions.reserve(std::max(0, sfc_piece_num - 1));
    for (int i = 0; i < sfc_piece_num - 1; ++i)
    {
      const corridor_gen::Polytope overlap = init_sfc_[i].CrossWith(init_sfc_[i + 1]);
      Eigen::Vector3d junction;
      const double depth = corridor_gen::findInteriorDist(overlap.GetPlanes(), junction);
      if (depth <= corridor_gen::kEpsilon || std::isinf(depth))
      {
        if (init_sfc_[i].HaveSeedLine() && init_sfc_[i + 1].HaveSeedLine())
          junction = 0.5 * (init_sfc_[i].seed_line_.second + init_sfc_[i + 1].seed_line_.first);
        else
          junction = 0.5 * (guide_path[std::min(i, static_cast<int>(guide_path.size()) - 1)] +
                            guide_path[std::min(i + 1, static_cast<int>(guide_path.size()) - 1)]);
        ROS_WARN("[DiffPlanner] SFC junction %d uses fallback waypoint", i);
      }
      sfc_junctions.push_back(junction);
    }

    double avg_junc_dist = pp_.polyTraj_piece_length;
    if (sfc_junctions.size() >= 2)
    {
      double junc_dist_sum = 0.0;
      for (size_t i = 1; i < sfc_junctions.size(); ++i)
        junc_dist_sum += (sfc_junctions[i] - sfc_junctions[i - 1]).norm();
      avg_junc_dist = junc_dist_sum / static_cast<double>(sfc_junctions.size() - 1);
    }
    else if (sfc_junctions.size() == 1)
    {
      avg_junc_dist = (sfc_junctions[0] - start_pt).norm();
      if (avg_junc_dist < 1e-3)
        avg_junc_dist = pp_.polyTraj_piece_length;
    }

    const double wp0_wp1_dist = (wp1 - wp0).norm();
    std::vector<Eigen::Vector3d> tail_inner_pts;
    if (!touch_goal_ && sfc_piece_num > 1)
    {
      if (wp0_wp1_dist < pp_.polyTraj_piece_length)
      {
        // short tail: single piece wp0->wp1
      }
      else if (wp0_wp1_dist < avg_junc_dist || avg_junc_dist <= 1e-6)
      {
        // dist in [polyTraj_piece_length, avg_junc_dist): split into 2 tail pieces
        tail_inner_pts.push_back(0.5 * (wp0 + wp1));
      }
      else
      {
        Eigen::Vector3d wp_dir = Eigen::Vector3d::Zero();
        if (wp0_wp1_dist > 1e-6)
          wp_dir = (wp1 - wp0) / wp0_wp1_dist;
        const int n = static_cast<int>(wp0_wp1_dist / avg_junc_dist) - 1; // 这个地方不合理，后面的按照polyTraj_piece_length划分长度才合理
        tail_inner_pts.reserve(n);
        for (int k = 1; k <= n; ++k)
          tail_inner_pts.push_back(wp0 + k * avg_junc_dist * wp_dir);
      }
    }

    const int tail_piece_num = (touch_goal_ || sfc_piece_num == 1) ? 0 : (static_cast<int>(tail_inner_pts.size()) + 1);
    const int piece_nums = (sfc_piece_num == 1)
                               ? 2
                               : (touch_goal_ ? sfc_piece_num : (sfc_piece_num + tail_piece_num));

    Eigen::MatrixXd innerPs(3, std::max(0, piece_nums - 1));
    std::vector<Eigen::Vector3d> path_vertices;
    path_vertices.reserve(piece_nums + 1);
    path_vertices.push_back(start_pt);

    for (int i = 0; i < sfc_piece_num - 1; ++i)
    {
      innerPs.col(i) = sfc_junctions[i];
      path_vertices.push_back(sfc_junctions[i]);
    }

    Eigen::Vector3d tail_pos;
    Eigen::Vector3d tail_vel;
    if (sfc_piece_num == 1)
    {
      const int inner_idx = guide_path.size() >= 2
                                ? static_cast<int>(guide_path.size()) - 2
                                : 0;
      const Eigen::Vector3d inner_wp =
          guide_path.size() >= 2 ? guide_path[inner_idx] : 0.5 * (start_pt + wp0);
      innerPs.col(0) = inner_wp;
      path_vertices.push_back(inner_wp);
      tail_pos = touch_goal_ ? wp0 : wp1;
      tail_vel = wp1_vel;
      path_vertices.push_back(tail_pos);
    }
    else if (touch_goal_)
    {
      tail_pos = wp0;
      tail_vel = wp1_vel;
      path_vertices.push_back(wp0);
    }
    else
    {
      innerPs.col(sfc_piece_num - 1) = wp0;
      path_vertices.push_back(wp0);

      for (size_t k = 0; k < tail_inner_pts.size(); ++k)
      {
        innerPs.col(sfc_piece_num + static_cast<int>(k)) = tail_inner_pts[k];
        path_vertices.push_back(tail_inner_pts[k]);
      }

      tail_pos = wp1;
      tail_vel = wp1_vel;
      path_vertices.push_back(wp1);
    }
    ROS_INFO("computeInitStateWithPolySearch11");
    constexpr double kMinPieceDur = 0.01;
    Eigen::VectorXd piece_dur_vec(piece_nums);
    for (int i = 0; i < piece_nums; ++i) {
      piece_dur_vec(i) = (i == 0 || i == piece_nums - 1) ? std::max(kMinPieceDur, (path_vertices[i + 1] - path_vertices[i]).norm() / (pp_.max_vel_ * 0.5)) : 
                          std::max(kMinPieceDur, (path_vertices[i + 1] - path_vertices[i]).norm() / (pp_.max_vel_));
    }

    headState << start_pt, start_vel, start_acc;
    tailState << tail_pos, tail_vel, Eigen::Vector3d::Zero();
    initMJO.reset(headState, tailState, piece_nums);
    initMJO.generate(innerPs, piece_dur_vec);

    sfc_init_data_.clear();
    sfc_init_data_.sfc_piece_num = sfc_piece_num;
    sfc_init_data_.hPolyIdx.resize(piece_nums);
    sfc_init_data_.hPolytopes.resize(sfc_piece_num);
    for (int i = 0; i < sfc_piece_num; ++i)
    {
      sfc_init_data_.hPolytopes[i] = init_sfc_[i].GetPlanes();
      const Eigen::ArrayXd norms = sfc_init_data_.hPolytopes[i].leftCols<3>().rowwise().norm();
      sfc_init_data_.hPolytopes[i].array().colwise() /= norms;
      sfc_init_data_.hPolyIdx(i) = i;
    }
    if (sfc_piece_num == 1 && piece_nums == 2)
    {
      sfc_init_data_.hPolyIdx(0) = 0;
      sfc_init_data_.hPolyIdx(1) = 0;
    }
    else if (!touch_goal_)
    {
      for (int i = sfc_piece_num; i < piece_nums; ++i)
        sfc_init_data_.hPolyIdx(i) = -1;
    }
    ploy_traj_opt_->setInitSfcCorridor(sfc_init_data_);

    if (visualization_)
    {
      std::vector<std::pair<Eigen::Vector3d, Eigen::Vector3d>> seed_lines;
      seed_lines.reserve(init_sfc_.size());
      for (const auto &poly : init_sfc_)
      {
        if (poly.HaveSeedLine())
          seed_lines.emplace_back(poly.seed_line_.first, poly.seed_line_.second);
      }
      visualization_->displaySfcCorridor(sfc_init_data_.hPolytopes, seed_lines,
                                         ploy_traj_opt_->getInitSfcCorridor().waypoint_attractor, 0);
    }

    double init_sfc_violation = 0.0;
    ploy_traj_opt_->checkSfcCorridorFeasibility(initMJO, init_sfc_violation);
    if (init_sfc_violation > 1e-3)
      ROS_WARN("[DiffPlanner] initMJO initial SFC violation max=%.3f", init_sfc_violation);

    ROS_INFO("[DiffPlanner] initMJO: %d pieces (%s), tail dist=%.2f, last dt=%.2f",
             piece_nums,
             (sfc_piece_num == 1) ? "single_sfc_2pc"
                                  : (touch_goal_ ? "touch_goal" : "with tail to local_target"),
             (tail_pos - path_vertices[path_vertices.size() - 2]).norm(),
             piece_dur_vec(piece_nums - 1));

    return true;
  }

  bool DiffPlannerManager::computeInitState(
      const Eigen::Vector3d &start_pt, const Eigen::Vector3d &start_vel, const Eigen::Vector3d &start_acc,
      const Eigen::Vector3d &local_target_pt, const Eigen::Vector3d &local_target_vel,
      const bool flag_polyInit, const bool flag_randomPolyTraj, const double &ts,
      poly_traj::MinJerkOpt &initMJO)
  {

    static bool flag_first_call = true;

    if (flag_first_call || flag_polyInit) /*** case 1: polynomial initialization ***/
    {
      flag_first_call = false;

      /* basic params */
      Eigen::Matrix3d headState, tailState;
      Eigen::MatrixXd innerPs;
      Eigen::VectorXd piece_dur_vec;
      int piece_nums;
      constexpr double init_of_init_totaldur = 2.0;
      headState << start_pt, start_vel, start_acc;
      tailState << local_target_pt, local_target_vel, Eigen::Vector3d::Zero();

      /* determined or random inner point */
      if (!flag_randomPolyTraj)
      {
        if (innerPs.cols() != 0)
        {
          ROS_ERROR("innerPs.cols() != 0");
        }

        piece_nums = 1;
        piece_dur_vec.resize(1);
        piece_dur_vec(0) = init_of_init_totaldur;
      }
      else
      {
        Eigen::Vector3d horizen_dir = ((start_pt - local_target_pt).cross(Eigen::Vector3d(0, 0, 1))).normalized();
        Eigen::Vector3d vertical_dir = ((start_pt - local_target_pt).cross(horizen_dir)).normalized();
        innerPs.resize(3, 1);
        innerPs = (start_pt + local_target_pt) / 2 +
                  (((double)rand()) / RAND_MAX - 0.5) *
                      (start_pt - local_target_pt).norm() *
                      horizen_dir * 0.8 * (-0.978 / (continous_failures_count_ + 0.989) + 0.989) +
                  (((double)rand()) / RAND_MAX - 0.5) *
                      (start_pt - local_target_pt).norm() *
                      vertical_dir * 0.4 * (-0.978 / (continous_failures_count_ + 0.989) + 0.989);

        piece_nums = 2;
        piece_dur_vec.resize(2);
        piece_dur_vec = Eigen::Vector2d(init_of_init_totaldur / 2, init_of_init_totaldur / 2);
      }

      /* generate the init of init trajectory */
      initMJO.reset(headState, tailState, piece_nums);
      initMJO.generate(innerPs, piece_dur_vec);
      poly_traj::Trajectory initTraj = initMJO.getTraj();

      /* generate the real init trajectory */
      piece_nums = round((headState.col(0) - tailState.col(0)).norm() / pp_.polyTraj_piece_length);
      if (piece_nums < 2)
        piece_nums = 2;
      double piece_dur = init_of_init_totaldur / (double)piece_nums;
      piece_dur_vec.resize(piece_nums);
      piece_dur_vec.setConstant(piece_dur);
      innerPs.resize(3, piece_nums - 1);
      int id = 0;
      double t_s = piece_dur, t_e = init_of_init_totaldur - piece_dur / 2;
      for (double t = t_s; t < t_e; t += piece_dur)
      {
        innerPs.col(id++) = initTraj.getPos(t);
      }
      if (id != piece_nums - 1)
      {
        ROS_ERROR("Should not happen! x_x");
        return false;
      }
      initMJO.reset(headState, tailState, piece_nums);
      initMJO.generate(innerPs, piece_dur_vec);
    }
    else /*** case 2: initialize from previous optimal trajectory ***/
    {
      if (traj_.global_traj.last_glb_t_of_lc_tgt < 0.0)
      {
        ROS_ERROR("You are initialzing a trajectory from a previous optimal trajectory, but no previous trajectories up to now.");
        return false;
      }

      /* the trajectory time system is a little bit complicated... */
      double passed_t_on_lctraj = getReplanPassedTimeOnLocalTraj();
      double t_to_lc_end = traj_.local_traj.duration - passed_t_on_lctraj;
      if (t_to_lc_end < 0)
      {
        ROS_INFO("t_to_lc_end < 0, exit and wait for another call.");
        return false;
      }
      double t_to_lc_tgt = t_to_lc_end +
                           (traj_.global_traj.glb_t_of_lc_tgt - traj_.global_traj.last_glb_t_of_lc_tgt);
      int piece_nums = ceil((start_pt - local_target_pt).norm() / pp_.polyTraj_piece_length);
      if (piece_nums < 2)
        piece_nums = 2;

      Eigen::Matrix3d headState, tailState;
      Eigen::MatrixXd innerPs(3, piece_nums - 1);
      Eigen::VectorXd piece_dur_vec = Eigen::VectorXd::Constant(piece_nums, t_to_lc_tgt / piece_nums);
      headState << start_pt, start_vel, start_acc;
      tailState << local_target_pt, local_target_vel, Eigen::Vector3d::Zero();

      double t = piece_dur_vec(0);
      for (int i = 0; i < piece_nums - 1; ++i)
      {
        if (t < t_to_lc_end)
        {
          innerPs.col(i) = traj_.local_traj.traj.getPos(t + passed_t_on_lctraj);
        }
        else if (t <= t_to_lc_tgt)
        {
          double glb_t = t - t_to_lc_end + traj_.global_traj.last_glb_t_of_lc_tgt - traj_.global_traj.global_start_time;
          innerPs.col(i) = traj_.global_traj.traj.getPos(glb_t);
        }
        else
        {
          ROS_ERROR("Should not happen! x_x 0x88 t=%.2f, t_to_lc_end=%.2f, t_to_lc_tgt=%.2f", t, t_to_lc_end, t_to_lc_tgt);
        }

        t += piece_dur_vec(i + 1);
      }

      initMJO.reset(headState, tailState, piece_nums);
      initMJO.generate(innerPs, piece_dur_vec);
    }

    return true;
  }

  void DiffPlannerManager::getLocalTarget(
      const double planning_horizen, const Eigen::Vector3d &start_pt,
      const Eigen::Vector3d &global_end_pt, Eigen::Vector3d &local_target_pos,
      Eigen::Vector3d &local_target_vel, bool &catch_goal)
  {
    double t;
    catch_goal = false;

    traj_.global_traj.last_glb_t_of_lc_tgt = traj_.global_traj.glb_t_of_lc_tgt;

    double t_step = planning_horizen / 20 / pp_.max_vel_;
    // double dist_min = 9999, dist_min_t = 0.0;
    for (t = traj_.global_traj.glb_t_of_lc_tgt;
         t < (traj_.global_traj.global_start_time + traj_.global_traj.duration);
         t += t_step)
    {
      Eigen::Vector3d pos_t = traj_.global_traj.traj.getPos(t - traj_.global_traj.global_start_time);
      double dist = (pos_t - start_pt).norm();

      if (dist >= planning_horizen)
      {
        local_target_pos = pos_t;
        traj_.global_traj.glb_t_of_lc_tgt = t;
        break;
      }
    }

    if ((t - traj_.global_traj.global_start_time) >= traj_.global_traj.duration - 1e-5) // Last global point
    {
      local_target_pos = global_end_pt;
      traj_.global_traj.glb_t_of_lc_tgt = traj_.global_traj.global_start_time + traj_.global_traj.duration;
      catch_goal = true;
    }

    if ((global_end_pt - local_target_pos).norm() < (pp_.max_vel_ * pp_.max_vel_) / (2 * pp_.max_acc_))
    {
      local_target_vel = Eigen::Vector3d::Zero();
    }
    else
    {
      local_target_vel = traj_.global_traj.traj.getVel(t - traj_.global_traj.global_start_time);
    }
  }

  bool DiffPlannerManager::setLocalTrajFromOpt(const poly_traj::MinJerkOpt &opt, const bool catch_goal)
  {
    poly_traj::Trajectory new_traj = opt.getTraj();
    poly_traj::Trajectory committed_traj = new_traj;
    double start_WT = ros::Time::now().toSec();

    if (replan_stitch_.enable)
    {
      start_WT = replan_stitch_.replan_start_WT;
      if (!stitchReplanTrajectory(traj_.local_traj.traj, new_traj, replan_stitch_, committed_traj))
      {
        ROS_WARN("[DiffPlanner] stitchReplanTrajectory failed, use optimized segment only.");
        committed_traj = new_traj;
      }
      else
      {
        ROS_INFO("[DiffPlanner] Stitched replan: prefix TT [%.3f, %.3f], opt dur %.3f, total dur %.3f",
                 replan_stitch_.replan_process_start_TT, replan_stitch_.replan_state_TT,
                 new_traj.getTotalDuration(), committed_traj.getTotalDuration());
      }
    }

    ROS_INFO("opt traj dur: %f, start_pos: [%f, %f, %f], end_pos: [%f, %f, %f]", committed_traj.getTotalDuration(),
             committed_traj.getPos(0).x(), committed_traj.getPos(0).y(), committed_traj.getPos(0).z(),
             committed_traj.getPos(committed_traj.getTotalDuration()).x(),
             committed_traj.getPos(committed_traj.getTotalDuration()).y(),
             committed_traj.getPos(committed_traj.getTotalDuration()).z());
    Eigen::MatrixXd cps = opt.getInitConstraintPoints(getCpsNumPrePiece());
    PtsChk_t pts_to_check;
    int id_cps_end = ConstraintPoints::two_thirds_id(cps, catch_goal);
    if (committed_traj.getPieceNum() > new_traj.getPieceNum())
    {
      const int cps_num = getCpsNumPrePiece();
      id_cps_end = std::max(id_cps_end, cps_num * committed_traj.getPieceNum() * 2 / 3);
    }
    bool ret = ploy_traj_opt_->computePointsToCheck(committed_traj, id_cps_end, pts_to_check);
    if (ret && pts_to_check.size() >= 1 && pts_to_check.back().size() >= 1)
    {
      traj_.setLocalTraj(committed_traj, pts_to_check, start_WT);
      clearReplanStitch();
    }

    return ret;
  }

  void DiffPlannerManager::beginReplanStitch(const double replan_start_WT, const double t_cur,
                                             const double t_replan_state)
  {
    replan_stitch_.enable = true;
    replan_stitch_.replan_start_WT = replan_start_WT;
    replan_stitch_.replan_process_start_TT = t_cur;
    replan_stitch_.replan_state_TT = t_replan_state;
  }

  void DiffPlannerManager::clearReplanStitch()
  {
    replan_stitch_.enable = false;
    replan_stitch_.replan_start_WT = 0.0;
    replan_stitch_.replan_process_start_TT = 0.0;
    replan_stitch_.replan_state_TT = 0.0;
  }

  double DiffPlannerManager::getReplanPassedTimeOnLocalTraj() const
  {
    if (replan_stitch_.enable)
      return replan_stitch_.replan_state_TT;
    return ros::Time::now().toSec() - traj_.local_traj.start_time;
  }

  bool DiffPlannerManager::EmergencyStop(Eigen::Vector3d stop_pos)
  {
    auto ZERO = Eigen::Vector3d::Zero();
    Eigen::Matrix<double, 3, 3> headState, tailState;
    headState << stop_pos, ZERO, ZERO;
    tailState = headState;
    poly_traj::MinJerkOpt stopMJO;
    stopMJO.reset(headState, tailState, 2);
    stopMJO.generate(stop_pos, Eigen::Vector2d(1.0, 1.0));

    setLocalTrajFromOpt(stopMJO, false);

    return true;
  }

  bool DiffPlannerManager::checkCollision(int drone_id)
  {
    if (traj_.local_traj.start_time < 1e9) // It means my first planning has not started
      return false;
    if (traj_.swarm_traj[drone_id].drone_id != drone_id) // The trajectory is invalid
      return false;

    double my_traj_start_time = traj_.local_traj.start_time;
    double other_traj_start_time = traj_.swarm_traj[drone_id].start_time;

    double t_start = max(my_traj_start_time, other_traj_start_time);
    double t_end = min(my_traj_start_time + traj_.local_traj.duration * 2 / 3,
                       other_traj_start_time + traj_.swarm_traj[drone_id].duration);

    for (double t = t_start; t < t_end; t += 0.03)
    {
      if ((traj_.local_traj.traj.getPos(t - my_traj_start_time) -
           traj_.swarm_traj[drone_id].traj.getPos(t - other_traj_start_time))
              .norm() < (getSwarmClearance() + traj_.swarm_traj[drone_id].des_clearance) )
      {
        return true;
      }
    }

    return false;
  }

  bool DiffPlannerManager::planGlobalTrajWaypoints(
      const Eigen::Vector3d &start_pos, const Eigen::Vector3d &start_vel,
      const Eigen::Vector3d &start_acc, const std::vector<Eigen::Vector3d> &waypoints,
      const Eigen::Vector3d &end_vel, const Eigen::Vector3d &end_acc)
  {

    poly_traj::MinJerkOpt globalMJO;
    Eigen::Matrix<double, 3, 3> headState, tailState;
    headState << start_pos, start_vel, start_acc;
    tailState << waypoints.back(), end_vel, end_acc;
    Eigen::MatrixXd innerPts;

    if (waypoints.size() > 1)
    {

      innerPts.resize(3, waypoints.size() - 1);
      for (int i = 0; i < (int)waypoints.size() - 1; ++i)
      {
        innerPts.col(i) = waypoints[i];
      }
    }
    else
    {
      if (innerPts.size() != 0)
      {
        ROS_ERROR("innerPts.size() != 0");
      }
    }

    globalMJO.reset(headState, tailState, waypoints.size());

    double des_vel = pp_.max_vel_ / 1.5;
    Eigen::VectorXd time_vec(waypoints.size());

    for (int j = 0; j < 2; ++j)
    {
      for (size_t i = 0; i < waypoints.size(); ++i)
      {
        time_vec(i) = (i == 0) ? (waypoints[0] - start_pos).norm() / des_vel
                               : (waypoints[i] - waypoints[i - 1]).norm() / des_vel;
      }

      globalMJO.generate(innerPts, time_vec);

      if (globalMJO.getTraj().getMaxVelRate() < pp_.max_vel_ ||
          start_vel.norm() > pp_.max_vel_ ||
          end_vel.norm() > pp_.max_vel_)
      {
        break;
      }

      if (j == 2)
      {
        ROS_WARN("Global traj MaxVel = %f > set_max_vel", globalMJO.getTraj().getMaxVelRate());
        cout << "headState=" << endl
             << headState << endl;
        cout << "tailState=" << endl
             << tailState << endl;
      }

      des_vel /= 1.5;
    }

    auto time_now = ros::Time::now();
    traj_.setGlobalTraj(globalMJO.getTraj(), time_now.toSec());

    return true;
  }

} // namespace diff_planner
