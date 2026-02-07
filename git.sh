#!/bin/bash

# 设置严格模式：遇到错误立即退出，未定义变量报错
set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
    exit 1
}

# 检查是否在 Git 仓库中
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    error "当前目录不是 Git 仓库！"
fi

# 获取当前分支名
current_branch=$(git symbolic-ref --short HEAD 2>/dev/null) || {
    error "无法获取当前分支名（可能处于 detached HEAD 状态）"
}

log "当前分支: $current_branch"

# 检查工作区和暂存区是否有未提交的更改
if ! git diff-index --quiet HEAD --; then
    error "工作区有未提交的更改，请先提交或 stash 后再运行此脚本。"
fi

# 获取所有 remote 名称
remotes=$(git remote)

if [ -z "$remotes" ]; then
    error "未配置任何 remote 仓库。"
fi

log "发现以下 remote 仓库：$(echo $remotes | tr '\n' ' ')"

# 1. 遍历所有 remote 进行 pull --rebase
for remote in $remotes; do
    log "正在从 $remote 拉取并 rebase..."
    url=$(git remote get-url "$remote")
    should_pull=false

    # 检查是否匹配 gitee.com 下的 hjxlinux 用户
    # 匹配 https://gitee.com/hjxlinux/... 或 git@gitee.com:hjxlinux/...
    if echo "$url" | grep -q "gitee\.com.*hjxlinux"; then
        should_pull=true
    fi

    if [ "$should_pull" = true ]; then
        log "正在从 $remote ($url) 拉取并 rebase..."
        if git pull --rebase "$remote" "$current_branch"; then
            log "成功从 $remote 拉取并 rebase。"
        else
            error "从 $remote 拉取或 rebase 失败！请手动解决冲突后重试。"
        fi
    else
        log "跳过拉取 $remote ($url) - 不符合拉取条件（非指定用户仓库）。"
    fi
done

# 2. 遍历所有 remote 进行条件推送
for remote in $remotes; do
    url=$(git remote get-url "$remote")
    should_push=false

    # 检查是否匹配 github.com 下的 cold-rivers-snow 用户
    # 匹配 https://github.com/cold-rivers-snow/... 或 git@github.com:cold-rivers-snow/...
    if echo "$url" | grep -q "github\.com.*cold-rivers-snow"; then
        should_push=true
    fi

    # 检查是否匹配 gitee.com 下的 hjxlinux 用户
    # 匹配 https://gitee.com/hjxlinux/... 或 git@gitee.com:hjxlinux/...
    if echo "$url" | grep -q "gitee\.com.*hjxlinux"; then
        should_push=true
    fi

    if [ "$should_push" = true ]; then
        log "正在推送本地更新到 $remote ($url)..."
        if git push "$remote" "$current_branch" -f; then
            log "推送到 $remote 成功！"
        else
            error "推送到 $remote 失败！请检查权限或网络问题。"
        fi
    else
        log "跳过推送 $remote ($url) - 不符合推送条件（非指定用户仓库）。"
    fi
done

log "操作完成：所有符合条件的仓库已同步。"
