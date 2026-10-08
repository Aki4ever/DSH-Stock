#!/usr/bin/env node
/**
 * ==============================================================================
 * REQ-128 · launchd 引导器（借 DSH 应用的 TCC 身份，绕过 macOS「文稿」保护）
 * ------------------------------------------------------------------------------
 * 为什么需要这一层（2026-10-08 实测留痕，不是推测）：
 *   macOS 的 TCC 隐私保护把 `~/Documents` 列为受保护目录。用户级 LaunchAgent
 *   直接执行工程内脚本时，实测 `launchd.log` 得到：
 *       shell-init: error retrieving current directory: getcwd: cannot access parent
 *       directories: Operation not permitted
 *       /bin/bash: .../scripts/ensure_server.sh: Operation not permitted
 *       last exit code = 126
 *   对照探针（脚本放到 ~/Library/Application Support、工作目录 /tmp）同样
 *   `READ_DOCUMENTS=fail` —— 说明拦截点是**读文稿目录**这件事本身，与脚本放哪无关；
 *   纯 launchd 路线若不授予「完全磁盘访问权限」不可能成功。
 *
 *   反证（同机实测）：以 `ELECTRON_RUN_AS_NODE=1` 运行 DSH 应用本体
 *   （/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness，
 *   签名身份 com.deepseek.dsh —— 该应用已具备文稿访问授权）时 `READ_DOCUMENTS=ok`。
 *   于是由它作为**家长进程**拉起 ensure_server.sh，子进程继承同一授权，
 *   既不需要用户去系统设置里点授权，也不需要把工程挪出文稿目录。
 *
 * 行为：
 *   spawn `bash <工程>/scripts/ensure_server.sh`（幂等，唯一启动口径），
 *   输出追加到 `<工程>/launchd.log`，等待其结束并**透传退出码**
 *   （launchd 依退出码记录 last exit code，便于 status 自证）。
 * ==============================================================================
 */

const { spawn } = require('node:child_process')
const { openSync } = require('node:fs')
const path = require('node:path')

const ROOT = path.resolve(__dirname, '..')
const ENSURE = path.join(ROOT, 'scripts', 'ensure_server.sh')
const LOG = path.join(ROOT, 'launchd.log')

let out = 'ignore'
try {
  out = openSync(LOG, 'a')
} catch {
  out = 'ignore'
}

const child = spawn('/bin/bash', [ENSURE], {
  cwd: ROOT,
  stdio: ['ignore', out, out],
  env: process.env,
})

child.on('error', (err) => {
  process.stderr.write(`[launchd_bootstrap] 拉起 ensure_server.sh 失败：${err.message}\n`)
  process.exit(1)
})

child.on('exit', (code, signal) => {
  // 透传退出码：0 = 服务端当时已健康或已被拉起到位
  process.exit(signal ? 1 : (typeof code === 'number' ? code : 1))
})
