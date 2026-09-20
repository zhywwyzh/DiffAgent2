"""共享执行（执行缝）：跨技能共享的动作发送、批次记账、反馈与取消。

契约归属 l3-dispatcher/execution-seam；ports.py 承载跨家族共享动作端口，
waypoint.py 为单目标执行，skill_host.py 实现各家族宿主端口，
composition.py 为执行缝装配入口。
"""
