"""系统支撑平面（support plane）。

维持 dispatcher 正常运行的系统级支撑模块所在子包：状态枚举（state）、
配置装载（config）、结构化日志（slog）、连接租约（connection_lease）、
zenoh 传输（zenoh_rpc）、RPC 传输面（rpc_plane）、传输/执行装配
（control_plane）。这些模块不是 agent 可执行工具，不进入工具发现面；
按模块直接引用，无正式 __all__ 契约（方案 §4.12）。
"""
