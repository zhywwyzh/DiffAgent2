int16 drone_id
int32 traj_id
time start_time

uint8 order
float32[] coef_x
float32[] coef_y
float32[] coef_z
float32[] duration

# Native execution ownership; zero is reserved for non-action deployments.
uint64 execution_boot_id
uint64 execution_generation
