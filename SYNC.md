# 仓库同步说明

## 仓库关系

| 仓库 | 地址 | 角色 |
|------|------|------|
| **Gitee** | https://gitee.com/neo163/hao-yuan | **主仓库**（开发者提交入口） |
| **GitHub** | https://github.com/superneo2026/hao-yuan | **镜像仓库**（自动同步） |

## 同步机制

以 Gitee 为基础，提交后自动同步到 GitHub：

```bash
# 一键提交并双推
/root/git-submit.sh haoyuan "修复：xxx"

# 仅同步已有提交（不产生新提交）
/root/haoyuan-sync.sh          # 同步 master
/root/haoyuan-sync.sh --all    # 同步所有分支 + 标签
```

## 手动操作

```bash
cd /root/hao-yuan

# 推送 Gitee（主）
git push origin master

# 推送 GitHub（镜像）
git push github master
```

## 说明

- Gitee 推送成功即视为提交成功；GitHub 同步失败不影响主仓库
- 如果 GitHub 同步失败（网络/令牌问题），稍后执行 `/root/haoyuan-sync.sh` 补同步
