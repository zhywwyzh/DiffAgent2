cmake_minimum_required(VERSION 3.5)
project(diff_planner)

set(CMAKE_BUILD_TYPE "Release")
set(CMAKE_CXX_FLAGS "-O3 -Wall -g -fPIC")
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_compile_options(-Werror=return-type)

find_package(Eigen3 REQUIRED)
find_package(PCL 1.7 REQUIRED)
find_package(OpenCV REQUIRED)

find_package(catkin REQUIRED COMPONENTS
  roscpp
  std_msgs
  geometry_msgs
  visualization_msgs
  quadrotor_msgs
  traj_utils
  message_generation
  message_filters
  cv_bridge
)

catkin_package(
  INCLUDE_DIRS include
  LIBRARIES diff_planner
  CATKIN_DEPENDS roscpp std_msgs traj_utils
)

include_directories(
  include
  SYSTEM
  ${catkin_INCLUDE_DIRS}
  ${Eigen3_INCLUDE_DIRS}
  ${PCL_INCLUDE_DIRS}
  ${OpenCV_INCLUDE_DIRS}
)

link_directories(${PCL_LIBRARY_DIRS})

file(GLOB_RECURSE srcs CONFIGURE_DEPENDS src/*.cpp)
list(FILTER srcs EXCLUDE REGEX "grid_map_bigmap")
add_library(diff_planner STATIC ${srcs})
add_dependencies(diff_planner ${catkin_EXPORTED_TARGETS} ${${PROJECT_NAME}_EXPORTED_TARGETS})
target_include_directories(diff_planner PUBLIC include)
target_link_libraries(diff_planner
  ${catkin_LIBRARIES}
  ${PCL_LIBRARIES}
  ${OpenCV_LIBRARIES}
)

add_executable(diff_planner_node Apps/diff_planner_node.cpp)
add_dependencies(diff_planner_node ${catkin_EXPORTED_TARGETS} ${${PROJECT_NAME}_EXPORTED_TARGETS})
target_link_libraries(diff_planner_node diff_planner)

add_executable(traj_server Apps/traj_server.cpp)
add_dependencies(traj_server ${catkin_EXPORTED_TARGETS} ${${PROJECT_NAME}_EXPORTED_TARGETS})
target_link_libraries(traj_server diff_planner)
