#ifndef _TRAJ_STITCH_H_
#define _TRAJ_STITCH_H_

#include <optimizer/poly_traj_utils.hpp>

namespace diff_planner
{

  struct ReplanStitchInfo
  {
    bool enable{false};
    double replan_start_WT{0.0};
    double replan_process_start_TT{0.0};
    double replan_state_TT{0.0};
  };

  inline bool stitchReplanTrajectory(const poly_traj::Trajectory &old_traj,
                                     const poly_traj::Trajectory &new_traj,
                                     const ReplanStitchInfo &stitch,
                                     poly_traj::Trajectory &out_traj)
  {
    if (!stitch.enable)
    {
      out_traj = new_traj;
      return true;
    }

    poly_traj::Trajectory prefix;
    if (!old_traj.getPartialTrajectoryByTime(stitch.replan_process_start_TT,
                                             stitch.replan_state_TT, prefix))
    {
      return false;
    }

    out_traj = prefix;
    out_traj.append(new_traj);
    return true;
  }

} // namespace diff_planner

#endif
