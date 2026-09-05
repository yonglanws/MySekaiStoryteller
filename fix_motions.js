const fs = require('fs')
const path = require('path')

function fixModelMotions(modelDir) {
  const model3Files = fs.readdirSync(modelDir).filter((f) => f.endsWith('.model3.json'))
  if (model3Files.length === 0) {
    console.log(`No .model3.json found in ${modelDir}`)
    return
  }

  const model3Path = path.join(modelDir, model3Files[0])
  const motionsDir = path.join(modelDir, 'motions')

  if (!fs.existsSync(motionsDir)) {
    console.log(`No motions/ folder in ${modelDir}`)
    return
  }

  const data = JSON.parse(fs.readFileSync(model3Path, 'utf-8'))

  // 如果已有 Motions 且不为空，跳过
  if (data.Motions && Object.keys(data.Motions).length > 0) {
    console.log(`Skipping ${path.basename(model3Path)} - already has Motions`)
    return
  }

  const bodyMotions = []
  const facialMotions = []

  const motionFiles = fs
    .readdirSync(motionsDir)
    .filter((f) => f.endsWith('.motion3.json'))
    .sort()
  for (const motionFile of motionFiles) {
    const relPath = `motions/${motionFile}`
    const name = motionFile.replace('.motion3.json', '')

    const entry = {
      File: relPath,
      FadeInTime: 0.0,
      FadeOutTime: 0.0
    }

    if (name.startsWith('face_')) {
      facialMotions.push(entry)
    } else {
      bodyMotions.push(entry)
    }
  }

  data.Motions = {}
  if (bodyMotions.length > 0) data.Motions.Body = bodyMotions
  if (facialMotions.length > 0) data.Motions.Facial = facialMotions

  fs.writeFileSync(model3Path, JSON.stringify(data, null, 2), 'utf-8')
  console.log(
    `Fixed ${path.basename(model3Path)}: Body=${bodyMotions.length}, Facial=${facialMotions.length}`
  )
}

const modelsBase = 'resources/builtin/models'
fixModelMotions(path.join(modelsBase, '19ena/19ena_jc/19ena_jc_t04'))
fixModelMotions(path.join(modelsBase, '17kanade/17kanade_normal/17kanade_normal_3.1_f_t02'))
fixModelMotions(path.join(modelsBase, '18mafuyu/18mafuyu_normal/18mafuyu_normal_3.0_f_t05'))

console.log('Done!')
