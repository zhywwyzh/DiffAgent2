/**
 * This file is part of ROG-Map
 *
 * Copyright 2024 Yunfan REN, MaRS Lab, University of Hong Kong, <mars.hku.hk>
 * Developed by Yunfan REN <renyf at connect dot hku dot hk>
 * for more information see <https://github.com/hku-mars/ROG-Map>.
 * If you use this code, please cite the respective publications as
 * listed on the above website.
 *
 * ROG-Map is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * ROG-Map is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with ROG-Map. If not, see <http://www.gnu.org/licenses/>.
 */

#ifndef SUPER_SCOPE_TIMER_HPP
#define SUPER_SCOPE_TIMER_HPP

#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <slog/logger.hpp>
namespace super_planner {
namespace super_utils {
class TimeConsuming {

public:
  TimeConsuming();

  TimeConsuming(std::string msg, int repeat_time) {
    repeat_time_ = repeat_time;
    msg_ = msg;
    tc_start = std::chrono::high_resolution_clock::now();
    has_shown = false;
    print_ = true;
  }

  TimeConsuming(std::string msg, bool print_log) {
    msg_ = msg;
    repeat_time_ = 1;
    print_ = print_log;
    tc_start = std::chrono::high_resolution_clock::now();
    has_shown = false;
  }

  ~TimeConsuming() {
    if (!has_shown && enable_ && print_) {
      tc_end = std::chrono::high_resolution_clock::now();
      double dt = std::chrono::duration_cast<std::chrono::duration<double>>(tc_end - tc_start).count();
      print_time(dt);
    }
  }

  void set_enbale(bool enable) { enable_ = enable; }

  void start() { tc_start = std::chrono::high_resolution_clock::now(); }

  double stop() {
    if (!enable_) {
      return 0;
    }
    has_shown = true;
    tc_end = std::chrono::high_resolution_clock::now();
    double dt = std::chrono::duration_cast<std::chrono::duration<double>>(tc_end - tc_start).count();
    if (!print_) {
      return dt;
    }
    print_time(dt);
    return dt;
  }

private:
  void print_time(const double dt) const {
    double t_us = (double)dt * 1e6 / repeat_time_;
    if (t_us < 1) {
      t_us *= 1000;
      SLOG_DEBUG(" -- [TIMER] {} time consuming {} ns", msg_, t_us);
    } else if (t_us > 1e6) {
      t_us /= 1e6;
      SLOG_DEBUG(" -- [TIMER] {} time consuming {} s", msg_, t_us);
    } else if (t_us > 1e3) {
      t_us /= 1e3;
      SLOG_DEBUG(" -- [TIMER] {} time consuming {} ms", msg_, t_us);
    } else {
      SLOG_DEBUG(" -- [TIMER] {} time consuming {} us", msg_, t_us);
    }
  }

  std::chrono::high_resolution_clock::time_point tc_start, tc_end;
  std::string msg_;
  int repeat_time_{1};
  bool has_shown = false;
  bool enable_{true};
  bool print_{true};
};
} // namespace super_utils
} // namespace super_planner

#endif
