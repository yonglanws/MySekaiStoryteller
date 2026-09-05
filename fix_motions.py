import json
import os
from pathlib import Path

def fix_model_motions(model_dir: str):
    """为 .model3.json 补齐 Motions 字段"""
    model_dir = Path(model_dir)
    model3_files = list(model_dir.glob("*.model3.json"))
    if not model3_files:
        print(f"No .model3.json found in {model_dir}")
        return

    model3_path = model3_files[0]
    motions_dir = model_dir / "motions"

    if not motions_dir.exists():
        print(f"No motions/ folder in {model_dir}")
        return

    with open(model3_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 如果已有 Motions 且不为空，跳过
    if data.get("Motions") and len(data["Motions"]) > 0:
        print(f"Skipping {model3_path.name} - already has Motions")
        return

    body_motions = []
    facial_motions = []

    for motion_file in sorted(motions_dir.glob("*.motion3.json")):
        rel_path = f"motions/{motion_file.name}"
        name = motion_file.stem  # e.g., "w-happy-nod01" or "face_smile_01"

        entry = {
            "File": rel_path,
            "FadeInTime": 0.0,
            "FadeOutTime": 0.0
        }

        if name.startswith("face_"):
            facial_motions.append(entry)
        else:
            body_motions.append(entry)

    data["Motions"] = {}
    if body_motions:
        data["Motions"]["Body"] = body_motions
    if facial_motions:
        data["Motions"]["Facial"] = facial_motions

    with open(model3_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Fixed {model3_path.name}: Body={len(body_motions)}, Facial={len(facial_motions)}")

# 处理三个缺少 Motions 的模型
models_base = Path("resources/builtin/models")
fix_model_motions(models_base / "19ena" / "19ena_jc" / "19ena_jc_t04")
fix_model_motions(models_base / "17kanade" / "17kanade_normal" / "17kanade_normal_3.1_f_t02")
fix_model_motions(models_base / "18mafuyu" / "18mafuyu_normal" / "18mafuyu_normal_3.0_f_t05")

print("Done!")
