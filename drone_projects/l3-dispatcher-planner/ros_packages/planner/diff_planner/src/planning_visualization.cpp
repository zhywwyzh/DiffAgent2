#include <traj_utils/planning_visualization.h>

#include <cmath>

using std::cout;
using std::endl;
namespace diff_planner
{
namespace
{
constexpr double kSfcEps = 1e-4;

bool pointInHPoly(const Eigen::Matrix<double, Eigen::Dynamic, 4> &hPoly,
                  const Eigen::Vector3d &p, const double eps)
{
  for (int i = 0; i < hPoly.rows(); ++i)
  {
    if (hPoly(i, 0) * p(0) + hPoly(i, 1) * p(1) + hPoly(i, 2) * p(2) + hPoly(i, 3) > eps)
      return false;
  }
  return true;
}

double planeDist(const Eigen::RowVector4d &plane, const Eigen::Vector3d &p)
{
  return std::abs(plane(0) * p(0) + plane(1) * p(1) + plane(2) * p(2) + plane(3));
}

bool solvePlaneTriple(const Eigen::RowVector4d &p0, const Eigen::RowVector4d &p1,
                      const Eigen::RowVector4d &p2, Eigen::Vector3d &v)
{
  Eigen::Matrix3d A;
  A.row(0) = p0.head<3>();
  A.row(1) = p1.head<3>();
  A.row(2) = p2.head<3>();
  if (std::abs(A.determinant()) < 1e-9)
    return false;
  Eigen::Vector3d b(-p0(3), -p1(3), -p2(3));
  v = A.colPivHouseholderQr().solve(b);
  return v.allFinite();
}

bool enumeratePolytopeVertices(const Eigen::Matrix<double, Eigen::Dynamic, 4> &hPoly,
                               std::vector<Eigen::Vector3d> &verts)
{
  verts.clear();
  const int n = static_cast<int>(hPoly.rows());
  if (n < 4)
    return false;

  for (int i = 0; i < n; ++i)
  {
    for (int j = i + 1; j < n; ++j)
    {
      for (int k = j + 1; k < n; ++k)
      {
        Eigen::Vector3d v;
        if (!solvePlaneTriple(hPoly.row(i), hPoly.row(j), hPoly.row(k), v))
          continue;
        if (!pointInHPoly(hPoly, v, kSfcEps))
          continue;

        bool duplicated = false;
        for (const auto &u : verts)
        {
          if ((u - v).norm() < kSfcEps)
          {
            duplicated = true;
            break;
          }
        }
        if (!duplicated)
          verts.push_back(v);
      }
    }
  }
  return verts.size() >= 4;
}

int sharedFaceCount(const Eigen::Matrix<double, Eigen::Dynamic, 4> &hPoly,
                    const Eigen::Vector3d &a, const Eigen::Vector3d &b)
{
  int count = 0;
  for (int f = 0; f < hPoly.rows(); ++f)
  {
    if (planeDist(hPoly.row(f), a) < kSfcEps && planeDist(hPoly.row(f), b) < kSfcEps)
      ++count;
  }
  return count;
}

Eigen::Vector4d sfcPolyColor(const int idx, const int total)
{
  const double hue = (total <= 1) ? 0.58 : static_cast<double>(idx) / total;
  const double r = 0.5 + 0.5 * std::cos(6.28318 * (hue + 0.0));
  const double g = 0.5 + 0.5 * std::cos(6.28318 * (hue + 0.33));
  const double b = 0.5 + 0.5 * std::cos(6.28318 * (hue + 0.67));
  return Eigen::Vector4d(r, g, b, 0.85);
}

geometry_msgs::Point toRosPoint(const Eigen::Vector3d &p)
{
  geometry_msgs::Point pt;
  pt.x = p(0);
  pt.y = p(1);
  pt.z = p(2);
  return pt;
}
}  // namespace
  PlanningVisualization::PlanningVisualization(ros::NodeHandle &nh)
  {
    node = nh;

    goal_point_pub = nh.advertise<visualization_msgs::Marker>("goal_point", 2);
    global_list_pub = nh.advertise<visualization_msgs::Marker>("global_list", 2);
    guide_path_pub = nh.advertise<visualization_msgs::Marker>("guide_path", 2);
    init_list_pub = nh.advertise<visualization_msgs::Marker>("init_list", 2);
    optimal_list_pub = nh.advertise<visualization_msgs::Marker>("optimal_list", 2);
    failed_list_pub = nh.advertise<visualization_msgs::Marker>("failed_list", 2);
    a_star_list_pub = nh.advertise<visualization_msgs::Marker>("a_star_list", 20);
    sfc_corridor_pub = nh.advertise<visualization_msgs::MarkerArray>("sfc_corridor", 2);

    // intermediate_pt0_pub = nh.advertise<visualization_msgs::Marker>("pt0_dur_opt", 10);
    // intermediate_grad0_pub = nh.advertise<visualization_msgs::MarkerArray>("grad0_dur_opt", 10);
    // intermediate_pt1_pub = nh.advertise<visualization_msgs::Marker>("pt1_dur_opt", 10);
    // intermediate_grad1_pub = nh.advertise<visualization_msgs::MarkerArray>("grad1_dur_opt", 10);
    // intermediate_grad_smoo_pub = nh.advertise<visualization_msgs::MarkerArray>("smoo_grad_dur_opt", 10);
    // intermediate_grad_dist_pub = nh.advertise<visualization_msgs::MarkerArray>("dist_grad_dur_opt", 10);
    // intermediate_grad_feas_pub = nh.advertise<visualization_msgs::MarkerArray>("feas_grad_dur_opt", 10);
    // intermediate_grad_swarm_pub = nh.advertise<visualization_msgs::MarkerArray>("swarm_grad_dur_opt", 10);
  }

  // // real ids used: {id, id+1000}
  void PlanningVisualization::displayMarkerList(ros::Publisher &pub, const vector<Eigen::Vector3d> &list, double scale,
                                                Eigen::Vector4d color, int id, bool show_sphere /* = true */ )
  {
    visualization_msgs::Marker sphere, line_strip;
    sphere.header.frame_id = line_strip.header.frame_id = "world";
    sphere.header.stamp = line_strip.header.stamp = ros::Time::now();
    sphere.type = visualization_msgs::Marker::SPHERE_LIST;
    line_strip.type = visualization_msgs::Marker::LINE_STRIP;
    sphere.action = line_strip.action = visualization_msgs::Marker::ADD;
    sphere.id = id;
    line_strip.id = id + 1000;

    sphere.pose.orientation.w = line_strip.pose.orientation.w = 1.0;
    sphere.color.r = line_strip.color.r = color(0);
    sphere.color.g = line_strip.color.g = color(1);
    sphere.color.b = line_strip.color.b = color(2);
    sphere.color.a = line_strip.color.a = color(3) > 1e-5 ? color(3) : 1.0;
    sphere.scale.x = scale;
    sphere.scale.y = scale;
    sphere.scale.z = scale;
    line_strip.scale.x = scale / 2;
    geometry_msgs::Point pt;
    for (int i = 0; i < int(list.size()); i++)
    {
      pt.x = list[i](0);
      pt.y = list[i](1);
      pt.z = list[i](2);
      if (show_sphere) sphere.points.push_back(pt);
      line_strip.points.push_back(pt);
    }
    if (show_sphere) pub.publish(sphere);
    pub.publish(line_strip);
  }

  // real ids used: {id, id+1}
  void PlanningVisualization::generatePathDisplayArray(visualization_msgs::MarkerArray &array,
                                                       const vector<Eigen::Vector3d> &list, double scale, Eigen::Vector4d color, int id)
  {
    visualization_msgs::Marker sphere, line_strip;
    sphere.header.frame_id = line_strip.header.frame_id = "world";
    sphere.header.stamp = line_strip.header.stamp = ros::Time::now();
    sphere.type = visualization_msgs::Marker::SPHERE_LIST;
    line_strip.type = visualization_msgs::Marker::LINE_STRIP;
    sphere.action = line_strip.action = visualization_msgs::Marker::ADD;
    sphere.id = id;
    line_strip.id = id + 1;

    sphere.pose.orientation.w = line_strip.pose.orientation.w = 1.0;
    sphere.color.r = line_strip.color.r = color(0);
    sphere.color.g = line_strip.color.g = color(1);
    sphere.color.b = line_strip.color.b = color(2);
    sphere.color.a = line_strip.color.a = color(3) > 1e-5 ? color(3) : 1.0;
    sphere.scale.x = scale;
    sphere.scale.y = scale;
    sphere.scale.z = scale;
    line_strip.scale.x = scale / 3;
    geometry_msgs::Point pt;
    for (int i = 0; i < int(list.size()); i++)
    {
      pt.x = list[i](0);
      pt.y = list[i](1);
      pt.z = list[i](2);
      sphere.points.push_back(pt);
      line_strip.points.push_back(pt);
    }
    array.markers.push_back(sphere);
    array.markers.push_back(line_strip);
  }

  // real ids used: {1000*id ~ (arrow nums)+1000*id}
  void PlanningVisualization::generateArrowDisplayArray(visualization_msgs::MarkerArray &array,
                                                        const vector<Eigen::Vector3d> &list, double scale, Eigen::Vector4d color, int id)
  {
    visualization_msgs::Marker arrow;
    arrow.header.frame_id = "world";
    arrow.header.stamp = ros::Time::now();
    arrow.type = visualization_msgs::Marker::ARROW;
    arrow.action = visualization_msgs::Marker::ADD;

    // geometry_msgs::Point start, end;
    // arrow.points

    arrow.color.r = color(0);
    arrow.color.g = color(1);
    arrow.color.b = color(2);
    arrow.color.a = color(3) > 1e-5 ? color(3) : 1.0;
    arrow.scale.x = scale;
    arrow.scale.y = 2 * scale;
    arrow.scale.z = 2 * scale;

    geometry_msgs::Point start, end;
    for (int i = 0; i < int(list.size() / 2); i++)
    {
      // arrow.color.r = color(0) / (1+i);
      // arrow.color.g = color(1) / (1+i);
      // arrow.color.b = color(2) / (1+i);

      start.x = list[2 * i](0);
      start.y = list[2 * i](1);
      start.z = list[2 * i](2);
      end.x = list[2 * i + 1](0);
      end.y = list[2 * i + 1](1);
      end.z = list[2 * i + 1](2);
      arrow.points.clear();
      arrow.points.push_back(start);
      arrow.points.push_back(end);
      arrow.id = i + id * 1000;

      array.markers.push_back(arrow);
    }
  }

  void PlanningVisualization::displayGoalPoint(Eigen::Vector3d goal_point, Eigen::Vector4d color, const double scale, int id)
  {
    visualization_msgs::Marker sphere;
    sphere.header.frame_id = "world";
    sphere.header.stamp = ros::Time::now();
    sphere.type = visualization_msgs::Marker::SPHERE;
    sphere.action = visualization_msgs::Marker::ADD;
    sphere.id = id;

    sphere.pose.orientation.w = 1.0;
    sphere.color.r = color(0);
    sphere.color.g = color(1);
    sphere.color.b = color(2);
    sphere.color.a = color(3);
    sphere.scale.x = scale;
    sphere.scale.y = scale;
    sphere.scale.z = scale;
    sphere.pose.position.x = goal_point(0);
    sphere.pose.position.y = goal_point(1);
    sphere.pose.position.z = goal_point(2);

    goal_point_pub.publish(sphere);
  }

  void PlanningVisualization::displayGlobalPathList(vector<Eigen::Vector3d> init_pts, const double scale, int id)
  {

    if (global_list_pub.getNumSubscribers() == 0)
    {
      return;
    }

    Eigen::Vector4d color(0, 0.5, 0.5, 1);
    displayMarkerList(global_list_pub, init_pts, scale, color, id);
  }

  void PlanningVisualization::displayGuidePathList(const vector<Eigen::Vector3d> &guide_pts,
                                                   const double scale, int id)
  {
    Eigen::Vector4d color(1.0, 0.55, 0.0, 1.0);
    displayMarkerList(guide_path_pub, guide_pts, scale, color, id);
  }

  void PlanningVisualization::displayMultiInitPathList(vector<vector<Eigen::Vector3d>> init_trajs, const double scale)
  {

    if (init_list_pub.getNumSubscribers() == 0)
    {
      return;
    }

    static int last_nums = 0;

    for ( int id=0; id<last_nums; id++ )
    {
      Eigen::Vector4d color(0, 0, 0, 0);
      vector<Eigen::Vector3d> blank;
      displayMarkerList(init_list_pub, blank, scale, color, id, false);
      ros::Duration(0.001).sleep();
    }
    last_nums = 0;

    for ( int id=0; id<(int)init_trajs.size(); id++ )
    {
      Eigen::Vector4d color(0, 0, 1, 0.7);
      displayMarkerList(init_list_pub, init_trajs[id], scale, color, id, false);
      ros::Duration(0.001).sleep();
      last_nums++;
    }

  }

  void PlanningVisualization::displayInitPathList(vector<Eigen::Vector3d> init_pts, const double scale, int id)
  {

    if (init_list_pub.getNumSubscribers() == 0)
    {
      return;
    }

    Eigen::Vector4d color(0, 0, 1, 1);
    displayMarkerList(init_list_pub, init_pts, scale, color, id);
  }

  void PlanningVisualization::displayMultiOptimalPathList(vector<vector<Eigen::Vector3d>> optimal_trajs, const double scale) // zxzxzx
  {

    if (optimal_list_pub.getNumSubscribers() == 0)
    {
      return;
    }

    static int last_nums = 0;

    for ( int id=0; id<last_nums; id++ )
    {
      Eigen::Vector4d color(0, 0, 0, 0);
      vector<Eigen::Vector3d> blank;
      displayMarkerList(optimal_list_pub, blank, scale, color, id + 10, false);
      ros::Duration(0.001).sleep();
    }
    last_nums = 0;

    for ( int id=0; id<(int)optimal_trajs.size(); id++ )
    {
      Eigen::Vector4d color(1, 0, 0, 0.7);
      displayMarkerList(optimal_list_pub, optimal_trajs[id], scale, color, id + 10, false);
      ros::Duration(0.001).sleep();
      last_nums++;
    }

  }

  void PlanningVisualization::displayOptimalList(Eigen::MatrixXd optimal_pts, int id)
  {

    if (optimal_list_pub.getNumSubscribers() == 0)
    {
      return;
    }

    vector<Eigen::Vector3d> list;
    for (int i = 0; i < optimal_pts.cols(); i++)
    {
      Eigen::Vector3d pt = optimal_pts.col(i).transpose();
      list.push_back(pt);
    }
    Eigen::Vector4d color(1, 0, 0, 1);
    displayMarkerList(optimal_list_pub, list, 0.15, color, id);
  }

  void PlanningVisualization::displayFailedList(Eigen::MatrixXd failed_pts, int id)
  {

    if (failed_list_pub.getNumSubscribers() == 0)
    {
      return;
    }

    vector<Eigen::Vector3d> list;
    for (int i = 0; i < failed_pts.cols(); i++)
    {
      Eigen::Vector3d pt = failed_pts.col(i).transpose();
      list.push_back(pt);
    }
    Eigen::Vector4d color(0.3, 0, 0, 1);
    displayMarkerList(failed_list_pub, list, 0.15, color, id);
  }

  void PlanningVisualization::displayOptPolyJunctionList(const vector<Eigen::Vector3d> &junc_pts,
                                                         const bool success, int id)
  {
    ros::Publisher &pub = success ? optimal_list_pub : failed_list_pub;
    if (pub.getNumSubscribers() == 0)
      return;

    const Eigen::Vector4d color = success ? Eigen::Vector4d(1.0, 0.85, 0.0, 1.0)
                                          : Eigen::Vector4d(1.0, 0.45, 0.0, 1.0);
    displayMarkerList(pub, junc_pts, 0.22, color, id + 500);
  }

  void PlanningVisualization::displayOptResult(const Eigen::MatrixXd &cstr_pts,
                                               const vector<Eigen::Vector3d> &junc_pts,
                                               const bool success, int id)
  {
    if (success)
      displayOptimalList(cstr_pts, id);
    else
      displayFailedList(cstr_pts, id);
    displayOptPolyJunctionList(junc_pts, success, id);
  }

  void PlanningVisualization::displayAStarList(std::vector<std::vector<Eigen::Vector3d>> a_star_paths, int id /* = Eigen::Vector4d(0.5,0.5,0,1)*/)
  {

    if (a_star_list_pub.getNumSubscribers() == 0)
    {
      return;
    }

    int i = 0;
    vector<Eigen::Vector3d> list;

    Eigen::Vector4d color = Eigen::Vector4d(0.5 + ((double)rand() / RAND_MAX / 2), 0.5 + ((double)rand() / RAND_MAX / 2), 0, 1); // make the A star pathes different every time.
    double scale = 0.05 + (double)rand() / RAND_MAX / 10;

    for (auto block : a_star_paths)
    {
      list.clear();
      for (auto pt : block)
      {
        list.push_back(pt);
      }
      //Eigen::Vector4d color(0.5,0.5,0,1);
      displayMarkerList(a_star_list_pub, list, scale, color, id + i); // real ids used: [ id ~ id+a_star_paths.size() ]
      i++;
    }
  }

  void PlanningVisualization::displayArrowList(ros::Publisher &pub, const vector<Eigen::Vector3d> &list, double scale, Eigen::Vector4d color, int id)
  {
    visualization_msgs::MarkerArray array;
    // clear
    pub.publish(array);

    generateArrowDisplayArray(array, list, scale, color, id);

    pub.publish(array);
  }

  void PlanningVisualization::displayIntermediatePt(std::string type, Eigen::MatrixXd &pts, int id, Eigen::Vector4d color)
  {
    std::vector<Eigen::Vector3d> pts_;
    pts_.reserve(pts.cols());
    for ( int i=0; i<pts.cols(); i++ )
    {
      pts_.emplace_back(pts.col(i));
    }

    if ( !type.compare("0") )
    {
      displayMarkerList(intermediate_pt0_pub, pts_, 0.1, color, id);
    }
    else if ( !type.compare("1") )
    {
      displayMarkerList(intermediate_pt1_pub, pts_, 0.1, color, id);
    }
  }

  void PlanningVisualization::displayIntermediateGrad(std::string type, Eigen::MatrixXd &pts, Eigen::MatrixXd &grad, int id, Eigen::Vector4d color)
  {
    if ( pts.cols() != grad.cols() )
    {
      ROS_ERROR("pts.cols() != grad.cols()");
      return;
    }
    std::vector<Eigen::Vector3d> arrow_;
    arrow_.reserve(pts.cols()*2);
    if ( !type.compare("swarm") )
    {
      for ( int i=0; i<pts.cols(); i++ )
      {
        arrow_.emplace_back(pts.col(i));
        arrow_.emplace_back(grad.col(i));
      }
    }
    else
    {
      for ( int i=0; i<pts.cols(); i++ )
      {
        arrow_.emplace_back(pts.col(i));
        arrow_.emplace_back(pts.col(i)+grad.col(i));
      }
    }
    

    if ( !type.compare("grad0") )
    {
      displayArrowList(intermediate_grad0_pub, arrow_, 0.05, color, id);
    }
    else if ( !type.compare("grad1") )
    {
      displayArrowList(intermediate_grad1_pub, arrow_, 0.05, color, id);
    }
    else if ( !type.compare("dist") )
    {
      displayArrowList(intermediate_grad_dist_pub, arrow_, 0.05, color, id);
    }
    else if ( !type.compare("smoo") )
    {
      displayArrowList(intermediate_grad_smoo_pub, arrow_, 0.05, color, id);
    }
    else if ( !type.compare("feas") )
    {
      displayArrowList(intermediate_grad_feas_pub, arrow_, 0.05, color, id);
    }
    else if ( !type.compare("swarm") )
    {
      displayArrowList(intermediate_grad_swarm_pub, arrow_, 0.02, color, id);
    }
    
  }

  void PlanningVisualization::displaySfcCorridor(
      const std::vector<Eigen::Matrix<double, Eigen::Dynamic, 4>> &hPolys,
      const std::vector<std::pair<Eigen::Vector3d, Eigen::Vector3d>> &seed_lines,
      const Eigen::MatrixXd &waypoint_attractors,
      int id)
  {
    ROS_INFO("displaySfcCorridor1");
    visualization_msgs::MarkerArray array;
    visualization_msgs::Marker clear_marker;
    clear_marker.header.frame_id = "world";
    clear_marker.header.stamp = ros::Time::now();
    clear_marker.ns = "sfc_corridor";
    clear_marker.id = 0;
    clear_marker.action = visualization_msgs::Marker::DELETEALL;
    array.markers.push_back(clear_marker);

    int marker_id = id;
    const int poly_total = static_cast<int>(hPolys.size());
    ROS_INFO("displaySfcCorridor2");
    for (int pi = 0; pi < poly_total; ++pi)
    {
      const auto &hPoly = hPolys[pi];
      if (hPoly.rows() < 4 || !hPoly.allFinite())
        continue;

      std::vector<Eigen::Vector3d> verts;
      if (!enumeratePolytopeVertices(hPoly, verts))
      {
        ROS_WARN("[PlanningVisualization] SFC poly %d vertex enumeration failed", pi);
        continue;
      }

      const Eigen::Vector4d color = sfcPolyColor(pi, poly_total);

      visualization_msgs::Marker edge_marker;
      edge_marker.header.frame_id = "world";
      edge_marker.header.stamp = ros::Time::now();
      edge_marker.ns = "sfc_corridor/edge";
      edge_marker.id = marker_id++;
      edge_marker.type = visualization_msgs::Marker::LINE_LIST;
      edge_marker.action = visualization_msgs::Marker::ADD;
      edge_marker.pose.orientation.w = 1.0;
      edge_marker.scale.x = 0.05;
      edge_marker.color.r = color(0);
      edge_marker.color.g = color(1);
      edge_marker.color.b = color(2);
      edge_marker.color.a = color(3);

      for (size_t a = 0; a < verts.size(); ++a)
      {
        for (size_t b = a + 1; b < verts.size(); ++b)
        {
          if (sharedFaceCount(hPoly, verts[a], verts[b]) < 2)
            continue;
          edge_marker.points.push_back(toRosPoint(verts[a]));
          edge_marker.points.push_back(toRosPoint(verts[b]));
        }
      }
      if (!edge_marker.points.empty())
        array.markers.push_back(edge_marker);

      visualization_msgs::Marker mesh_marker;
      mesh_marker.header.frame_id = "world";
      mesh_marker.header.stamp = ros::Time::now();
      mesh_marker.ns = "sfc_corridor/mesh";
      mesh_marker.id = marker_id++;
      mesh_marker.type = visualization_msgs::Marker::TRIANGLE_LIST;
      mesh_marker.action = visualization_msgs::Marker::ADD;
      mesh_marker.pose.orientation.w = 1.0;
      mesh_marker.scale.x = 1.0;
      mesh_marker.scale.y = 1.0;
      mesh_marker.scale.z = 1.0;
      mesh_marker.color.r = color(0);
      mesh_marker.color.g = color(1);
      mesh_marker.color.b = color(2);
      mesh_marker.color.a = 0.15;

      Eigen::Vector3d center = Eigen::Vector3d::Zero();
      for (const auto &v : verts)
        center += v;
      center /= static_cast<double>(verts.size());

      for (size_t a = 0; a < verts.size(); ++a)
      {
        for (size_t b = a + 1; b < verts.size(); ++b)
        {
          if (sharedFaceCount(hPoly, verts[a], verts[b]) < 2)
            continue;
          mesh_marker.points.push_back(toRosPoint(center));
          mesh_marker.points.push_back(toRosPoint(verts[a]));
          mesh_marker.points.push_back(toRosPoint(verts[b]));
        }
      }
      if (!mesh_marker.points.empty())
        array.markers.push_back(mesh_marker);
    }

    if (!seed_lines.empty())
    {
      visualization_msgs::Marker seed_marker;
      seed_marker.header.frame_id = "world";
      seed_marker.header.stamp = ros::Time::now();
      seed_marker.ns = "sfc_corridor/seed";
      seed_marker.id = marker_id++;
      seed_marker.type = visualization_msgs::Marker::LINE_LIST;
      seed_marker.action = visualization_msgs::Marker::ADD;
      seed_marker.pose.orientation.w = 1.0;
      seed_marker.scale.x = 0.08;
      seed_marker.color.r = 1.0;
      seed_marker.color.g = 0.85;
      seed_marker.color.b = 0.0;
      seed_marker.color.a = 1.0;

      for (const auto &line : seed_lines)
      {
        seed_marker.points.push_back(toRosPoint(line.first));
        seed_marker.points.push_back(toRosPoint(line.second));
      }
      array.markers.push_back(seed_marker);
    }

    if (waypoint_attractors.cols() > 0)
    {
      visualization_msgs::Marker wp_marker;
      wp_marker.header.frame_id = "world";
      wp_marker.header.stamp = ros::Time::now();
      wp_marker.ns = "sfc_corridor/waypoint";
      wp_marker.id = marker_id++;
      wp_marker.type = visualization_msgs::Marker::SPHERE_LIST;
      wp_marker.action = visualization_msgs::Marker::ADD;
      wp_marker.pose.orientation.w = 1.0;
      wp_marker.scale.x = 0.18;
      wp_marker.scale.y = 0.18;
      wp_marker.scale.z = 0.18;
      wp_marker.color.r = 1.0;
      wp_marker.color.g = 0.0;
      wp_marker.color.b = 1.0;
      wp_marker.color.a = 0.9;

      for (int i = 0; i < waypoint_attractors.cols(); ++i)
        wp_marker.points.push_back(toRosPoint(waypoint_attractors.col(i)));
      array.markers.push_back(wp_marker);
    }
    ROS_INFO("displaySfcCorridor3");

    sfc_corridor_pub.publish(array);
  }

  // PlanningVisualization::
} // namespace diff_planner