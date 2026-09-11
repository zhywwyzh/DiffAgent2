cmake_minimum_required(VERSION 2.8.3)
project(ego_planner)

set(CMAKE_BUILD_TYPE "Release")
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -Wall -g")

find_package(Eigen3 REQUIRED)
find_package(PCL 1.7 REQUIRED)
find_package(OpenCV REQUIRED)

find_package(catkin REQUIRED COMPONENTS
  roscpp
  rospy
  std_msgs
  sensor_msgs
  nav_msgs
  geometry_msgs
  quadrotor_msgs
  visualization_msgs
  traj_utils
  message_generation
  cv_bridge
  message_filters
  vis_utils
  tf
  pcl_ros
)

catkin_package(
 INCLUDE_DIRS include
 LIBRARIES ego_planner
 CATKIN_DEPENDS traj_utils vis_utils
)

include_directories(
  include
  SYSTEM
  ${catkin_INCLUDE_DIRS} ${PROJECT_SOURCE_DIR}/include
  ${EIGEN3_INCLUDE_DIR}
  ${PCL_INCLUDE_DIRS}
  ${OpenCV_INCLUDE_DIRS}
)

add_library(ego_planner
  src/ego_replan_fsm.cpp
  src/planner_manager.cpp
  src/traj_server.cpp
  src/poly_traj_optimizer.cpp
  src/oc_a_star.cpp
  src/dyn_a_star.cpp
  src/grid_map.cpp
  src/raycast.cpp
  src/grid_map_frontier_part.cpp
  )

target_link_libraries(ego_planner 
  ${catkin_LIBRARIES}
  ${PCL_LIBRARIES}
  ${OpenCV_LIBRARIES}
)

add_executable(ego_planner_node src/ego_planner_node.cpp)
target_link_libraries(ego_planner_node ego_planner ${catkin_LIBRARIES})
add_dependencies(ego_planner ${catkin_EXPORTED_TARGETS} ${${PROJECT_NAME}_EXPORTED_TARGETS})
add_dependencies(ego_planner_node ${catkin_EXPORTED_TARGETS} ${${PROJECT_NAME}_EXPORTED_TARGETS})
