#include <corridor_gen/geometry_utils.h>
#include <corridor_gen/sdlp.h>

namespace corridor_gen {

namespace {
double DistancePointEllipse(double e0, double e1, double y0, double y1, double &x0, double &x1) {
    double distance;
    double record_sign[2] = {1, 1};
    constexpr double eps = 1e-8;
    if (y0 < 0) {
        record_sign[0] = -1;
        y0 = -y0;
    }
    if (y1 < 0) {
        record_sign[1] = -1;
        y1 = -y1;
    }

    auto getRoot = [&](double r0, double z0, double z1, double g) {
        double n0 = r0 * z0;
        double s0 = z1 - 1, s1 = (g < 0 ? 0 : sqrt(n0 * n0 + z1 * z1) - 1);
        double s = 0;
        for (int i = 0; i < 10; ++i) {
            s = (s0 + s1) / 2;
            if (s == s0 || s == s1) {
                break;
            }
            double ratio0 = n0 / (s + r0), ratio1 = z1 / (s + 1);
            g = ratio0 * ratio0 + ratio1 * ratio1 - 1;
            if (g > 0) {
                s0 = s;
            }
            else if (g < 0) {
                s1 = s;
            }
            else {
                break;
            }
        }
        return s;
    };

    if (y1 > eps) {
        if (y0 > eps) {
            double z0 = y0 / e0, z1 = y1 / e1, g = z0 * z0 + z1 * z1 - 1;
            if (g != 0) {
                double r0 = e0 * e0 / e1 / e1, sbar = getRoot(r0, z0, z1, g);
                x0 = r0 * y0 / (sbar + r0);
                x1 = y1 / (sbar + 1);
                distance = sqrt((x0 - y0) * (x0 - y0) + (x1 - y1) * (x1 - y1));
            }
            else {
                x0 = y0;
                x1 = y1;
                distance = 0;
            }
        }
        else {
            // y0 == 0
            x0 = 0;
            x1 = e1;
            distance = fabs(y1 - e1);
        }
    }
    else {
        // y1 == 0
        double numer0 = e0 * y0, denom0 = e0 * e0 - e1 * e1;
        if (numer0 < denom0) {
            double xde0 = numer0 / denom0;
            x0 = e0 * xde0;
            x1 = e1 * sqrt(1 - xde0 * xde0);
            distance = sqrt((x0 - y0) * (x0 - y0) + x1 * x1);
        }
        else {
            x0 = e0;
            x1 = 0;
            distance = fabs(y0 - e0);
        }
    }
    x0 *= record_sign[0];
    x1 *= record_sign[1];

    return distance;
}

}  // namespace

double DistancePointEllipsoid(double e0, double e1, double e2, double y0, double y1, double y2,
                              double &x0, double &x1, double &x2) {
    auto getRoot = [&](double r0, double r1, double z0, double z1, double z2, double g) {
        double n0 = r0 * z0, n1 = r1 * z1;
        double s0 = z2 - 1, s1 = (g < 0 ? 0 : sqrt(n0 * n0 + n1 * n1 + z2 * z2) - 1);
        double s = 0;
        const int maxIterations = 10;
        for (int i = 0; i < maxIterations; ++i) {
            s = (s0 + s1) / 2;
            if (s == s0 || s == s1) {
                break;
            }
            double ratio0 = n0 / (s + r0), ratio1 = n1 / (s + r1), ratio2 = z2 / (s + 1);
            g = (ratio0 * ratio0) + (ratio1 * ratio1) + (ratio2 * ratio2) - 1;
            if (g > 0) {
                s0 = s;
            }
            else if (g < 0) {
                s1 = s;
            }
            else {
                break;
            }
        }
        return s;
    };
    constexpr double eps = 1e-8;
    double distance;
    double record_sign[3] = {1, 1, 1};

    if (y0 < 0) {
        record_sign[0] = -1;
        y0 = -y0;
    }
    if (y1 < 0) {
        record_sign[1] = -1;
        y1 = -y1;
    }
    if (y2 < 0) {
        record_sign[2] = -1;
        y2 = -y2;
    }

    if (y2 > eps) {
        if (y1 > eps) {
            if (y0 > eps) {
                double z0 = y0 / e0, z1 = y1 / e1, z2 = y2 / e2;
                double g = sqrt(z0 * z0 + z1 * z1 + z2 * z2) - 1;

                if (g != 0) {
                    double r0 = e0 * e0 / e2 / e2, r1 = e1 * e1 / e2 / e2;
                    double sbar = getRoot(r0, r1, z0, z1, z2, g);

                    x0 = r0 * y0 / (sbar + r0);
                    x1 = r1 * y1 / (sbar + r1);
                    x2 = y2 / (sbar + 1);

                    distance = sqrt((x0 - y0) * (x0 - y0) +
                        (x1 - y1) * (x1 - y1) +
                        (x2 - y2) * (x2 - y2));
                }
                else {
                    x0 = y0;
                    x1 = y1;
                    x2 = y2;
                    distance = 0;
                }
            }
            else // y0 == 0
            {
                x0 = 0;
                distance = DistancePointEllipse(e1, e2, y1, y2, x1, x2);
            }
        }
        else // y1 == 0
        {
            if (y0 > 0) {
                x1 = 0;
                distance = DistancePointEllipse(e0, e2, y0, y2, x0, x2);
            }
            else // y0 == 0
            {
                x0 = 0;
                x1 = 0;
                x2 = e2;
                distance = fabs(y2 - e2);
            }
        }
    }
    else // y2 == 0
    {
        double denom0 = e0 * e0 - e2 * e2, denom1 = e1 * e1 - e2 * e2;
        double numer0 = e0 * y0, numer1 = e1 * y1;
        bool computed = false;

        if (numer0 < denom0 && numer1 < denom1) {
            double xde0 = numer0 / denom0, xde1 = numer1 / denom1;
            double discr = 1 - xde0 * xde0 - xde1 * xde1;

            if (discr > 0) {
                x0 = e0 * xde0;
                x1 = e1 * xde1;
                x2 = e2 * sqrt(discr);

                distance = sqrt((x0 - y0) * (x0 - y0) +
                    (x1 - y1) * (x1 - y1) +
                    x2 * x2);
                computed = true;
            }
        }
        if (!computed) {
            x2 = 0;
            distance = DistancePointEllipse(e0, e1, y0, y1, x0, x1);
        }
    }
    x0 *= record_sign[0];
    x1 *= record_sign[1];
    x2 *= record_sign[2];
    return distance;
}

double findInteriorDist(const Eigen::MatrixX4d &hPoly, Eigen::Vector3d &interior) {
    const int m = hPoly.rows();

    Eigen::MatrixX4d A(m, 4);
    Eigen::VectorXd b(m);
    Eigen::Vector4d c, x;
    const Eigen::ArrayXd hNorm = hPoly.leftCols<3>().rowwise().norm();
    A.leftCols<3>() = hPoly.leftCols<3>().array().colwise() / hNorm;
    A.rightCols<1>().setConstant(1.0);
    b = -hPoly.rightCols<1>().array() / hNorm;
    c.setZero();
    c(3) = -1.0;

    const double minmaxsd = math_utils::sdlp::linprog<4>(c, A, b, x);
    interior = x.head<3>();
    return -minmaxsd;
}

bool findInterior(const Eigen::MatrixX4d &hPoly, Eigen::Vector3d &interior) {
    const int m = hPoly.rows();

    Eigen::MatrixX4d A(m, 4);
    Eigen::VectorXd b(m);
    Eigen::Vector4d c, x;
    const Eigen::ArrayXd hNorm = hPoly.leftCols<3>().rowwise().norm();
    A.leftCols<3>() = hPoly.leftCols<3>().array().colwise() / hNorm;
    A.rightCols<1>().setConstant(1.0);
    b = -hPoly.rightCols<1>().array() / hNorm;
    c.setZero();
    c(3) = -1.0;

    const double minmaxsd = math_utils::sdlp::linprog<4>(c, A, b, x);
    interior = x.head<3>();

    return minmaxsd < 0.0 && !std::isinf(minmaxsd);
}

}  // namespace corridor_gen
