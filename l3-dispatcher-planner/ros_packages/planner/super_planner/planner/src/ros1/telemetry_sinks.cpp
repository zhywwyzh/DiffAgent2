#define MCAP_IMPLEMENTATION
#include <ros_interface/ros1/telemetry_sinks.hpp>

#include <filesystem>
namespace super_planner {
namespace telemetry {
    bool McapSink::open(const std::string &dir) {
        std::lock_guard<std::mutex> lk(mu_);
        std::error_code ec;
        std::filesystem::create_directories(dir, ec);
        if (ec) {
            SLOG_ERROR("[telemetry] failed to create mcap dir {}: {}", dir, ec.message());
            return false;
        }
        const int64_t ts_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count();
        const std::string path = dir + "/nav-" + std::to_string(ts_ns) + ".mcap";

        file_ = std::make_unique<mcap::FileWriter>();
        const auto st = file_->open(path);
        if (!st.ok()) {
            SLOG_ERROR("[telemetry] failed to open mcap file {}: {}", path, st.message);
            file_.reset();
            return false;
        }
        mcap::McapWriterOptions options("ros1");
        options.noChunking = true;
        options.noSummary = false;
        writer_.open(*file_, options);
        open_ = true;
        SLOG_INFO("[telemetry] mcap recording to {}", path);
        return true;
    }

    void McapSink::close() {
        std::lock_guard<std::mutex> lk(mu_);
        if (!open_) {
            return;
        }
        writer_.close();
        file_->flush();
        file_.reset();
        open_ = false;
    }

    template<typename M>
    uint16_t McapSink::ensureChannel(const std::string &topic) {
        const auto it = channels_.find(topic);
        if (it != channels_.end()) {
            return it->second;
        }
        mcap::Schema schema(ros::message_traits::DataType<M>::value(),
                            "ros1msg",
                            ros::message_traits::Definition<M>::value());
        writer_.addSchema(schema);
        mcap::Channel channel(topic, "ros1", schema.id);
        writer_.addChannel(channel);
        channels_[topic] = channel.id;
        return channel.id;
    }

    template<typename M>
    void McapSink::writeRosMsg(const std::string &topic, const M &msg, const int64_t ts_ns) {
        const uint16_t channel_id = ensureChannel<M>(topic);
        ros::SerializedMessage sm = ros::serialization::serializeMessage(msg);
        /* serializeMessage prefixes the payload with a uint32 LE length header
         * (ROS transport framing). The mcap ros1msg schema holds only the bare
         * serialized message, so skip the header via message_start. */
        mcap::Message m;
        m.channelId = channel_id;
        m.sequence = seq_++;
        m.logTime = static_cast<mcap::Timestamp>(ts_ns);
        m.publishTime = m.logTime;
        m.data = reinterpret_cast<const std::byte *>(sm.message_start);
        m.dataSize = sm.num_bytes - 4;
        static_cast<void>(writer_.write(m));
    }

    void McapSink::write(const slog::Level /*level*/, const int64_t ts_ns, const std::string &json_line) {
        std::lock_guard<std::mutex> lk(mu_);
        if (!open_) {
            return;
        }
        std_msgs::String str;
        str.data = json_line;
        writeRosMsg("/telemetry/log", str, ts_ns);
    }

    void McapSink::writeCommand(const quadrotor_msgs::PositionCommand &cmd, const int64_t ts_ns) {
        std::lock_guard<std::mutex> lk(mu_);
        if (!open_) {
            return;
        }
        writeRosMsg("/setpoint_cmd", cmd, ts_ns);
    }

    void McapSink::writeMarkers(const std::string &topic, const visualization_msgs::MarkerArray &arr,
                                const int64_t ts_ns) {
        std::lock_guard<std::mutex> lk(mu_);
        if (!open_) {
            return;
        }
        writeRosMsg(topic, arr, ts_ns);
    }

    void McapSink::writePointCloud(const std::string &topic, const sensor_msgs::PointCloud2 &cloud,
                                   const int64_t ts_ns) {
        std::lock_guard<std::mutex> lk(mu_);
        if (!open_) {
            return;
        }
        writeRosMsg(topic, cloud, ts_ns);
    }

    void McapSink::flush() {
        std::lock_guard<std::mutex> lk(mu_);
        if (open_ && file_) {
            file_->flush();
        }
    }

}
} // namespace super_planner
