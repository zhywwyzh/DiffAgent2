uint8      drone_id

# Waypoint window. waypoints is a flattened xyz array with 1 to 3 points in
# travel order; a window of size 1 is a single goal. Yaw fields apply to the
# final waypoint. The final waypoint is the batch goal; an empty array is invalid.
uint32    batch_id
float32[] waypoints
float32    yaw
bool       look_forward
bool       goal_to_follower
bool       yaw_low_speed

uint8 YAW_MODE_NORMAL=0
uint8 YAW_MODE_LOW_SPEED=1
uint8 YAW_MODE_PANORAMA=2
uint8 yaw_mode

# yaw路径模式。默认使用最短角路径，全景旋转使用保持指定方向的连续角路径。
uint8 YAW_PATH_SHORTEST=0
uint8 YAW_PATH_KEEP_DIRECTION=1
uint8 yaw_path_mode
