# dispatcher 与只读 l4 消费者的 RPC 闭环交付

日期：2026-09-17

现行协议归 `specs/implemented/inner/l3-l4-rpc.spec.md`。

RPC 终态直接取唯一 runtime 记录的 name/call_id，移除入队后才登记的第二张关联表，
使快速完成不再丢失 outcome。重放同样经过 owner 门，租约和调用账本采用一致锁序，
避免释放检查与准入锁反转；旧租约回调和过期检查不影响新 owner 或已经续约的租约。

成功 acquire 接入 owner token 监听。TTL watchdog 仍是超时保障，监听失败留诊断。
非法请求统一回复；关闭可打断重试等待，部分启动失败释放已获取资源。

103 项回归通过，包含真实回环 Zenoh 与只读加载的 l4 fleet/client/flight bridge。
测试能力未进入生产集合；通用控制面闭环不等于基础飞行已实现。线上 pub/sub 不承诺
断线后的持久结果补发，安全停止端口验证不代表下游物理制动已经完成。
