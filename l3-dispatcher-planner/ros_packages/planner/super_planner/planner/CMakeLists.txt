cmake_minimum_required(VERSION 3.5)
project(super_planner)

set(CMAKE_BUILD_TYPE "Release")
set(CMAKE_CXX_FLAGS "-O3 -Wall -g -fPIC")
add_compile_options(-DQT_NO_VERSION_TAGGING)
add_compile_options(-Werror=return-type)
add_compile_options(-Werror=unused-variable)
add_compile_options(-Werror=unused-but-set-variable)
set(CMAKE_CXX_STANDARD 17)

# Define the voxelize and raycasting method
add_definitions(-DORIGIN_AT_CORNER)
add_definitions(-DFMT_HEADER_ONLY)
add_definitions(-DROOT_DIR=\"${CMAKE_CURRENT_SOURCE_DIR}/\")
add_definitions(-DMCAP_COMPRESSION_NO_LZ4)
add_definitions(-DMCAP_COMPRESSION_NO_ZSTD)

# Build git revision (short hash, -dirty when uncommitted) for run_started telemetry.
# The compile container cannot reach the repo .git (bind-mount boundary), so the
# host-side Makefile writes .artifacts/build/git_version.txt; file is the fallback.
set(ENV{GIT_DISCOVERY_ACROSS_FILESYSTEM} "true")
execute_process(
        COMMAND git -C ${CMAKE_SOURCE_DIR} describe --always --dirty
        OUTPUT_VARIABLE GIT_VERSION
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET)
if(NOT GIT_VERSION)
    execute_process(
            COMMAND cat /workspace/build/git_version.txt
            OUTPUT_VARIABLE GIT_VERSION
            OUTPUT_STRIP_TRAILING_WHITESPACE
            ERROR_QUIET)
endif()
if(NOT GIT_VERSION)
    set(GIT_VERSION "unknown")
endif()
add_definitions(-DGIT_VERSION=\"${GIT_VERSION}\")


message("Using ROS1")
find_package(catkin REQUIRED COMPONENTS
        roscpp
        std_msgs
        pcl_ros
        geometry_msgs
        nav_msgs
        message_generation
        quadrotor_msgs
        visualization_msgs
        message_filters
        tf
        vis_utils
        slog
        slog_ros
)
find_package(yaml-cpp REQUIRED)
find_package(Boost REQUIRED COMPONENTS system filesystem regex iostreams)
find_package(Eigen3 REQUIRED)
find_package(PCL REQUIRED)
catkin_package(
        INCLUDE_DIRS
        LIBRARIES super_planner
        CATKIN_DEPENDS roscpp rospy std_msgs slog
        #  DEPENDS system_lib
)

include_directories(
        SYSTEM
        include
        include/third_party/mcap
        ${catkin_INCLUDE_DIRS}
        ${Eigen3_INCLUDE_DIRS}
        ${PCL_INCLUDE_DIRS}
)


set(THIRD_PARTY
        ${catkin_LIBRARIES}
        ${PCL_LIBRARIES}
        ${Boost_LIBRARIES}
        yaml-cpp
        -ldw
)

file(GLOB_RECURSE srcs CONFIGURE_DEPENDS src/*.cpp include/*.h include/*.hpp include/*.cpp)
add_library(super STATIC ${srcs})
target_include_directories(super PUBLIC
        include)
target_link_libraries(super PUBLIC
)


add_executable(fsm_node
        Apps/fsm_node_ros1.cpp
)
target_link_libraries(fsm_node
        super
        ${THIRD_PARTY}
)
