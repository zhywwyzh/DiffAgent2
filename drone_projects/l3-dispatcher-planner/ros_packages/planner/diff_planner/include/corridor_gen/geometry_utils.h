#pragma once

#include <corridor_gen/types.hpp>
#include <corridor_gen/sdlp.h>

namespace corridor_gen {

double DistancePointEllipsoid(double e0, double e1, double e2, double y0, double y1, double y2,
                              double &x0, double &x1, double &x2);

double findInteriorDist(const Eigen::MatrixX4d &hPoly, Eigen::Vector3d &interior);

bool findInterior(const Eigen::MatrixX4d &hPoly, Eigen::Vector3d &interior);

}  // namespace corridor_gen
