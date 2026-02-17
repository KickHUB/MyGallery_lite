# MyGallery Lite 실행 가이드

## 1) 빠른 실행 (Windows)

1. 프로젝트 루트에서 `run_mygallery_venv.bat`를 실행합니다.
2. 최초 1회는 가상환경(`venv`) 생성과 패키지 설치가 진행됩니다.
3. 설치가 끝나면 앱이 자동으로 시작됩니다.

## 2) 수동 실행

1. `python -m venv venv`
2. `venv\Scripts\activate`
3. `python -m pip install -U pip setuptools wheel`
4. `python -m pip install -r requirements.txt`
5. `python main.py`

## 3) 초기 설정 (.env)

1. `.env.example`을 복사해 `.env` 파일을 만듭니다.
2. `SOURCE`를 실제 감시할 폴더 경로로 지정합니다.
3. `DEST_FOLDER_NAME`을 지정합니다. (예: `Sorted_by_Date`)
4. `DEST`는 Lite 정책상 자동 계산됩니다. (`SOURCE/DEST_FOLDER_NAME`)
5. `.env`를 변경한 뒤 서버를 재시작합니다.

## 4) 경로 설정 후 확인

- 정상 시작 시 로그에 `watchdog 감시 시작:` 메시지가 출력됩니다.
- `SOURCE`가 비어 있거나 존재하지 않으면 감시는 시작되지 않습니다.
- 영상 썸네일/메타 처리를 쓰려면 `FFMPEG_PATH`, `FFPROBE_PATH`, `EXIFTOOL_PATH`를 설정하세요.

## 5) 설정 화면 사용

- 앱 실행 후 `관리 -> 설정`에서 경로를 지정할 수 있습니다.
- `SOURCE` 또는 경로 관련 값을 바꾼 경우 재시작 안내가 뜨면 재시작 후 사용하세요.

## 6) 개발 문서

- 개발자용 문서는 `README.dev.md`를 참고하세요.
