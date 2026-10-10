"""跟踪 RGB 和标定入站；只写纯数据缓存。"""
import rospy
from sensor_msgs.msg import CameraInfo, CompressedImage
from dispatcher.support.tracking_data import EncodedRGB


class TrackingFramesRos:
    def __init__(self, store):
        self.store = store
        self.subscribers = []
        try:
            self.subscribers.append(rospy.Subscriber(rospy.get_param('~track/info_topic', '/camera/color/camera_info'),
                CameraInfo, self.info, queue_size=1))
            self.subscribers.append(rospy.Subscriber(rospy.get_param('~track/rgb_topic', '/camera/color/image_raw/compressed'),
                CompressedImage, self.rgb, queue_size=2, buff_size=16*1024*1024))
        except Exception:
            self.close()
            raise

    def info(self, msg):
        with self.store.lock:
            self.store.intrinsics = dict(fx=msg.K[0], fy=msg.K[4], cx=msg.K[2], cy=msg.K[5],
                width=msg.width, height=msg.height, frame_id=msg.header.frame_id)

    def rgb(self, msg):
        with self.store.lock:
            info = self.store.intrinsics
            if info and ('jpeg' in msg.format or 'jpg' in msg.format):
                self.store.add_rgb(msg.header.stamp.to_nsec(),
                    EncodedRGB(bytes(msg.data), (info['height'], info['width'], 3)))

    @staticmethod
    def now():
        return rospy.Time.now().to_sec()

    def close(self):
        for sub in reversed(self.subscribers):
            sub.unregister()
