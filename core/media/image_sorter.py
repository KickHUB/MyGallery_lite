# utils/image_sorter.py
import os
from datetime import datetime

from core.media.image_utils import organize_pngs


def organize_and_rename_pngs(source_folder, destination_root):
    """Move PNG files and rename them based on creation time."""
    organize_pngs(source_folder, destination_root, rename=True, skip_video_meta=False)

def rename_existing_pngs(destination_root):
    for date_folder in os.listdir(destination_root):
        folder_path = os.path.join(destination_root, date_folder)
        if not os.path.isdir(folder_path):
            continue

        for filename in os.listdir(folder_path):
            if filename.lower().endswith('.png'):
                file_path = os.path.join(folder_path, filename)
                try:
                    creation_time = os.path.getctime(file_path)
                    creation_time_str = datetime.fromtimestamp(creation_time).strftime('%Y%m%d_%H%M%S')
                except Exception as e:
                    print(f"⚠️ 시간 정보 오류: {filename}: {e}")
                    continue

                new_filename = f"{creation_time_str}.png"
                new_path = os.path.join(folder_path, new_filename)
                if file_path != new_path and not os.path.exists(new_path):
                    os.rename(file_path, new_path)
                    print(f"🔁 이름 변경됨: {filename} → {new_filename}")
