#pragma once

#include <map>
#include <memory>
#include <mutex>
#include <string>

#include <mcap/writer.hpp>
#include <slog/logger.hpp>

#include <ros/serialization.h>
#include <ros/message_traits.h>
#include <std_msgs/String.h>
#include <sensor_msgs/PointCloud2.h>
#include <visualization_msgs/MarkerArray.h>
#include <quadrotor_msgs/PositionCommand.h>
namespace super_planner {
namespace telemetry {
    class McapSink : public slog::Sink {
    public:
        McapSink() = default;
        ~McapSink() override { close(); }

        bool open(const std::string &dir);
        void close();
        bool isOpen() const { return open_; }

        void write(slog::Level level, int64_t ts_ns, const std::string &json_line) override;

        void writeCommand(const quadrotor_msgs::PositionCommand &cmd, int64_t ts_ns);
        void writeMarkers(const std::string &topic, const visualization_msgs::MarkerArray &arr, int64_t ts_ns);
        void writePointCloud(const std::string &topic, const sensor_msgs::PointCloud2 &cloud, int64_t ts_ns);

        void flush();

    private:
        template<typename M>
        void writeRosMsg(const std::string &topic, const M &msg, int64_t ts_ns);

        template<typename M>
        uint16_t ensureChannel(const std::string &topic);

        mcap::McapWriter writer_;
        std::unique_ptr<mcap::FileWriter> file_;
        std::mutex mu_;
        bool open_{false};
        std::map<std::string, uint16_t> channels_;
        uint32_t seq_{0};
    };

}
} // namespace super_planner
