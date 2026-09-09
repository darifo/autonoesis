# 软件供应链

未来负责 Capability Pack 签名、SBOM、镜像签名、来源允许列表、依赖扫描和发布证明。


## CI 供应链门禁（P2-03 已接线）

- **SBOM**：Python（cyclonedx-py over uv export）、Node Cockpit（cyclonedx-npm）、
  Capability Pack（`tools/security/pack_sbom.py`，含内容摘要/签名/依赖图）、镜像
  （trivy cyclonedx）；全部随 CI 证据归档 30 天。
- **扫描**：SAST（bandit -ll SARIF）、SCA（pip-audit --strict + pnpm audit --prod）、
  Secret（tools/security/scan_secrets.py + trivy secret）、容器与 IaC 错配（trivy fs
  misconfig）、镜像漏洞（trivy image）。
- **Provenance**：镜像经 actions/attest-build-provenance 生成 SLSA 构建证明
  （keyless，绑定 commit 与 workflow）；Capability Pack 以仓库开发密钥签名（生产
  密钥待流水线注入）。
- **依赖升级**：dependabot 每周分组 PR；回滚 = revert uv.lock/pnpm-lock.yaml，
  由同一 CI 门禁验证。
- **镜像纯净性**：`.dockerignore` + per-package 构建（`--no-dev --package`）+
  `tools/security/verify_image_purity.sh` 断言（无开发依赖/测试/git 历史/开发签名密钥）。
