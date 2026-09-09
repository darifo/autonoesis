# Helm Chart（工程预览）

`autonoesis/` 是 Autonoesis API / Worker / Cockpit 的工程预览 Chart。它落实 P2-01 的
部署安全域要求：

- 每个 workload 一个专用非 root `ServiceAccount`（禁用 token 自动挂载）；
- `readOnlyRootFilesystem`、drop ALL capabilities、`seccompProfile: RuntimeDefault`；
- **默认拒绝全部 Egress** 的 NetworkPolicy，仅放行声明的依赖端点（PostgreSQL /
  Temporal / OTel Collector / OPA）与集群 DNS；
- 凭证只经外部预置的 Secret 引用（`secretRefs.*`），Chart 不承载明文；可选
  `externalSecrets.enabled=true` 渲染 ExternalSecret（Vault/Secret Manager，短期凭证刷新）；
- 可选 ResourceQuota；`global.availabilityZones` 启用跨可用区 topology spread；
  RollingUpdate maxUnavailable=0 保容量升级；每个 Worker Pool 配 PodDisruptionBudget。

**边界（诚实声明）**：Chart 渲染与结构由 CI 校验（`tools/dev/validate_helm_chart.sh`，
lint + template + 必需 kind/专用 SA 断言）达到工件级验证；但未经生产集群部署、滚动
升级与多可用区实际演练，生产运行证据仍未成立。生产使用前必须补：Ingress/TLS、外部 Secret
管理器绑定、HPA、PodDisruptionBudget、备份与 DR 演练（见 docs/runbooks/backup-restore.md）。

本地渲染检查：

```bash
helm lint infra/helm/autonoesis
helm template infra/helm/autonoesis > /dev/null
```
