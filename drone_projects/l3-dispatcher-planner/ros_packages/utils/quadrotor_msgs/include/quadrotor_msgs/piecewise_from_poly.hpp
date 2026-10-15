#pragma once

#include <cstddef>
#include <cstdint>

#include <quadrotor_msgs/PiecewisePolynomial.h>

namespace quadrotor_msgs {

/** Fill a PiecewisePolynomial message from a piecewise polynomial trajectory.
 *
 * @tparam Traj      trajectory type exposing getPieceNum() and getDurations()
 *                   returning a column vector
 * @tparam GetPiece  callable (traj, segment) -> const reference to the piece
 *                   (getCoeffMat() with rows = axes, cols = coefficients,
 *                   getDegree() returning the polynomial degree)
 * @tparam Coeff     callable (piece, axis, power) -> coefficient value
 */
template <typename Traj, typename GetPiece, typename Coeff>
inline void FillPiecewisePolynomial(const Traj& traj, int order, const GetPiece& get_piece, const Coeff& coeff,
                                    PiecewisePolynomial& msg) {
  const int n_seg = traj.getPieceNum();
  if (n_seg <= 0) {
    return;
  }
  msg.n_seg = static_cast<uint32_t>(n_seg);
  msg.order = static_cast<uint8_t>(order);
  const auto durs = traj.getDurations();
  msg.durations.resize(n_seg);
  msg.coeffs.assign(static_cast<size_t>(n_seg) * 3 * (order + 1), 0.0);
  for (int i = 0; i < n_seg; ++i) {
    msg.durations[i] = durs(i);
    const auto& piece = get_piece(traj, i);
    const size_t base = static_cast<size_t>(i) * 3 * (order + 1);
    for (int axis = 0; axis < 3; ++axis) {
      for (int j = 0; j <= order; ++j) {
        msg.coeffs[base + static_cast<size_t>(axis) * (order + 1) + static_cast<size_t>(j)] = coeff(piece, axis, j);
      }
    }
  }
}

} // namespace quadrotor_msgs