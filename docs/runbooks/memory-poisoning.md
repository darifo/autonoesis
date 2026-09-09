# Runbook: Memory Poisoning（记忆投毒）

> 适用：怀疑恶意或低质内容进入了租户 Memory,并可能经 Context 检索影响后续 Run 决策。
> 目标:阻断毒化记忆的传播,保全来源证据,清理后验证检索与 Write Gate。

## 1. 识别

- 审计事件 `memory.recorded` 的来源异常(非预期 Run/主体)。
- Run 行为漂移:评估分数下降、Grader 失败模式与某次输入相关。
- Context Snapshot 摘要冲突/注入信号(Canary)触发。

## 2. 立即动作

1. 定位毒化记录:Memory Ledger 按来源 Run/主体/时间窗过滤(租户内操作)。
2. **不要**直接物理删除:走数据主体的删除流程(墓碑 + 证明),保留 Ledger 链完整性;
   立即执行的是**撤销信任/停用**而非篡改历史。
3. 若毒化内容来自某 Pack/Agent 版本:禁用或撤销对应版本(能力包生命周期操作,
   撤销不可逆),阻断继续产出。
4. 高危时激活租户 Kill Switch 暂停读取该记忆域的 Run。

## 3. 传播评估

1. 列出读取过该记录的 ContextSnapshot(可复现摘要)及其下游 Run。
2. 对受影响 Run 的 Output 做抽检;已被污染结论的 Goal 重新执行验证。
3. 若毒化内容进入了评估 Suite 的生产回放 Case:冻结该 Suite(隐藏/回放目录隔离),
   修正后以新版本重发——固定引用的 Candidate 会失败于旧版本,这是预期防线。

## 4. 清理与验证

1. 经删除流程移除记录(删除墓碑进入审计链)。
2. 重放 Memory 相关安全套件(tests/security/test_trusted_context_memory_authority):
   Write Gate 不可绕过、向量投影清理生效。
3. 复盘来源:是 Run 输出未经验证写入(应过 Write Gate)、外部数据导入未分级,
   还是评估污染,并补对应测试。

## 5. 原则

- Memory 是受信任积累:写入必须过门禁,删除必须走证明,读取必须过 ACL——
  任何"快速修复"绕过三者之一都会扩大伤害。
