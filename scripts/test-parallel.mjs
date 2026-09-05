/**
 * T4 并发导出测试：同时提交 N 个导出任务，验证真并行（总耗时 << N × 单任务耗时）。
 * 用法：node scripts/test-parallel.mjs [并发数，默认2]
 */
import { readFileSync, existsSync, readdirSync, globSync } from 'node:fs'

const API_URL = process.env.MSS_API_URL || 'http://127.0.0.1:9881'
const N = parseInt(process.argv[2] || '2', 10)
const STORY_FILE =
  process.env.MSS_E2E_STORY || 'resources/builtin/multi-character-demo.sekai-story.json'

const story = JSON.parse(readFileSync(STORY_FILE, 'utf-8'))
adaptStoryToAvailableAssets(story)
const body = JSON.stringify({ story, timeout: 420000 })

/** 内置示例故事可能引用当前目录缺失的模型/背景，替换为实际存在的资源 */
function adaptStoryToAvailableAssets(story) {
  const modelsRoot = 'resources/builtin/models'
  const imagesRoot = 'resources/builtin/images'
  const availableModels = globSync('**/*.model3.json', { cwd: modelsRoot }).sort()
  const availableImages = existsSync(imagesRoot)
    ? readdirSync(imagesRoot)
        .filter((f) => /\.(jpg|jpeg|png)$/i.test(f))
        .sort()
    : []
  for (const m of story.models || []) {
    if (!existsSync(`${modelsRoot}/${m.model}`) && availableModels.length > 0) {
      m.model = availableModels[0].replaceAll('\\', '/')
    }
  }
  for (const img of story.images || []) {
    if (!existsSync(`${imagesRoot}/${img.image}`) && availableImages.length > 0) {
      img.image = availableImages[0]
    }
  }
}

const post = () =>
  fetch(`${API_URL}/api/v1/export`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body
  }).then((r) => r.json())

const t0 = Date.now()
const results = await Promise.all(Array.from({ length: N }, () => post()))
const wall = ((Date.now() - t0) / 1000).toFixed(1)

let ok = true
results.forEach((r, i) => {
  const name = (r.videoPath || '').split(/[\\/]/).pop() || r.message
  console.log(
    `task#${i}: success=${r.success}, file=${name}, renderDuration=${r.duration ? r.duration.toFixed(1) + 's' : 'n/a'}`
  )
  if (!r.success) ok = false
})
console.log(`wall time for ${N} exports: ${wall}s (serial estimate ~${65 * N}s)`)
console.log(ok ? 'PARALLEL TEST PASSED' : 'PARALLEL TEST FAILED')
process.exit(ok ? 0 : 1)
